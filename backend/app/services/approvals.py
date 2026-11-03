"""Selecting a recommendation, creating approvals per policy, and approval decisions.

Approval authority is enforced server-side (rbac.approval_denial): role, approval limit, region
and segregation of duties. Every decision and every denial is audited.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import audit, rbac
from app.agents.approval_router import ApprovalStep, PolicyContext, next_escalation_role, plan
from app.config import get_settings
from app.db import utcnow
from app.enums import (
    IN_FLIGHT_APPROVALS,
    ActorType,
    ApprovalStatus,
    CommType,
    IssueStatus,
    IssueType,
    Priority,
    RecStatus,
    Role,
    Status,
)
from app.errors import ApiError, bad_request, conflict, not_found
from app.models import Approval, Case, Recommendation, User
from app.services import approval_advice, communications, inventory
from app.services.analysis import run_analysis
from app.state_machine import transition

SELECTABLE = {Status.PENDING_REVIEW, Status.REJECTED}
MIN_LEAD = timedelta(minutes=30)


def policy_for(case: Case) -> PolicyContext:
    reconciled = next(
        (r for r in case.risk_assessments if r.is_current and r.agent == "reconciled"), None
    )
    disagreement = any(
        i.type == IssueType.AGENT_DISAGREEMENT and i.status == IssueStatus.OPEN for i in case.issues
    )
    return PolicyContext(
        risk_level=reconciled.risk_level if reconciled else None,
        confidence=case.overall_confidence,
        disagreement=disagreement,
        injection=case.injection_flag,
        auto_threshold=get_settings().confidence_auto_threshold,
    )


def due_at_for(case: Case, now: datetime) -> datetime:
    """min(deadline − 30 min, now + default timeout); never already in the past."""
    timeout = now + timedelta(minutes=get_settings().approval_default_timeout_minutes)
    if case.deadline_at is None:
        return timeout
    candidate = case.deadline_at - MIN_LEAD
    if candidate > now:
        return min(candidate, timeout)
    # TRADE-OFF: deadline already (nearly) passed — give approvers the default window.
    return min(case.deadline_at, timeout) if case.deadline_at > now else timeout


def list_approvers(db: Session) -> list[User]:
    """Regional Managers the Operations Team can route an approval to."""
    return list(db.scalars(select(User).where(User.role == Role.OPS_MANAGER).order_by(User.region)))


def resolve_approver(db: Session, case: Case, approver_id: str | None) -> User | None:
    """The manager chosen by the Operations Team, or by default the manager for the case region."""
    if approver_id:
        chosen = db.get(User, approver_id)
        if chosen is None or chosen.role != Role.OPS_MANAGER:
            raise bad_request("INVALID_APPROVER", "Choose one of the Regional Managers")
        return chosen
    return next((m for m in list_approvers(db) if m.region == case.region), None)


def select_recommendation(
    db: Session,
    case: Case,
    rec: Recommendation,
    user: User,
    note: str | None,
    approver_id: str | None = None,
) -> None:
    if case.status not in SELECTABLE:
        raise conflict("ILLEGAL_TRANSITION", f"Cannot select a recommendation in {case.status}")
    if rec.status != RecStatus.PROPOSED:
        raise conflict("RECOMMENDATION_NOT_PROPOSED", f"Recommendation is {rec.status}")
    flagged = [
        i.field
        for i in case.issues
        if i.type == IssueType.EXTRACTION_FLAGGED and i.status == IssueStatus.OPEN
    ]
    if flagged:  # never route a decision built on a value a human said is wrong
        names = ", ".join(f.replace("_", " ") for f in flagged)
        raise conflict("FIELD_FLAGGED", f"Correct the flagged field(s) first: {names}.")
    rec.status = RecStatus.SELECTED
    top = next(
        (
            r
            for r in case.recommendations
            if r.status in {RecStatus.PROPOSED, RecStatus.SELECTED, RecStatus.OVERRIDDEN}
            and r.created_by == "agent"
            and r.rank == 1
        ),
        None,
    )
    audit.log_event(
        db,
        action="recommendation.selected",
        actor=user.email,
        request_id=case.id,
        before={"ai_top": top.title if top else None},
        after={
            "id": rec.id,
            "title": rec.title,
            "rank": rec.rank,
            "created_by": rec.created_by,
            "followed_ai": top is not None and top.id == rec.id,
        },
        reason=note,
    )
    approval_plan = plan(rec.estimated_cost_inr, policy_for(case))
    if not approval_plan.required:
        transition(
            db,
            case,
            Status.IN_PROGRESS,
            actor=user.email,
            reason="No approval required (₹0, low risk, high confidence)",
        )
        _start_work(db, case, rec, user.email)
        return
    assignee = resolve_approver(db, case, approver_id)
    _request_step(
        db, case, rec, approval_plan.steps[0], approval_plan.reasons, note=note, assignee=assignee
    )
    transition(
        db,
        case,
        Status.PENDING_APPROVAL,
        actor=user.email,
        reason=f"Routed by the Operations Team: {'; '.join(approval_plan.reasons)}",
    )


def _request_step(
    db: Session,
    case: Case,
    rec: Recommendation,
    step: ApprovalStep,
    reasons: list[str],
    *,
    note: str | None,
    assignee: User | None,
) -> Approval:
    approval = Approval(
        request_id=case.id,
        recommendation_id=rec.id,
        approver_role=str(step.role),
        kind=step.kind,
        amount_inr=rec.estimated_cost_inr,
        due_at=due_at_for(case, utcnow()),
        reasons=reasons,
        routing_note=note,
        assigned_to_id=assignee.id if assignee else None,
        case=case,
        recommendation=rec,
    )
    db.add(approval)
    db.flush()
    db.refresh(approval, ["assigned_to"])
    audit.log_event(
        db,
        action="approval.requested",
        actor="approval_router",
        actor_type=ActorType.SYSTEM,
        request_id=case.id,
        after={
            "approval_id": approval.id,
            "role": approval.approver_role,
            "kind": approval.kind,
            "amount_inr": approval.amount_inr,
            "due_at": approval.due_at,
            "routing_note": note,
            "assigned_to": assignee.email if assignee else None,
        },
        reason="; ".join(reasons),
    )
    advice = approval_advice.refresh(db, approval, reason="Approval requested")
    communications.notify(
        db,
        case,
        CommType.APPROVAL_REQUEST,
        [assignee.email] if assignee else communications.recipients(db, step.role, case.region),
        recommendation=rec.title,
        amount_inr=rec.estimated_cost_inr,
        reasons=reasons,
        due_at=approval.due_at,
        routing_note=note,
        ai_suggestion=approval_advice.summary_line(advice),
        **communications.original_request(case),
    )
    return approval


def _start_work(db: Session, case: Case, rec: Recommendation, actor: str) -> None:
    inventory.adjust_reservations(
        db, rec.allocations, release=False, actor=actor, request_id=case.id
    )


def get_approval(db: Session, approval_id: str) -> Approval:
    approval = db.get(Approval, approval_id)
    if approval is None:
        raise not_found("Approval")
    return approval


def _check_authority(
    db: Session, user: User, approval: Approval, case: Case, *, check_limit: bool
) -> None:
    if approval.status not in IN_FLIGHT_APPROVALS:
        raise conflict("APPROVAL_NOT_PENDING", f"Approval is already {approval.status}")
    denial = rbac.approval_denial(user, approval, case, check_limit=check_limit)
    if denial:
        code, message = denial
        raise rbac.deny(db, user, message, code=code, request_id=case.id)


def approve(
    db: Session,
    approval: Approval,
    user: User,
    note: str | None,
    reconfirm: bool,
    self_override: bool = False,
) -> None:
    case = approval.case
    if self_override and rbac.needs_self_override(user, approval, case):
        _self_override(db, approval, user, note)
    else:
        _check_authority(db, user, approval, case, check_limit=True)
    if approval.stale and not reconfirm:
        raise ApiError(
            409,
            "STALE_APPROVAL",
            f"Circumstances changed ({approval.stale_reason}). Review the updated "
            f"case and re-confirm to approve.",
        )
    approval.status, approval.approver_id = ApprovalStatus.APPROVED, user.id
    approval.decided_at, approval.decision_note = utcnow(), note
    audit.log_event(
        db,
        action="approval.approved",
        actor=user.email,
        request_id=case.id,
        after={
            "approval_id": approval.id,
            "amount_inr": approval.amount_inr,
            "reconfirmed_stale": approval.stale,
        },
        reason=note,
    )
    siblings = [a for a in case.approvals if a.recommendation_id == approval.recommendation_id]
    if all(a.status == ApprovalStatus.APPROVED for a in siblings):
        transition(db, case, Status.APPROVED, actor=user.email, reason="All approvals granted")
        transition(
            db,
            case,
            Status.IN_PROGRESS,
            actor="orchestrator",
            actor_type=ActorType.SYSTEM,
            reason="Approved action started",
        )
        _start_work(db, case, approval.recommendation, user.email)
    elif case.status == Status.ESCALATED and not any(
        a.status == ApprovalStatus.ESCALATED for a in siblings
    ):
        transition(
            db,
            case,
            Status.PENDING_APPROVAL,
            actor=user.email,
            reason="Escalated approval decided; others still pending",
        )


def _self_override(db: Session, approval: Approval, user: User, note: str | None) -> None:
    """The Director approves their own request: allowed only with a written justification,
    marked on the approval and recorded separately so it is reviewed (management summary)."""
    if len((note or "").strip()) < rbac.MIN_JUSTIFICATION:
        raise ApiError(
            400,
            "JUSTIFICATION_REQUIRED",
            f"Explain why you are approving your own request "
            f"(at least {rbac.MIN_JUSTIFICATION} characters).",
        )
    approval.self_approved = True
    audit.log_event(
        db,
        action="approval.self_override",
        actor=user.email,
        request_id=approval.request_id,
        after={"approval_id": approval.id, "amount_inr": approval.amount_inr},
        reason=note,
    )


def reject(db: Session, approval: Approval, user: User, note: str) -> None:
    case = approval.case
    _check_authority(db, user, approval, case, check_limit=False)
    approval.status, approval.approver_id = ApprovalStatus.REJECTED, user.id
    approval.decided_at, approval.decision_note = utcnow(), note
    rec = approval.recommendation
    rec.status = RecStatus.REJECTED
    for sibling in case.approvals:
        if sibling.id != approval.id and sibling.status in IN_FLIGHT_APPROVALS:
            sibling.status, sibling.decision_note = ApprovalStatus.CANCELLED, "Sibling rejected"
    audit.log_event(
        db,
        action="approval.rejected",
        actor=user.email,
        request_id=case.id,
        after={
            "approval_id": approval.id,
            "recommendation": rec.title,
            "amount_inr": approval.amount_inr,
        },
        reason=note,
    )
    transition(db, case, Status.REJECTED, actor=user.email, reason=note)
    run_analysis(
        db,
        case,
        actor="orchestrator",
        actor_type=ActorType.SYSTEM,
        start_at="validation",
        reason=f"Re-propose after rejection of '{rec.title}'",
        preserve_status=True,
    )
    alternatives = [r.title for r in case.recommendations if r.status == RecStatus.PROPOSED]
    audit.log_event(
        db,
        action="recommendation.reproposed",
        actor="recommendation",
        actor_type=ActorType.AGENT,
        request_id=case.id,
        after={"excluded": rec.kind, "alternatives": alternatives},
    )


def escalate(
    db: Session,
    approval: Approval,
    *,
    actor: str,
    actor_type: ActorType,
    note: str | None,
    user: User | None = None,
) -> None:
    case = approval.case
    if user is not None:
        _check_authority(db, user, approval, case, check_limit=False)
    elif approval.status not in IN_FLIGHT_APPROVALS:
        return
    target = next_escalation_role(approval.approver_role)
    if target is None:
        raise conflict("NO_ESCALATION_TARGET", "Already at the highest approval level")
    before = {
        "role": approval.approver_role,
        "level": approval.escalation_level,
        "due_at": approval.due_at,
    }
    previous_due = approval.due_at
    approval.approver_role, approval.status = str(target), ApprovalStatus.ESCALATED
    approval.assigned_to_id = None  # any Director may decide
    approval.escalation_level += 1
    approval.due_at = utcnow() + timedelta(minutes=get_settings().approval_default_timeout_minutes)
    approval.reminder_sent = False
    if target == Role.ADMIN:
        approval.kind = "financial"
    forwarded = user is not None  # a manager's decision, not a missed deadline
    audit.log_event(
        db,
        action="approval.forwarded" if forwarded else "approval.escalated",
        actor=actor,
        actor_type=actor_type,
        request_id=case.id,
        before=before,
        after={
            "role": approval.approver_role,
            "level": approval.escalation_level,
            "due_at": approval.due_at,
        },
        reason=note,
    )
    if not forwarded:
        _bump_priority(db, case, actor, actor_type)
    db.flush()
    db.refresh(approval, ["assigned_to"])
    advice = approval_advice.refresh(db, approval, reason=f"Moved up to the {target} ({note})")
    communications.notify(
        db,
        case,
        CommType.ESCALATION,
        communications.recipients(db, target, case.region),
        recommendation=approval.recommendation.title,
        amount_inr=approval.amount_inr,
        previous_due=previous_due,
        level=approval.escalation_level,
        due_at=approval.due_at,
        escalation_reason=note,
        forwarded_by_manager=forwarded,
        ai_suggestion=approval_advice.summary_line(advice),
    )
    if case.status == Status.PENDING_APPROVAL:
        transition(
            db,
            case,
            Status.ESCALATED,
            actor=actor,
            actor_type=actor_type,
            reason=note or f"Escalated to {target}",
        )


def _bump_priority(db: Session, case: Case, actor: str, actor_type: ActorType) -> None:
    order = [Priority.P4, Priority.P3, Priority.P2, Priority.P1]
    current = Priority(case.priority)
    if current == Priority.P1:
        return
    case.priority = str(order[order.index(current) + 1])
    audit.log_event(
        db,
        action="request.priority_bumped",
        actor=actor,
        actor_type=actor_type,
        request_id=case.id,
        before={"priority": current},
        after={"priority": case.priority},
    )


def list_for_user(db: Session, user: User, status: str | None, mine: bool) -> list[Approval]:
    query = select(Approval).order_by(Approval.due_at)
    if status == "decided":
        query = query.where(Approval.status.in_([ApprovalStatus.APPROVED, ApprovalStatus.REJECTED]))
    elif status == "pending":
        query = query.where(Approval.status.in_([str(s) for s in IN_FLIGHT_APPROVALS]))
    elif status:
        query = query.where(Approval.status == status)
    if mine and user.role != Role.ADMIN:
        query = query.where(
            or_(
                Approval.assigned_to_id == user.id,
                Approval.approver_id == user.id,
                (Approval.approver_role == user.role) & Approval.assigned_to_id.is_(None),
            )
        )
    return [a for a in db.scalars(query) if rbac.can_view_case(user, a.case)]
