"""Dashboard metrics (SQL) and the management summary (LLM narrative over those numbers)."""

from __future__ import annotations

from collections import Counter as Tally
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.agents import reporting
from app.config import get_settings
from app.db import utcnow
from app.enums import (
    IN_FLIGHT_APPROVALS,
    ActorType,
    CommStatus,
    CommType,
    FieldSource,
    RecStatus,
    RiskAgentName,
    Status,
)
from app.faults import get_flags
from app.llm.client import LLMClient
from app.models import Approval, AuditLog, Case, Communication, ExtractedField, Recommendation, User
from app.state_machine import TERMINAL

AI_SOURCES = [str(FieldSource.LLM), str(FieldSource.FALLBACK)]


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _field_metrics(db: Session) -> tuple[float, dict[str, float]]:
    rows = db.execute(
        select(ExtractedField.field, ExtractedField.source, ExtractedField.request_id)
    )
    ai: Tally[str] = Tally()
    corrected: Tally[str] = Tally()
    seen_corrections: set[tuple[str, str]] = set()
    for field, source, request_id in rows:
        if source in AI_SOURCES:
            ai[field] += 1
        elif source == FieldSource.HUMAN and (request_id, field) not in seen_corrections:
            seen_corrections.add((request_id, field))
            corrected[field] += 1
    total_ai = sum(ai.values())
    accuracy = 1 - _ratio(sum(corrected.values()), total_ai) if total_ai else 1.0
    return round(accuracy, 4), {f: _ratio(corrected[f], ai[f]) for f in ai}


def _agent_metrics(db: Session) -> tuple[float, float]:
    rows = db.execute(
        select(AuditLog.model, AuditLog.latency_ms).where(
            AuditLog.actor_type == ActorType.AGENT,
            AuditLog.model.is_not(None),
            AuditLog.model != "deterministic",
        )
    )
    models, latencies = [], []
    for model, latency in rows:
        models.append(model)
        if latency is not None:
            latencies.append(latency)
    fallback_rate = _ratio(sum(m == "fallback" for m in models), len(models))
    avg_latency = round(sum(latencies) / len(latencies), 1) if latencies else 0.0
    return fallback_rate, avg_latency


def dashboard(db: Session) -> dict[str, Any]:
    now = utcnow()
    cases = list(db.scalars(select(Case)))
    open_cases = [c for c in cases if Status(c.status) not in TERMINAL]
    closed = [c for c in cases if c.closed_at]
    selected = list(
        db.scalars(select(Recommendation).where(Recommendation.status == RecStatus.SELECTED))
    )
    overridden = [r for r in selected if r.created_by == "human" or r.rank != 1]
    in_flight = list(
        db.scalars(
            select(Approval).where(Approval.status.in_([str(s) for s in IN_FLIGHT_APPROVALS]))
        )
    )
    accuracy, correction_rates = _field_metrics(db)
    fallback_rate, avg_latency = _agent_metrics(db)
    return {
        "total_cases": len(cases),
        "open_cases": len(open_cases),
        "counts_by_status": dict(Tally(c.status for c in cases)),
        "by_priority": dict(Tally(c.priority for c in open_cases)),
        "by_category": dict(Tally(c.category for c in cases)),
        "overdue": sum(1 for c in open_cases if c.sla_due_at and c.sla_due_at < now),
        "pending_approvals": len(in_flight),
        "avg_time_to_close_hours": round(
            sum((c.closed_at - c.created_at).total_seconds() for c in closed) / 3600 / len(closed),
            2,
        )
        if closed
        else 0.0,
        "ai_override_rate": _ratio(len(overridden), len(selected)),
        "auto_extraction_accuracy": accuracy,
        "field_correction_rate": correction_rates,
        "degraded_cases": sum(1 for c in open_cases if c.degraded),
        "fallback_rate": fallback_rate,
        "avg_agent_latency_ms": avg_latency,
        "approval_sla_breaches": db.scalar(
            select(func.count()).select_from(Approval).where(Approval.escalation_level > 0)
        )
        or 0,
        "self_approvals": [
            {"ref": a.case.ref, "amount_inr": a.amount_inr, "justification": a.decision_note}
            for a in db.scalars(select(Approval).where(Approval.self_approved.is_(True)))
        ],
        "critical_cases": _critical(open_cases),
        "pending_approval_items": [
            {
                "ref": a.case.ref,
                "title": a.recommendation.title,
                "amount_inr": a.amount_inr,
                "approver_role": a.approver_role,
                "due_at": a.due_at.isoformat(),
                "escalation_level": a.escalation_level,
            }
            for a in in_flight
        ],
    }


def _critical(open_cases: list[Case]) -> list[dict[str, Any]]:
    items = []
    for c in open_cases:
        risk = next(
            (
                r.risk_level
                for r in c.risk_assessments
                if r.is_current and r.agent == RiskAgentName.RECONCILED
            ),
            None,
        )
        if risk in {"high", "critical"} or c.status == Status.ESCALATED:
            items.append(
                {
                    "id": c.id,
                    "ref": c.ref,
                    "subject": c.subject,
                    "status": c.status,
                    "priority": c.priority,
                    "risk_level": risk,
                }
            )
    return sorted(items, key=lambda i: i["priority"])[:10]


def management_summary(db: Session, user: User) -> tuple[str, dict[str, Any], str, str]:
    metrics = dashboard(db)
    llm = LLMClient(get_settings(), llm_down=get_flags(db)["llm_down"])
    markdown, result = reporting.summarize(metrics, llm)
    model = result.model if result.data else "template"
    comm = Communication(
        type=str(CommType.MANAGEMENT_SUMMARY),
        to=[],
        status=CommStatus.DRAFT,
        subject=f"Operations summary {utcnow().date().isoformat()}",
        body=markdown,
        model=model,
        created_by="agent",
    )
    db.add(comm)
    db.flush()
    audit.log_event(
        db,
        action="report.management_summary",
        actor="reporting",
        actor_type=ActorType.AGENT,
        after={"communication_id": comm.id, "open_cases": metrics["open_cases"]},
        reason=f"Requested by {user.email}",
        meta=audit.AgentMeta(
            model=model,
            prompt_hash=result.prompt_hash,
            latency_ms=result.latency_ms,
            tokens=result.tokens,
        ),
    )
    return markdown, metrics, model, comm.id
