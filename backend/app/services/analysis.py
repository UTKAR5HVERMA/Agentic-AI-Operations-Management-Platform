"""Runs the agent graph for a case and persists its output (one transaction, fully audited).

Two modes:
- full: case moves ANALYZING → NEEDS_INFO / PENDING_REVIEW / DUPLICATE.
- status-preserving reassessment: when approvals are in flight or work has started, the status
  is kept; new options supersede old ones and in-flight approvals are marked stale (edge 9).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.agents import graph
from app.agents.common import AgentContext
from app.agents.risk import PRIORITY_BY_RISK
from app.agents.state import CaseState
from app.audit import AgentMeta
from app.config import get_settings
from app.db import SessionLocal, get_engine, utcnow
from app.enums import (
    IN_FLIGHT_APPROVALS,
    ActorType,
    CommStatus,
    FieldSource,
    Flag,
    IssueStatus,
    Priority,
    RecStatus,
    RiskAgentName,
    Status,
)
from app.faults import get_flags
from app.llm.client import LLMClient
from app.models import (
    Case,
    Communication,
    ExtractedField,
    Issue,
    Recommendation,
    RiskAssessment,
    Supplier,
)
from app.services import approval_advice, inventory
from app.state_machine import TERMINAL, transition

log = logging.getLogger(__name__)
DEDUP_WINDOW_DAYS = 14
SLA_HOURS = {Priority.P1: 4, Priority.P2: 24, Priority.P3: 72, Priority.P4: 120}
AUTO_RESOLVED_NOTE = "No longer detected after re-analysis"
PRESERVE_STATUSES = {Status.PENDING_APPROVAL, Status.ESCALATED, Status.APPROVED, Status.IN_PROGRESS}
OUTCOME_STATUS = {
    "duplicate": Status.DUPLICATE,
    "needs_info": Status.NEEDS_INFO,
    "pending_review": Status.PENDING_REVIEW,
}


def current_fields(case: Case) -> dict[str, ExtractedField]:
    return {f.field: f for f in case.fields if f.is_current}


def _field_dict(row: ExtractedField) -> dict[str, Any]:
    return {
        "value": row.value,
        "normalized": row.normalized_value,
        "evidence": row.evidence,
        "confidence": row.confidence,
        "source": row.source,
        "ambiguous": False,
    }


def _open_cases(db: Session, case: Case) -> list[dict[str, Any]]:
    since = utcnow() - timedelta(days=DEDUP_WINDOW_DAYS)
    rows = db.scalars(
        select(Case).where(
            Case.id != case.id,
            Case.created_at >= since,
            Case.status.not_in(list(TERMINAL)),
        )
    )
    out = []
    for other in rows:
        if other.id == case.parent_id or other.parent_id == case.id:
            continue  # a split parent and its children are related, not duplicates
        f = current_fields(other)

        def norm(name: str, fields: dict[str, ExtractedField] = f) -> Any:
            return fields[name].normalized_value if name in fields else None

        out.append(
            {
                "id": other.id,
                "ref": other.ref,
                "location": norm("location"),
                "sku": norm("item"),
                "quantity": norm("quantity_required"),
                "delay_days": norm("delay_days"),
                "text": f"{other.subject} {other.sanitized_text}",
            }
        )
    return out


def _suppliers(db: Session) -> list[dict[str, Any]]:
    return [
        {
            "name": s.name,
            "items": s.items,
            "lead_time_days": s.lead_time_days,
            "reliability_score": s.reliability_score,
            "is_primary": s.is_primary,
            "express_cost_per_unit_inr": s.express_cost_per_unit_inr,
        }
        for s in db.scalars(select(Supplier))
    ]


def analyse_new_case(case_id: str) -> None:
    """Background job: run the agents on a freshly submitted case in its own session.

    The submitter gets an immediate response; if this job dies, the scheduler picks the case up.
    """
    get_engine()
    with SessionLocal() as db:
        case = db.get(Case, case_id)
        if case is None or case.status != Status.NEW:
            return
        try:
            run_analysis(
                db, case, actor="orchestrator", actor_type=ActorType.SYSTEM, reason="New request"
            )
            db.commit()
        except Exception:
            db.rollback()
            log.exception("analysis.background_failed", extra={"case_id": case_id})


def build_state(db: Session, case: Case, start_at: str, now: datetime) -> CaseState:
    fields = current_fields(case)
    locked = {
        k: _field_dict(v)
        for k, v in fields.items()
        if v.source in {FieldSource.HUMAN, FieldSource.EVENT}
    }
    state: CaseState = {
        "request_id": case.id,
        "ref": case.ref,
        "start_at": start_at,
        "subject": case.subject,
        "raw_text": case.raw_text,
        "channel": case.channel,
        "sender_email": case.sender_email,
        "sender_name": case.sender_name,
        "received_at": case.received_at.isoformat(),
        "analysis_at": now.isoformat(),
        "category_hint": None,
        "locked_fields": locked,
        "inventory_snapshot": inventory.snapshot(db),
        "suppliers": _suppliers(db),
        "catalog": inventory.catalog(db),
        "open_cases": _open_cases(db, case),
        "excluded_kinds": [
            r.kind
            for r in case.recommendations
            if r.status == RecStatus.REJECTED and r.kind != "custom"
        ],
        "suppressed_issue_keys": [
            i.key for i in case.issues if i.status != IssueStatus.OPEN and i.resolved_by_id
        ],
        "dedup_dismissed": case.dedup_dismissed,
        "issues": [],
        "trace": [],
        "audit_events": [],
        "degraded_reasons": [],
        "risk": {},
    }
    if start_at != "intake":  # resume from persisted extraction
        state.update(
            sanitized_text=case.sanitized_text,
            category=case.category,
            fields={k: _field_dict(v) for k, v in fields.items()},
            injection=case.injection_details or {"flag": case.injection_flag},
        )
    return state


def run_analysis(
    db: Session,
    case: Case,
    *,
    actor: str,
    actor_type: ActorType = ActorType.HUMAN,
    start_at: str = "intake",
    reason: str | None = None,
    preserve_status: bool = False,
) -> CaseState:
    """Run the graph for `case` and persist everything. Caller commits."""
    settings = get_settings()
    preserve = (
        preserve_status
        or Status(case.status) in PRESERVE_STATUSES
        or any(a.status in IN_FLIGHT_APPROVALS for a in case.approvals)
    )
    if not preserve:
        transition(db, case, Status.ANALYZING, actor=actor, actor_type=actor_type, reason=reason)
    llm = LLMClient(settings, llm_down=get_flags(db)[str(Flag.LLM_DOWN)])
    out = graph.run(build_state(db, case, start_at, utcnow()), AgentContext(llm, settings))

    _persist(db, case, out, start_at=start_at, preserve=preserve)
    for event in out.get("audit_events", []):
        audit.log_event(
            db,
            action=event["action"],
            actor=event["actor"],
            actor_type=ActorType.AGENT,
            request_id=case.id,
            after=event.get("after"),
            reason=event.get("reason"),
            meta=AgentMeta(
                model=event.get("model"),
                prompt_hash=event.get("prompt_hash"),
                latency_ms=event.get("latency_ms"),
                tokens=event.get("tokens"),
                confidence=event.get("confidence"),
            ),
        )
    if preserve:
        _mark_approvals_stale(db, case, reason or "Case re-assessed", actor)
    else:
        _finish(db, case, out, actor, actor_type)
    return out


def _finish(db: Session, case: Case, out: CaseState, actor: str, actor_type: ActorType) -> None:
    outcome = out.get("outcome", "pending_review")
    if outcome == "duplicate":
        master = out["duplicates"][0]
        case.duplicate_of_id = master["id"]
        audit.log_event(
            db,
            action="dedup.linked",
            actor="dedup",
            actor_type=ActorType.AGENT,
            request_id=case.id,
            after=master,
            reason=f"Similarity {master['similarity']:.0%} ≥ auto-link threshold",
        )
    transition(
        db,
        case,
        OUTCOME_STATUS.get(outcome, Status.PENDING_REVIEW),
        actor="orchestrator",
        actor_type=ActorType.SYSTEM,
        reason=f"Analysis outcome: {outcome}",
    )


def _mark_approvals_stale(db: Session, case: Case, reason: str, actor: str) -> None:
    for approval in case.approvals:
        if approval.status in IN_FLIGHT_APPROVALS and not approval.stale:
            approval.stale, approval.stale_reason = True, reason
            audit.log_event(
                db,
                action="approval.marked_stale",
                actor=actor,
                actor_type=ActorType.SYSTEM,
                request_id=case.id,
                after={"approval_id": approval.id},
                reason=reason,
            )
            approval_advice.refresh(db, approval, reason=f"Case changed: {reason}")


def _persist(db: Session, case: Case, out: CaseState, *, start_at: str, preserve: bool) -> None:
    if start_at == "intake":
        case.sanitized_text = out["sanitized_text"]
        case.injection_flag = bool(out["injection"].get("flag"))
        case.injection_details = out["injection"]
        case.sub_requests = out.get("sub_requests", [])
        case.duplicate_candidates = out.get("duplicates", [])
    case.category = out.get("category", case.category)
    _persist_fields(db, case, out.get("fields", {}))
    _merge_issues(db, case, out)
    if out.get("risk", {}).get("reconciled"):
        _persist_risk(db, case, out["risk"])
    _persist_recommendations(db, case, out.get("recommendations", []))
    _persist_drafts(db, case, out.get("drafts", []))
    _update_case(case, out)


def _persist_fields(db: Session, case: Case, fields: dict[str, dict[str, Any]]) -> None:
    existing = current_fields(case)
    for name, f in fields.items():
        row = existing.get(name)
        if row is not None and row.value == f["value"] and row.source == f["source"]:
            row.confidence, row.normalized_value, row.evidence = (
                f["confidence"],
                f["normalized"],
                f["evidence"],
            )
            continue
        if row is not None:
            row.is_current = False
        db.add(
            ExtractedField(
                request_id=case.id,
                field=name,
                value=f["value"],
                normalized_value=f["normalized"],
                evidence=f["evidence"],
                confidence=f["confidence"],
                source=f["source"],
                case=case,
            )
        )


def _ran_agents(out: CaseState) -> set[str]:
    ran = {t["agent"] for t in out.get("trace", []) if t.get("llm_status") != "skipped"}
    if "recommendation" in ran:
        ran.add("score")
    return ran


def _merge_issues(db: Session, case: Case, out: CaseState) -> None:
    new: dict[str, dict[str, Any]] = {}
    for i in out.get("issues", []):
        new.setdefault(i["key"], i)
    existing = {i.key: i for i in case.issues}
    ran = _ran_agents(out)
    for key, row in existing.items():
        if row.status == IssueStatus.OPEN and row.agent in ran and key not in new:
            row.status, row.resolution_note = IssueStatus.RESOLVED, AUTO_RESOLVED_NOTE
    for key, i in new.items():
        row = existing.get(key)
        if row is None:
            db.add(
                Issue(
                    request_id=case.id,
                    key=key,
                    agent=i["agent"],
                    type=i["type"],
                    severity=i["severity"],
                    field=i["field"],
                    message=i["message"],
                    details=i["details"],
                    case=case,
                )
            )
        elif row.status == IssueStatus.OPEN or row.resolved_by_id is None:
            row.status, row.resolution_note = IssueStatus.OPEN, None
            row.severity, row.message, row.details = i["severity"], i["message"], i["details"]


def _persist_risk(db: Session, case: Case, risk: dict[str, Any]) -> None:
    for old in case.risk_assessments:
        old.is_current = False
    for key, agent in (
        ("ops", RiskAgentName.OPS),
        ("financial", RiskAgentName.FINANCIAL),
        ("reconciled", RiskAgentName.RECONCILED),
    ):
        r = risk[key]
        db.add(
            RiskAssessment(
                request_id=case.id,
                agent=str(agent),
                urgency=r["urgency"],
                impact=r["impact"],
                risk_level=r["risk_level"],
                score=r["score"],
                rationale=r["rationale"],
                factors=r["factors"],
                confidence=r["confidence"],
                model=r["model"],
                details={k: r[k] for k in ("disagreement", "gap", "cost_exposure_inr") if k in r},
                case=case,
            )
        )


def _persist_recommendations(db: Session, case: Case, recs: list[dict[str, Any]]) -> None:
    for old in case.recommendations:
        if old.status == RecStatus.PROPOSED:
            old.status = RecStatus.SUPERSEDED
    for r in recs:
        plan = r.get("approval_plan", {})
        db.add(
            Recommendation(
                request_id=case.id,
                rank=r["rank"],
                kind=r["kind"],
                title=r["title"][:200],
                description=r["description"],
                rationale=r["rationale"],
                estimated_cost_inr=r["estimated_cost_inr"],
                estimated_lead_time_days=r["estimated_lead_time_days"],
                risk_reduction=r.get("risk_reduction", ""),
                confidence=r["confidence"],
                evidence=r["evidence"],
                allocations=r.get("allocations", []),
                requires_approval=r.get("requires_approval", True),
                approval_reasons=r.get("approval_reasons", []),
                approvers=plan.get("approvers", []),
                model=r["model"],
                case=case,
            )
        )


def _persist_drafts(db: Session, case: Case, drafts: list[dict[str, Any]]) -> None:
    for d in drafts:
        existing = next(
            (
                c
                for c in case.communications
                if c.type == d["type"]
                and c.status == CommStatus.DRAFT
                and c.created_by == "agent"
                and not c.edited
            ),
            None,
        )
        if existing:
            existing.subject, existing.body, existing.to, existing.model = (
                d["subject"],
                d["body"],
                d["to"],
                d["model"],
            )
        else:
            db.add(
                Communication(
                    request_id=case.id,
                    type=d["type"],
                    to=d["to"],
                    subject=d["subject"],
                    body=d["body"],
                    model=d["model"],
                    created_by="agent",
                    case=case,
                )
            )


def _update_case(case: Case, out: CaseState) -> None:
    facts = out.get("facts", {})
    reconciled = out.get("risk", {}).get("reconciled")
    if reconciled:
        new_priority = str(PRIORITY_BY_RISK[reconciled["risk_level"]])
        if new_priority != case.priority or case.sla_due_at is None:
            case.priority = new_priority
            case.sla_due_at = utcnow() + timedelta(hours=SLA_HOURS[Priority(new_priority)])
    if facts.get("deadline_at"):
        case.deadline_at = datetime.fromisoformat(facts["deadline_at"])
    if facts.get("region"):
        case.region = facts["region"]
    case.overall_confidence = out.get("confidence", 0.0)
    case.confidence_breakdown = out.get("confidence_breakdown", {})
    reasons = sorted(set(out.get("degraded_reasons", [])))
    case.degraded, case.degraded_reasons = bool(reasons), reasons
    case.agent_trace = out.get("trace", [])
    case.version += 1
