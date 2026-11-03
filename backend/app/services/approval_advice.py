"""AI advice for the approver (agents/approval_advice.py), stored on the approval and audited.

Generated when an approval is requested, when it moves up to the Director, and when the case
changes under it. The advice is shown to the approver and put in their email; it never decides.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app import audit
from app.agents import approval_advice
from app.agents.approval_router import MANAGER_LIMIT_INR
from app.config import get_settings
from app.enums import ActorType, Flag, IssueStatus, RecStatus, Role
from app.faults import get_flags
from app.llm.client import LLMClient
from app.models import Approval
from app.normalize import ist_label


def advice_facts(approval: Approval) -> dict[str, Any]:
    case, rec = approval.case, approval.recommendation
    reconciled = next(
        (r for r in case.risk_assessments if r.is_current and r.agent == "reconciled"), None
    )
    manager = approval.approver_role == Role.OPS_MANAGER
    limit = approval.assigned_to.approval_limit_inr if approval.assigned_to else MANAGER_LIMIT_INR
    return {
        "ref": case.ref,
        "subject": case.subject,
        "option": rec.title,
        "description": rec.description,
        "agent_rationale": rec.rationale,
        "amount_inr": approval.amount_inr,
        "lead_time_days": rec.estimated_lead_time_days,
        "risk_level": reconciled.risk_level if reconciled else None,
        "case_confidence": round(case.overall_confidence, 2),
        "deadline": ist_label(case.deadline_at),
        "reasons": approval.reasons,
        "open_issues": [i.message for i in case.issues if i.status == IssueStatus.OPEN][:5],
        "stale_reason": approval.stale_reason if approval.stale else None,
        "routing_note": approval.routing_note,
        "alternatives": [
            {
                "title": r.title,
                "cost_inr": r.estimated_cost_inr,
                "lead_time_days": r.estimated_lead_time_days,
            }
            for r in case.recommendations
            if r.status == RecStatus.PROPOSED and r.id != rec.id
        ],
        "approver_role": approval.approver_role,
        "approver_limit_inr": limit if manager else None,
        "escalation_level": approval.escalation_level,
    }


def refresh(db: Session, approval: Approval, *, reason: str) -> dict[str, Any]:
    """(Re)generate the advice for the current approver and record it in the audit trail."""
    llm = LLMClient(get_settings(), llm_down=get_flags(db)[str(Flag.LLM_DOWN)])
    advice, result = approval_advice.advise(advice_facts(approval), llm)
    approval.advice = advice
    audit.log_event(
        db,
        action="approval.advice",
        actor="approval_advisor",
        actor_type=ActorType.AGENT,
        request_id=approval.request_id,
        after={"approval_id": approval.id, "for": approval.approver_role, **advice},
        reason=reason,
        meta=audit.AgentMeta(
            model=advice["model"],
            prompt_hash=result.prompt_hash,
            latency_ms=result.latency_ms,
            tokens=result.tokens,
        ),
    )
    return advice


def summary_line(advice: dict[str, Any] | None) -> str | None:
    """One line for the approver's email."""
    if not advice:
        return None
    label = {"approve": "Approve", "reject": "Reject", "forward": "Forward to the Director"}
    return f"{label[advice['suggestion']]}. {advice['rationale']}"
