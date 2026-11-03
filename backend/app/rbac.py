"""RBAC: case visibility, case actions and approval authority (BACKEND.md §9)."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends
from sqlalchemy.orm import Session

from app import audit
from app.auth import get_current_user
from app.db import get_db
from app.enums import IN_FLIGHT_APPROVALS, ApprovalStatus, IssueStatus, Role, Status
from app.errors import ApiError, forbidden
from app.models import Approval, Case, User
from app.state_machine import TERMINAL, can_transition

# Segregation of duties: the central analyst works the case and routes it (selecting an option
# creates the approval); regional managers only decide. Whoever proposes never approves.
TRIAGE_ROLES = frozenset({Role.OPS_ANALYST, Role.ADMIN})
DECIDER_ROLES = frozenset({Role.OPS_MANAGER, Role.ADMIN})
STAFF_ROLES = TRIAGE_ROLES | DECIDER_ROLES
SPEND_CANCEL_ROLES = DECIDER_ROLES
ALL_REGION_ROLES = frozenset({Role.OPS_ANALYST, Role.ADMIN})  # the triage desk sees every region

ROLE_LABELS = {
    Role.OPS_MANAGER: "a Regional Manager",
    Role.ADMIN: "the Director",
    Role.OPS_ANALYST: "the Operations Team",
}

# Case action → roles allowed to perform it (status rules live in `allowed_actions`).
ACTION_ROLES: dict[str, frozenset[Role]] = {
    "correct_field": TRIAGE_ROLES,
    "flag_field": TRIAGE_ROLES,
    "resolve_issue": TRIAGE_ROLES,
    "request_info": TRIAGE_ROLES,
    "provide_info": TRIAGE_ROLES | {Role.REQUESTER},
    "reanalyze": TRIAGE_ROLES,
    "select_recommendation": TRIAGE_ROLES,
    "override": TRIAGE_ROLES,
    "mark_duplicate": TRIAGE_ROLES,
    "not_duplicate": TRIAGE_ROLES,
    "add_event": TRIAGE_ROLES,
    "generate_comm": TRIAGE_ROLES,
    "send_comm": TRIAGE_ROLES,
    "resolve": TRIAGE_ROLES,
    "close": TRIAGE_ROLES,
    "reopen": TRIAGE_ROLES,
    "hold": STAFF_ROLES,
    "resume": STAFF_ROLES,
    "cancel": STAFF_ROLES | {Role.REQUESTER},
}


def format_inr(amount: int) -> str:
    """Indian digit grouping, e.g. 560000 → ₹5,60,000."""
    digits = str(abs(amount))
    head, tail = digits[:-3], digits[-3:]
    groups: list[str] = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    body = ",".join([*groups, tail]) if groups else tail
    return f"₹{body}"


def deny(
    db: Session, user: User, detail: str, *, code: str = "FORBIDDEN", request_id: str | None = None
) -> ApiError:
    """Record `auth.denied` (committed even though the request fails) and return a 403."""
    audit.log_event(
        db,
        action="auth.denied",
        actor=user.email,
        request_id=request_id,
        after={"code": code, "role": user.role, "region": user.region},
        reason=detail,
    )
    db.commit()
    return forbidden(detail, code)


def require_role(*roles: Role) -> Callable[..., User]:
    allowed = frozenset(roles)

    def dependency(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        if Role(user.role) not in allowed and user.role != Role.ADMIN:
            raise deny(db, user, "Your role is not allowed to perform this action")
        return user

    return dependency


def raised_by(user: User, case: Case) -> bool:
    """Segregation of duties: is `user` the person asking for this action? That is the sender.
    The request desk, the Scenario Lab or a staff member may only *log* a request on someone's
    behalf; only when no sender is recorded does the creator count as the requester."""
    if case.sender_email:
        return case.sender_email.lower() == user.email.lower()
    return case.owner_id == user.id


def is_own_case(user: User, case: Case) -> bool:
    return case.owner_id == user.id or (
        case.sender_email is not None and case.sender_email.lower() == user.email.lower()
    )


def sees_all_regions(user: User) -> bool:
    return Role(user.role) in ALL_REGION_ROLES


def is_routed(case: Case) -> bool:
    """The Operations Team has forwarded the case for a decision (an approval exists)."""
    return bool(case.approvals)


def can_view_case(user: User, case: Case) -> bool:
    if sees_all_regions(user) or is_own_case(user, case):
        return True
    # Regional managers only see what the Operations Team has routed to them, never raw intake.
    if user.role != Role.OPS_MANAGER:
        return False
    assigned = any(a.assigned_to_id == user.id for a in case.approvals)
    return assigned or (case.region == user.region and is_routed(case))


def ensure_can_view(db: Session, user: User, case: Case) -> None:
    if not can_view_case(user, case):
        detail = (
            f"{case.ref} has not been routed to you yet — the Operations Team reviews it first"
            if user.role == Role.OPS_MANAGER and case.region == user.region
            else f"You don't have access to {case.ref} (region {case.region})"
        )
        raise deny(db, user, detail, code="CASE_ACCESS_DENIED", request_id=case.id)


def has_approved_spend(case: Case) -> bool:
    return any(a.status == ApprovalStatus.APPROVED and a.amount_inr > 0 for a in case.approvals)


def ensure_action(db: Session, user: User, case: Case, action: str) -> None:
    """Role check for a case action; also enforces visibility. Raises 403 + audit on failure."""
    ensure_can_view(db, user, case)
    role = Role(user.role)
    if role not in ACTION_ROLES[action]:
        raise deny(
            db, user, f"Your role ({role}) cannot {action.replace('_', ' ')}", request_id=case.id
        )
    if role == Role.REQUESTER and not is_own_case(user, case):
        raise deny(db, user, "Requesters can only act on their own requests", request_id=case.id)
    if action == "cancel" and has_approved_spend(case) and role not in SPEND_CANCEL_ROLES:
        raise deny(
            db,
            user,
            "This case has approved spend; only an Ops Manager or admin can cancel it",
            code="CANCEL_NEEDS_MANAGER",
            request_id=case.id,
        )


def approval_denial(
    user: User, approval: Approval, case: Case, *, check_limit: bool = True
) -> tuple[str, str] | None:
    """Return (code, message) if `user` may not decide `approval`, else None.

    `check_limit=False` for reject/escalate: saying "no" or passing it up needs no spend authority.
    """
    role = Role(user.role)
    if role == Role.ADMIN:
        if raised_by(user, case):
            return (
                "SELF_APPROVAL_OVERRIDE_REQUIRED",
                "You raised this request. As Director you can still approve it, but only with a "
                "written justification (self-approval override); it is flagged for review.",
            )
        return None
    if role not in DECIDER_ROLES:
        return (
            "NOT_AN_APPROVER",
            "The Operations Team prepares and routes cases; the regional Ops Manager or the "
            "Director decides approvals.",
        )
    # Operational sign-offs (₹0 options that still need a human) carry no spend, so the approval
    # limit applies only to approvals with financial authority (kind == financial).
    if approval.assigned_to_id and approval.assigned_to_id != user.id:
        name = approval.assigned_to.name if approval.assigned_to else "another manager"
        return ("NOT_ASSIGNED_APPROVER", f"This approval is assigned to {name}.")
    if role != approval.approver_role:
        needed = ROLE_LABELS.get(Role(approval.approver_role), approval.approver_role)
        return ("APPROVAL_ROLE_MISMATCH", f"This approval is assigned to {needed}.")
    if (
        check_limit
        and approval.kind == "financial"
        and approval.amount_inr > user.approval_limit_inr
    ):
        return (
            "APPROVAL_LIMIT_EXCEEDED",
            f"You can approve up to {format_inr(user.approval_limit_inr)}. Forward it to the "
            "Director.",
        )
    if raised_by(user, case):
        return ("SELF_APPROVAL", _self_msg())
    return None


MIN_JUSTIFICATION = 15


def needs_self_override(user: User, approval: Approval, case: Case) -> bool:
    """Top of the chain: nobody is above the Director, so their own request needs an override."""
    return (
        user.role == Role.ADMIN and approval.status in IN_FLIGHT_APPROVALS and raised_by(user, case)
    )


def _self_msg() -> str:
    return "You raised this request, so you cannot approve it (segregation of duties)."


def can_decide(user: User, approval: Approval, case: Case) -> bool:
    return approval.status in IN_FLIGHT_APPROVALS and approval_denial(user, approval, case) is None


def allowed_actions(user: User, case: Case) -> list[str]:
    """Actions the UI should render for this user on this case (role × status)."""
    status = Status(case.status)
    candidates = _status_actions(case, status)
    actions = [a for a in candidates if _role_allows(user, case, a)]
    if any(can_decide(user, a, case) for a in case.approvals):
        actions += ["approve", "reject", "escalate"]
    return actions


def _role_allows(user: User, case: Case, action: str) -> bool:
    role = Role(user.role)
    if role not in ACTION_ROLES[action]:
        return False
    if role == Role.REQUESTER and not is_own_case(user, case):
        return False
    return not (action == "cancel" and has_approved_spend(case) and role not in SPEND_CANCEL_ROLES)


def _status_actions(case: Case, status: Status) -> list[str]:
    if status == Status.DUPLICATE:
        return ["not_duplicate"]
    if status in TERMINAL or status in {Status.NEW, Status.ANALYZING}:
        return []
    actions: list[str] = []
    if status not in {Status.RESOLVED, Status.ON_HOLD}:
        actions += ["flag_field", "correct_field"]
    if any(i.status == IssueStatus.OPEN for i in case.issues):
        actions.append("resolve_issue")
    if status in {Status.NEEDS_INFO, Status.PENDING_REVIEW}:
        actions += ["request_info", "provide_info"]
    if status in {Status.NEEDS_INFO, Status.PENDING_REVIEW, Status.REJECTED, Status.ON_HOLD}:
        actions.append("reanalyze")
    if status in {Status.PENDING_REVIEW, Status.REJECTED}:
        actions += ["select_recommendation", "override"]
    if status in {Status.NEEDS_INFO, Status.PENDING_REVIEW} and case.duplicate_candidates:
        actions += ["mark_duplicate", "not_duplicate"]
    actions += _lifecycle_actions(case, status)
    return actions


def _lifecycle_actions(case: Case, status: Status) -> list[str]:
    actions = ["add_event", "generate_comm", "send_comm"]
    if status == Status.IN_PROGRESS:
        actions.append("resolve")
    if status == Status.RESOLVED:
        actions += ["close", "reopen"]
    if status == Status.ON_HOLD:
        actions.append("resume")
    elif can_transition(case, Status.ON_HOLD):
        actions.append("hold")
    actions.append("cancel")
    return actions
