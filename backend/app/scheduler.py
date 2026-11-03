"""Background loop (BACKEND.md §13): approval reminders/escalation, comm retries, degraded-case
recovery and SLA breaches. `tick()` is also exposed via POST /api/simulate/scheduler-tick.

TRADE-OFF: an in-process asyncio loop (not distributed). Celery/Temporal is on the roadmap.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.config import get_settings
from app.db import SessionLocal, get_engine, utcnow
from app.enums import (
    IN_FLIGHT_APPROVALS,
    ActorType,
    CommType,
    Flag,
    IssueStatus,
    IssueType,
    Priority,
    Role,
    Severity,
    Status,
)
from app.faults import get_flags
from app.llm.client import OUTAGE_FLAG_ERROR
from app.models import Approval, Case, Issue
from app.services import approvals, communications
from app.services.analysis import run_analysis
from app.state_machine import TERMINAL

log = logging.getLogger(__name__)
RECOVERABLE = {Status.PENDING_REVIEW, Status.NEEDS_INFO, Status.ON_HOLD}
ACTOR = "scheduler"
RECOVERY_COOLDOWN = timedelta(minutes=10)
STUCK_NEW_AFTER = timedelta(minutes=2)


def _approval_checks(db: Session, now: datetime, counts: dict[str, int]) -> None:
    in_flight = db.scalars(
        select(Approval).where(Approval.status.in_([str(s) for s in IN_FLIGHT_APPROVALS]))
    )
    for a in list(in_flight):
        case = a.case
        if (
            case.deadline_at
            and case.deadline_at <= now
            and a.created_at < case.deadline_at
            and not a.deadline_alerted
        ):
            _deadline_missed(db, a, case)
            counts["deadline_alerts"] += 1
        if a.due_at <= now:
            if a.approver_role != Role.ADMIN:
                approvals.escalate(
                    db,
                    a,
                    actor=ACTOR,
                    actor_type=ActorType.SYSTEM,
                    note="No decision before the due time (auto-escalation)",
                )
                counts["escalations"] += 1
            continue
        halfway = a.created_at + (a.due_at - a.created_at) / 2
        if not a.reminder_sent and now >= halfway:
            a.reminder_sent = True
            communications.notify(
                db,
                case,
                CommType.REMINDER,
                communications.recipients(db, a.approver_role, case.region),
                recommendation=a.recommendation.title,
                amount_inr=a.amount_inr,
                due_at=a.due_at,
            )
            audit.log_event(
                db,
                action="approval.reminder_sent",
                actor=ACTOR,
                actor_type=ActorType.SYSTEM,
                request_id=case.id,
                after={"approval_id": a.id, "due_at": a.due_at},
            )
            counts["reminders"] += 1


def _deadline_missed(db: Session, a: Approval, case: Case) -> None:
    """Business deadline passed with no decision: alert management, never auto-approve."""
    a.deadline_alerted = True
    db.add(
        Issue(
            request_id=case.id,
            key=f"scheduler:deadline_missed:{a.id}",
            agent=ACTOR,
            type=str(IssueType.DEADLINE_MISSED),
            severity=str(Severity.BLOCKER),
            status=str(IssueStatus.OPEN),
            message="The business deadline passed without an approval decision. "
            "Management has been alerted; nothing was auto-approved.",
            details={"approval_id": a.id, "deadline_at": case.deadline_at.isoformat()},
            case=case,
        )
    )
    communications.notify(
        db,
        case,
        CommType.ESCALATION,
        communications.recipients(db, Role.ADMIN, case.region),
        recommendation=a.recommendation.title,
        amount_inr=a.amount_inr,
        previous_due=case.deadline_at,
        level=a.escalation_level,
        due_at=a.due_at,
    )
    audit.log_event(
        db,
        action="approval.deadline_missed",
        actor=ACTOR,
        actor_type=ActorType.SYSTEM,
        request_id=case.id,
        after={"approval_id": a.id, "deadline_at": case.deadline_at},
    )


def _provider_failed(case: Case) -> bool:
    """True when the last run degraded on real provider errors (429/5xx), not a fault flag."""
    return any(t.get("error") and t["error"] != OUTAGE_FLAG_ERROR for t in case.agent_trace)


def _analyse_stuck_new(db: Session, now: datetime, counts: dict[str, int]) -> None:
    """Safety net for submissions whose background analysis never ran (e.g. process restart)."""
    stuck = select(Case).where(Case.status == Status.NEW, Case.created_at <= now - STUCK_NEW_AFTER)
    for case in db.scalars(stuck):
        run_analysis(
            db, case, actor=ACTOR, actor_type=ActorType.SYSTEM, reason="Picked up by scheduler"
        )
        counts["reanalyzed"] += 1


def _recover_degraded(db: Session, now: datetime, counts: dict[str, int]) -> None:
    flags = get_flags(db)
    down = {"llm": flags[str(Flag.LLM_DOWN)], "inventory": flags[str(Flag.INVENTORY_DOWN)]}
    for case in db.scalars(select(Case).where(Case.degraded.is_(True))):
        if case.status not in RECOVERABLE or any(
            a.status in IN_FLIGHT_APPROVALS for a in case.approvals
        ):
            continue
        if any(down.get(reason, False) for reason in case.degraded_reasons):
            continue
        # Back off after real provider failures so retries don't burn the rate-limit quota.
        if _provider_failed(case) and case.updated_at > now - RECOVERY_COOLDOWN:
            continue
        run_analysis(
            db,
            case,
            actor=ACTOR,
            actor_type=ActorType.SYSTEM,
            reason=f"Systems recovered ({', '.join(case.degraded_reasons)})",
        )
        counts["reanalyzed"] += 1


def _sla(db: Session, now: datetime, counts: dict[str, int]) -> None:
    order = [Priority.P4, Priority.P3, Priority.P2, Priority.P1]
    for case in db.scalars(
        select(Case).where(Case.sla_breached.is_(False), Case.sla_due_at <= now)
    ):
        if Status(case.status) in TERMINAL:
            continue
        before = case.priority
        case.sla_breached = True
        current = Priority(before)
        if current != Priority.P1:
            case.priority = str(order[order.index(current) + 1])
        audit.log_event(
            db,
            action="request.sla_breached",
            actor=ACTOR,
            actor_type=ActorType.SYSTEM,
            request_id=case.id,
            before={"priority": before},
            after={"priority": case.priority},
        )
        counts["sla_breaches"] += 1


def tick(db: Session, now: datetime | None = None) -> dict[str, int]:
    now = now or utcnow()
    counts = dict.fromkeys(
        ("reminders", "escalations", "deadline_alerts", "retries", "reanalyzed", "sla_breaches"), 0
    )
    _approval_checks(db, now, counts)
    counts["retries"] = communications.retry_due(db)
    _analyse_stuck_new(db, now, counts)
    _recover_degraded(db, now, counts)
    _sla(db, now, counts)
    db.commit()
    return counts


def _tick_in_new_session() -> dict[str, int]:
    get_engine()
    with SessionLocal() as db:
        return tick(db)


async def run_forever() -> None:
    interval = get_settings().scheduler_interval_seconds
    while True:
        await asyncio.sleep(interval)
        try:
            counts = await asyncio.to_thread(_tick_in_new_session)
            if any(counts.values()):
                log.info("scheduler.tick", extra={"counts": counts})
        except Exception:  # keep the loop alive; the next tick retries
            log.exception("scheduler.tick_failed")
