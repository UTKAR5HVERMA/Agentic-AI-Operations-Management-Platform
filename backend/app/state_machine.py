"""Case lifecycle (BACKEND.md §6). All status changes go through `transition`."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app import audit
from app.db import utcnow
from app.enums import ActorType, Status
from app.errors import conflict
from app.models import Case

TERMINAL: frozenset[Status] = frozenset({Status.CLOSED, Status.CANCELLED, Status.DUPLICATE})

ALLOWED: dict[Status, frozenset[Status]] = {
    Status.NEW: frozenset({Status.ANALYZING}),
    Status.ANALYZING: frozenset({Status.NEEDS_INFO, Status.PENDING_REVIEW, Status.DUPLICATE}),
    Status.NEEDS_INFO: frozenset({Status.ANALYZING, Status.DUPLICATE}),
    Status.PENDING_REVIEW: frozenset(
        {Status.PENDING_APPROVAL, Status.IN_PROGRESS, Status.ANALYZING, Status.DUPLICATE}
    ),
    Status.PENDING_APPROVAL: frozenset({Status.APPROVED, Status.REJECTED, Status.ESCALATED}),
    Status.ESCALATED: frozenset({Status.PENDING_APPROVAL, Status.APPROVED, Status.REJECTED}),
    Status.REJECTED: frozenset(
        {Status.PENDING_APPROVAL, Status.IN_PROGRESS, Status.PENDING_REVIEW, Status.ANALYZING}
    ),
    Status.APPROVED: frozenset({Status.IN_PROGRESS}),
    Status.IN_PROGRESS: frozenset({Status.RESOLVED}),
    Status.RESOLVED: frozenset({Status.CLOSED, Status.IN_PROGRESS}),
    Status.ON_HOLD: frozenset(),  # resolved dynamically: back to previous_status (or re-analysis)
    Status.CLOSED: frozenset(),
    Status.CANCELLED: frozenset(),
    # Only via an explicit human "not a duplicate" decision, which re-runs the analysis.
    Status.DUPLICATE: frozenset({Status.ANALYZING}),
}


def allowed_targets(case: Case) -> frozenset[Status]:
    current = Status(case.status)
    if current in TERMINAL:
        return ALLOWED[current]
    if current == Status.ON_HOLD:
        targets = {Status.ANALYZING, Status.CANCELLED}
        if case.previous_status:
            targets.add(Status(case.previous_status))
        return frozenset(targets)
    return ALLOWED[current] | {Status.ON_HOLD, Status.CANCELLED}


def can_transition(case: Case, to: Status) -> bool:
    return to in allowed_targets(case)


def transition(
    db: Session,
    case: Case,
    to: Status,
    *,
    actor: str,
    actor_type: ActorType = ActorType.HUMAN,
    reason: str | None = None,
) -> None:
    """Move a case to `to` or raise 409 ILLEGAL_TRANSITION. Always writes an audit row."""
    current = Status(case.status)
    if not can_transition(case, to):
        raise conflict("ILLEGAL_TRANSITION", f"Cannot move a case from {current} to {to}")
    if to == Status.ON_HOLD:
        case.previous_status = current
    elif current == Status.ON_HOLD:
        case.previous_status = None
    if to == Status.CLOSED:
        case.closed_at = utcnow()
    case.status = to
    case.version += 1
    audit.log_event(
        db,
        action="request.status_changed",
        actor=actor,
        actor_type=actor_type,
        request_id=case.id,
        before={"status": current},
        after={"status": to},
        reason=reason,
    )
