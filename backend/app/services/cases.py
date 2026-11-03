"""Case use-cases: create, correct, resolve, override, duplicate, transition, cancel."""

from __future__ import annotations

from datetime import UTC

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app import audit, rbac
from app.agents import composer
from app.agents.communication import draft as draft_comm
from app.config import get_settings
from app.db import utcnow
from app.enums import (
    IN_FLIGHT_APPROVALS,
    ActorType,
    ApprovalStatus,
    CommType,
    FieldSource,
    Flag,
    IssueStatus,
    IssueType,
    RecStatus,
    Role,
    Severity,
    Status,
)
from app.errors import bad_request, conflict, not_found
from app.faults import get_flags
from app.llm.client import LLMClient
from app.models import Case, Counter, ExtractedField, Issue, Recommendation, User
from app.normalize import IST, normalize_field
from app.schemas import CreateRequest, OverrideRecommendation
from app.services import approvals as approval_service
from app.services import communications, inventory
from app.services.analysis import current_fields, run_analysis
from app.state_machine import TERMINAL, transition

# Statuses reachable through the generic /transition endpoint (others have dedicated flows).
MANUAL_TARGETS = {Status.RESOLVED, Status.CLOSED, Status.IN_PROGRESS, Status.ON_HOLD}
REANALYZABLE = {Status.NEEDS_INFO, Status.PENDING_REVIEW, Status.REJECTED, Status.ON_HOLD}


def next_ref(db: Session, year: int) -> str:
    key = f"ref-{year}"
    counter = db.get(Counter, key, with_for_update=True) or Counter(key=key, value=0)
    counter.value += 1
    db.add(counter)
    db.flush()
    return f"OPS-{year}-{counter.value:04d}"


def get_case(db: Session, case_id: str) -> Case:
    case = db.get(Case, case_id)
    if case is None:
        raise not_found("Request")
    return case


def check_version(case: Case, version: int | None) -> None:
    if version is not None and version != case.version:
        raise conflict(
            "STALE_VERSION", "This case was updated by someone else — reload and try again."
        )


def create_case(
    db: Session, data: CreateRequest, user: User | None, parent_id: str | None = None
) -> Case:
    received = data.received_at or utcnow()
    if received.tzinfo is None:
        received = received.replace(tzinfo=IST)  # TRADE-OFF: naive times are assumed IST
    owner = user
    if owner is None and data.sender_email:
        owner = db.scalar(select(User).where(func.lower(User.email) == data.sender_email.lower()))
    case = Case(
        ref=next_ref(db, received.astimezone(UTC).year),
        channel=str(data.channel),
        subject=data.subject.strip(),
        raw_text=data.raw_text,
        sender_email=data.sender_email,
        sender_name=data.sender_name or (user.name if user else None),
        received_at=received,
        owner_id=owner.id if owner else None,
        region=owner.region if owner and owner.region != "All" else "West",
        parent_id=parent_id,
    )
    db.add(case)
    db.flush()
    actor = user.email if user else f"webhook:{data.sender_email or 'unknown'}"
    audit.log_event(
        db,
        action="request.created",
        actor=actor,
        actor_type=ActorType.HUMAN if user else ActorType.SYSTEM,
        request_id=case.id,
        after={"ref": case.ref, "channel": case.channel, "subject": case.subject},
    )
    return case  # analysed afterwards by analysis.analyse_new_case (background)


def list_cases(
    db: Session,
    user: User,
    *,
    status: str | None,
    priority: str | None,
    category: str | None,
    q: str | None,
    mine: bool,
) -> list[Case]:
    query = select(Case).order_by(Case.created_at.desc())
    if user.role == Role.REQUESTER or mine:
        query = query.where(
            or_(Case.owner_id == user.id, func.lower(Case.sender_email) == user.email.lower())
        )
    elif not rbac.sees_all_regions(user):  # managers: their region, routed cases only
        query = query.where(
            or_(and_(Case.region == user.region, Case.approvals.any()), Case.owner_id == user.id)
        )
    for column, value in (
        (Case.status, status),
        (Case.priority, priority),
        (Case.category, category),
    ):
        if value:
            query = query.where(column == value)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(Case.ref.ilike(like), Case.subject.ilike(like)))
    return list(db.scalars(query.limit(500)))


FLAG_KEY = "human:extraction_flagged:{}"
NOT_EDITABLE = TERMINAL | {Status.RESOLVED, Status.ON_HOLD, Status.ANALYZING}


def open_flag(case: Case, name: str) -> Issue | None:
    return next(
        (i for i in case.issues if i.key == FLAG_KEY.format(name) and i.status == IssueStatus.OPEN),
        None,
    )


def flag_field(db: Session, case: Case, name: str, reason: str, user: User) -> None:
    """Edge case 5, step 1: a human marks an extracted value as wrong. The flag blocks sending
    the case for approval until the value is corrected (or the flag is removed)."""
    if Status(case.status) in NOT_EDITABLE:
        raise conflict("ILLEGAL_TRANSITION", f"Fields cannot be flagged in {case.status}")
    current = current_fields(case).get(name)
    if current is None or current.value is None:
        raise conflict("FIELD_NOT_EXTRACTED", "Nothing was extracted to flag — add the value.")
    if open_flag(case, name):
        return
    key = FLAG_KEY.format(name)
    issue = next((i for i in case.issues if i.key == key), None) or Issue(
        request_id=case.id, key=key, agent="human", case=case
    )
    issue.type, issue.severity, issue.status, issue.field = (
        str(IssueType.EXTRACTION_FLAGGED),
        str(Severity.BLOCKER),
        str(IssueStatus.OPEN),
        name,
    )
    issue.message = (
        f"{user.name} flagged the extracted {name.replace('_', ' ')} "
        f'("{current.value}") as incorrect: {reason}'
    )
    issue.details = {"reason": reason, "value": current.value, "flagged_by": user.email}
    issue.resolution_note, issue.resolved_by_id = None, None
    db.add(issue)
    audit.log_event(
        db,
        action="field.flagged",
        actor=user.email,
        request_id=case.id,
        after={"field": name, "value": current.value, "source": current.source},
        reason=reason,
    )


def correct_field(
    db: Session,
    case: Case,
    name: str,
    value: str,
    reason: str,
    user: User,
    *,
    require_flag: bool = True,
) -> None:
    """Edge case 5, step 2: corrections never overwrite; downstream agents re-run. A value the
    AI extracted must be flagged first; a missing value can be added directly. Resolving an
    issue (e.g. a conflict card) is itself the human's decision, so it skips the flag step."""
    if Status(case.status) in NOT_EDITABLE:
        raise conflict("ILLEGAL_TRANSITION", f"Fields cannot be corrected in {case.status}")
    old = current_fields(case).get(name)
    flag = open_flag(case, name)
    ai_value = old is not None and old.value is not None and old.source != FieldSource.HUMAN
    if require_flag and ai_value and not flag:
        raise conflict("FIELD_NOT_FLAGGED", "Flag the extracted value as incorrect first.")
    if flag is not None:
        flag.status, flag.resolved_by_id = str(IssueStatus.RESOLVED), user.id
        flag.resolution_note = f'Corrected to "{value}": {reason}'
    normalized, _ = normalize_field(name, value, case.received_at, inventory.catalog(db))
    if old is not None:
        old.is_current = False
    db.add(
        ExtractedField(
            request_id=case.id,
            field=name,
            value=value,
            normalized_value=normalized,
            evidence=None,
            confidence=1.0,
            source=str(FieldSource.HUMAN),
            corrected_by_id=user.id,
            correction_reason=reason,
            case=case,
        )
    )
    audit.log_event(
        db,
        action="field.corrected",
        actor=user.email,
        request_id=case.id,
        before={
            "field": name,
            "value": old.value if old else None,
            "source": old.source if old else None,
        },
        after={"field": name, "value": value, "normalized": normalized},
        reason=reason,
    )
    db.flush()
    run_analysis(
        db, case, actor=user.email, start_at="validation", reason=f"Field {name} corrected"
    )
    communications.refresh_clarification(db, case, user.email)


def provide_info(db: Session, case: Case, text: str, user: User) -> None:
    if case.status not in {Status.NEEDS_INFO, Status.PENDING_REVIEW}:
        raise conflict("ILLEGAL_TRANSITION", f"Cannot add information in {case.status}")
    if user.role == Role.REQUESTER:  # an answer to the team: keep it in the conversation
        communications.record_reply(db, case, text, user)
    stamp = utcnow().astimezone(IST).strftime("%d %b %Y %H:%M IST")
    case.raw_text = (
        f"{case.raw_text}\n\n--- Additional information ({stamp}, {user.name}) ---\n{text}"
    )
    audit.log_event(
        db,
        action="request.info_provided",
        actor=user.email,
        request_id=case.id,
        after={"text": text[:500]},
    )
    run_analysis(db, case, actor=user.email, reason="Additional information provided")
    communications.refresh_clarification(db, case, user.email)


def reanalyze(db: Session, case: Case, user: User | None, reason: str | None = None) -> None:
    if case.status not in REANALYZABLE:
        raise conflict("ILLEGAL_TRANSITION", f"Cannot re-analyze a case in {case.status}")
    actor = user.email if user else "scheduler"
    run_analysis(
        db,
        case,
        actor=actor,
        actor_type=ActorType.HUMAN if user else ActorType.SYSTEM,
        reason=reason or "Re-analysis requested",
    )
    communications.refresh_clarification(db, case, actor)


def resolve_issue(
    db: Session,
    case: Case,
    issue_id: str,
    resolution: str,
    value: str | None,
    note: str,
    user: User,
) -> None:
    issue = next((i for i in case.issues if i.id == issue_id), None)
    if issue is None:
        raise not_found("Issue")
    if issue.status != IssueStatus.OPEN:
        raise conflict("ISSUE_NOT_OPEN", f"Issue is already {issue.status}")
    chosen = (
        _conflict_value(issue.details, resolution, value)
        if issue.type == IssueType.CONFLICT
        else None
    )
    if resolution == "custom" and issue.type != IssueType.CONFLICT and not value:
        raise bad_request("VALUE_REQUIRED", "A value is required for a custom resolution")
    issue.status = IssueStatus.DISMISSED if resolution == "dismiss" else IssueStatus.RESOLVED
    issue.resolved_by_id, issue.resolution_note = user.id, note
    audit.log_event(
        db,
        action="issue.dismissed" if resolution == "dismiss" else "issue.resolved",
        actor=user.email,
        request_id=case.id,
        after={"issue_id": issue.id, "type": issue.type, "resolution": resolution, "value": chosen},
        reason=note,
    )
    field = issue.field
    if chosen is not None and field:
        correct_field(
            db,
            case,
            field,
            str(chosen),
            f"Conflict resolved ({resolution}): {note}",
            user,
            require_flag=False,
        )
    elif resolution == "custom" and field and value:
        correct_field(db, case, field, value, note, user, require_flag=False)
    elif issue.severity == "blocker" and case.status == Status.NEEDS_INFO:
        run_analysis(
            db,
            case,
            actor=user.email,
            start_at="validation",
            reason=f"Blocking issue {issue.type} {issue.status}",
        )
    communications.refresh_clarification(db, case, user.email)  # one question fewer to ask


def _conflict_value(details: dict, resolution: str, value: str | None) -> int | str | None:
    if resolution == "use_inventory":
        return details.get("inventory_value")
    if resolution == "use_email":
        return details.get("email_value")
    if resolution == "custom":
        if not value:
            raise bad_request("VALUE_REQUIRED", "A value is required for a custom resolution")
        return value
    return None


def override(db: Session, case: Case, data: OverrideRecommendation, user: User) -> None:
    """Edge case / R7: a human option replaces the AI ones, then goes through approval policy."""
    if case.status not in approval_service.SELECTABLE:
        raise conflict("ILLEGAL_TRANSITION", f"Cannot override in {case.status}")
    ai_options = [r for r in case.recommendations if r.status == RecStatus.PROPOSED]
    for r in ai_options:
        r.status, r.override_reason = RecStatus.OVERRIDDEN, data.reason
    rec = Recommendation(
        request_id=case.id,
        rank=0,
        kind="custom",
        title=data.title,
        description=data.description,
        rationale=f"Human override: {data.reason}",
        estimated_cost_inr=data.estimated_cost_inr,
        estimated_lead_time_days=data.estimated_lead_time_days,
        confidence=1.0,
        evidence=["human"],
        created_by="human",
        override_reason=data.reason,
        model="human",
        case=case,
    )
    db.add(rec)
    db.flush()
    audit.log_event(
        db,
        action="recommendation.overridden",
        actor=user.email,
        request_id=case.id,
        before={"ai_options": [r.title for r in ai_options]},
        after={"id": rec.id, "title": rec.title, "cost": rec.estimated_cost_inr},
        reason=data.reason,
    )
    approval_service.select_recommendation(db, case, rec, user, data.reason, data.approver_id)


def link_duplicate(db: Session, case: Case, master_id: str, user: User) -> None:
    master = get_case(db, master_id)
    if master.id == case.id or Status(master.status) in TERMINAL:
        raise bad_request("INVALID_MASTER", "Master must be a different, open request")
    rbac.ensure_can_view(db, user, master)
    case.duplicate_of_id = master.id
    audit.log_event(
        db,
        action="dedup.linked",
        actor=user.email,
        request_id=case.id,
        after={"master_id": master.id, "master_ref": master.ref},
    )
    draft_to_sender(db, case, CommType.DUPLICATE_NOTICE, master_ref=master.ref)
    draft_to_sender(
        db,
        master,
        CommType.STAKEHOLDER_UPDATE,
        recommendation=f"Another report of this issue was received ({case.ref})",
    )
    transition(db, case, Status.DUPLICATE, actor=user.email, reason=f"Duplicate of {master.ref}")


def draft_to_sender(db: Session, case: Case, comm_type: CommType, **facts: object) -> None:
    to = [case.sender_email] if case.sender_email else []
    d, _ = draft_comm(comm_type, communications.case_facts(case, **facts), to)
    communications.create(db, case, d)


def not_duplicate(db: Session, case: Case, user: User) -> None:
    case.dedup_dismissed, case.duplicate_candidates = True, []
    for issue in case.issues:
        if issue.type == IssueType.DUPLICATE and issue.status == IssueStatus.OPEN:
            issue.status, issue.resolved_by_id = IssueStatus.DISMISSED, user.id
            issue.resolution_note = "Marked not a duplicate"
    audit.log_event(
        db,
        action="dedup.dismissed",
        actor=user.email,
        request_id=case.id,
        before={"duplicate_of_id": case.duplicate_of_id},
    )
    if case.status == Status.DUPLICATE:
        case.duplicate_of_id = None
        run_analysis(db, case, actor=user.email, reason="Marked not a duplicate")


def manual_transition(db: Session, case: Case, to: Status, reason: str | None, user: User) -> None:
    resume_target = case.previous_status if case.status == Status.ON_HOLD else None
    if to not in MANUAL_TARGETS and to != resume_target:
        raise conflict(
            "ILLEGAL_TRANSITION", f"{to} is reached through its own action, not a manual transition"
        )
    if to == Status.ON_HOLD and not reason:
        raise bad_request("REASON_REQUIRED", "A reason is required to put a case on hold")
    transition(db, case, to, actor=user.email, reason=reason)
    if to == Status.CLOSED:
        draft_to_sender(db, case, CommType.CLOSURE)


def cancel(
    db: Session, case: Case, reason: str, actor: str, actor_type: ActorType = ActorType.HUMAN
) -> None:
    """Edge case 15: cancel approvals, release stock, notify approvers, draft notices."""
    if Status(case.status) in TERMINAL:
        raise conflict("ILLEGAL_TRANSITION", f"Case is already {case.status}")
    cancelled_roles = []
    for approval in case.approvals:
        if approval.status in IN_FLIGHT_APPROVALS:
            approval.status, approval.decision_note = ApprovalStatus.CANCELLED, reason
            cancelled_roles.append(approval.approver_role)
            audit.log_event(
                db,
                action="approval.cancelled",
                actor=actor,
                actor_type=actor_type,
                request_id=case.id,
                after={"approval_id": approval.id},
                reason=reason,
            )
    work_started = {Status.APPROVED, Status.IN_PROGRESS}
    if case.status in work_started or case.previous_status in work_started:
        chosen = next((r for r in case.recommendations if r.status == RecStatus.SELECTED), None)
        if chosen:
            inventory.adjust_reservations(
                db, chosen.allocations, release=True, actor=actor, request_id=case.id
            )
    summary = f"{len(cancelled_roles)} pending approval(s) cancelled." if cancelled_roles else ""
    for role in sorted(set(cancelled_roles)):
        communications.notify(
            db,
            case,
            CommType.CANCELLATION,
            communications.recipients(db, role, case.region),
            reason=reason,
            cancelled_summary=summary,
        )
    draft_to_sender(db, case, CommType.CANCELLATION, reason=reason, cancelled_summary=summary)
    audit.log_event(
        db,
        action="request.cancelled",
        actor=actor,
        actor_type=actor_type,
        request_id=case.id,
        after={"cancelled_approvals": len(cancelled_roles)},
        reason=reason,
    )
    transition(db, case, Status.CANCELLED, actor=actor, actor_type=actor_type, reason=reason)


def compose_reply(db: Session, case: Case, text: str, user: User) -> composer.ComposedEmail:
    """AI-drafted answer to the team's latest question. Nothing is saved."""
    question = communications.last_question(case)
    sender = case.sender_name or user.name
    return composer.compose_reply(
        question.body if question else case.subject, text, sender, LLMClient(get_settings())
    )


def compose_email(
    db: Session, subject: str | None, text: str, user: User, sender_name: str | None = None
) -> composer.ComposedEmail:
    """AI-written request email from the requester's notes. Draft only: nothing is saved."""
    llm = LLMClient(get_settings(), llm_down=get_flags(db)[str(Flag.LLM_DOWN)])
    return composer.compose(subject, text, sender_name or user.name, llm)
