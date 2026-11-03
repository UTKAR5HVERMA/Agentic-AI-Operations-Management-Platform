from __future__ import annotations

import hmac

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query
from sqlalchemy.orm import Session

from app import audit
from app.auth import get_current_user
from app.config import get_settings
from app.db import get_db
from app.enums import ActorType, Status
from app.errors import ApiError, not_found
from app.models import User
from app.routers.deps import case_for_action, case_for_view
from app.schemas import (
    CommunicationOut,
    ComposedEmailOut,
    ComposeReply,
    ComposeRequest,
    CreateRequest,
    DuplicateLink,
    EventIn,
    FieldCorrection,
    FieldFlag,
    GenerateComm,
    IssueResolution,
    OverrideRecommendation,
    ProvideInfo,
    ReasonRequest,
    RequestDetail,
    RequestSummary,
    SelectRecommendation,
    TransitionRequest,
    Versioned,
)
from app.services import analysis, approvals, cases, communications, events, views

router = APIRouter(prefix="/requests", tags=["requests"])

# Transition target → the action that authorises it.
TRANSITION_ACTIONS = {
    Status.RESOLVED: "resolve",
    Status.CLOSED: "close",
    Status.IN_PROGRESS: "reopen",
    Status.ON_HOLD: "hold",
}


@router.post("", response_model=RequestDetail, status_code=201)
def create_request(
    body: CreateRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RequestDetail:
    """Returns at once with status NEW; the agents analyse the request in the background."""
    case = cases.create_case(db, body, user)
    db.commit()
    background.add_task(analysis.analyse_new_case, case.id)
    return views.detail(db, case, user)


@router.post("/compose", response_model=ComposedEmailOut)
def compose_email(
    body: ComposeRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> ComposedEmailOut:
    """AI-generated request email (subject + body) from rough notes. Nothing is saved."""
    composed = cases.compose_email(db, body.subject, body.text, user, body.sender_name)
    return ComposedEmailOut(**composed.__dict__)


@router.post("/ingest-email", response_model=RequestSummary, status_code=201)
def ingest_email(
    body: CreateRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    x_webhook_secret: str = Header(default=""),
) -> RequestSummary:
    if not hmac.compare_digest(x_webhook_secret, get_settings().webhook_secret):
        audit.log_event(
            db,
            action="auth.denied",
            actor="webhook",
            actor_type=ActorType.SYSTEM,
            reason="Invalid X-Webhook-Secret",
        )
        db.commit()
        raise ApiError(401, "INVALID_WEBHOOK_SECRET", "Invalid webhook secret")
    case = cases.create_case(db, body.model_copy(update={"channel": "email"}), None)
    db.commit()
    background.add_task(analysis.analyse_new_case, case.id)
    return views.summary(case)


@router.get("", response_model=list[RequestSummary])
def list_requests(
    status: str | None = None,
    priority: str | None = None,
    category: str | None = None,
    q: str | None = Query(default=None, max_length=100),
    mine: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[RequestSummary]:
    rows = cases.list_cases(
        db, user, status=status, priority=priority, category=category, q=q, mine=mine
    )
    return [views.summary(c) for c in rows]


@router.get("/{case_id}", response_model=RequestDetail)
def get_request(
    case_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> RequestDetail:
    return views.detail(db, case_for_view(db, user, case_id), user)


@router.patch("/{case_id}/fields", response_model=RequestDetail)
def correct_field(
    case_id: str,
    body: FieldCorrection,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RequestDetail:
    case = case_for_action(db, user, case_id, "correct_field", body.version)
    cases.correct_field(db, case, str(body.field), body.value, body.reason, user)
    db.commit()
    return views.detail(db, case, user)


@router.post("/{case_id}/fields/flag", response_model=RequestDetail)
def flag_field(
    case_id: str,
    body: FieldFlag,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RequestDetail:
    case = case_for_action(db, user, case_id, "flag_field", body.version)
    cases.flag_field(db, case, str(body.field), body.reason, user)
    db.commit()
    return views.detail(db, case, user)


@router.post("/{case_id}/reanalyze", response_model=RequestDetail)
def reanalyze(
    case_id: str,
    body: Versioned | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RequestDetail:
    case = case_for_action(db, user, case_id, "reanalyze", body.version if body else None)
    cases.reanalyze(db, case, user)
    db.commit()
    return views.detail(db, case, user)


@router.post("/{case_id}/compose-reply", response_model=ComposedEmailOut)
def compose_reply(
    case_id: str,
    body: ComposeReply,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ComposedEmailOut:
    """AI-written reply to the team's question from rough notes. Nothing is saved."""
    case = case_for_action(db, user, case_id, "provide_info")
    return ComposedEmailOut(**cases.compose_reply(db, case, body.text, user).__dict__)


@router.post("/{case_id}/provide-info", response_model=RequestDetail)
def provide_info(
    case_id: str,
    body: ProvideInfo,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RequestDetail:
    case = case_for_action(db, user, case_id, "provide_info", body.version)
    cases.provide_info(db, case, body.text, user)
    db.commit()
    return views.detail(db, case, user)


@router.post("/{case_id}/issues/{issue_id}/resolve", response_model=RequestDetail)
def resolve_issue(
    case_id: str,
    issue_id: str,
    body: IssueResolution,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RequestDetail:
    case = case_for_action(db, user, case_id, "resolve_issue", body.version)
    cases.resolve_issue(db, case, issue_id, body.resolution, body.value, body.note, user)
    db.commit()
    return views.detail(db, case, user)


@router.post("/{case_id}/recommendations/{rec_id}/select", response_model=RequestDetail)
def select_recommendation(
    case_id: str,
    rec_id: str,
    body: SelectRecommendation,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RequestDetail:
    case = case_for_action(db, user, case_id, "select_recommendation", body.version)
    rec = next((r for r in case.recommendations if r.id == rec_id), None)
    if rec is None:
        raise not_found("Recommendation")
    approvals.select_recommendation(db, case, rec, user, body.note, body.approver_id)
    db.commit()
    return views.detail(db, case, user)


@router.post("/{case_id}/override", response_model=RequestDetail)
def override(
    case_id: str,
    body: OverrideRecommendation,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RequestDetail:
    case = case_for_action(db, user, case_id, "override", body.version)
    cases.override(db, case, body, user)
    db.commit()
    return views.detail(db, case, user)


@router.post("/{case_id}/duplicate", response_model=RequestDetail)
def mark_duplicate(
    case_id: str,
    body: DuplicateLink,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RequestDetail:
    case = case_for_action(db, user, case_id, "mark_duplicate", body.version)
    cases.link_duplicate(db, case, body.master_id, user)
    db.commit()
    return views.detail(db, case, user)


@router.post("/{case_id}/not-duplicate", response_model=RequestDetail)
def not_duplicate(
    case_id: str,
    body: Versioned | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RequestDetail:
    case = case_for_action(db, user, case_id, "not_duplicate", body.version if body else None)
    cases.not_duplicate(db, case, user)
    db.commit()
    return views.detail(db, case, user)


@router.post("/{case_id}/transition", response_model=RequestDetail)
def manual_transition(
    case_id: str,
    body: TransitionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RequestDetail:
    case = cases.get_case(db, case_id)
    action = (
        "resume"
        if case.status == Status.ON_HOLD and body.to != Status.ON_HOLD
        else TRANSITION_ACTIONS.get(body.to, "hold")
    )
    case = case_for_action(db, user, case_id, action, body.version)
    cases.manual_transition(db, case, body.to, body.reason, user)
    db.commit()
    return views.detail(db, case, user)


@router.post("/{case_id}/cancel", response_model=RequestDetail)
def cancel(
    case_id: str,
    body: ReasonRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RequestDetail:
    case = case_for_action(db, user, case_id, "cancel", body.version)
    cases.cancel(db, case, body.reason, user.email)
    db.commit()
    return views.detail(db, case, user)


@router.post("/{case_id}/events", response_model=RequestDetail)
def add_event(
    case_id: str,
    body: EventIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RequestDetail:
    case = case_for_action(db, user, case_id, "add_event", body.version)
    events.add_event(db, case, body.type, body.payload, user)
    db.commit()
    return views.detail(db, case, user)


@router.post("/{case_id}/communications/generate", response_model=CommunicationOut, status_code=201)
def generate_communication(
    case_id: str,
    body: GenerateComm,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommunicationOut:
    case = case_for_action(db, user, case_id, "generate_comm")
    comm = communications.generate(db, case, body.type, user)
    db.commit()
    return CommunicationOut.model_validate(comm)
