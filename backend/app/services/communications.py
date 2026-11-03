"""Drafts, sending, delivery retries and internal notifications (edge case 13).

Customer-facing drafts are only sent by a human ("approve & send"). Internal notifications
(approval requests, escalations, reminders) are sent by the system. Failed sends retry with
backoff 1, 2, 4 minutes. The first failure raises a case issue at once (so the team is alerted
while retries run); after 3 failures the in-app fallback is used; a later delivery closes the issue.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.agents import communication as comms_agent
from app.config import get_settings
from app.db import utcnow
from app.enums import ActorType, CommStatus, CommType, IssueStatus, IssueType, Role, Severity
from app.errors import conflict
from app.llm.client import LLMClient
from app.models import Case, Communication, Issue, User
from app.normalize import IST
from app.services import notifier
from app.services.analysis import current_fields

MAX_ATTEMPTS = 3
BACKOFF_MINUTES = (1, 2, 4)
SENDABLE = {CommStatus.DRAFT, CommStatus.APPROVED, CommStatus.FAILED}


def recipients(db: Session, role: Role | str, region: str) -> list[str]:
    query = select(User.email).where(User.role == str(role))
    if role != Role.ADMIN:
        query = query.where(User.region == region)
    return list(db.scalars(query))


def case_facts(case: Case, **extra: Any) -> dict[str, Any]:
    """Facts for templates/LLM drafts outside the graph — sanitized data only."""
    fields = current_fields(case)

    def value(name: str) -> Any:
        return fields[name].value if name in fields else None

    reconciled = next(
        (r for r in case.risk_assessments if r.is_current and r.agent == "reconciled"), None
    )
    chosen = next((r for r in case.recommendations if r.status == "selected"), None)
    return {
        "ref": case.ref,
        "subject": case.subject,
        "recipient_name": case.sender_name,
        "item": value("item"),
        "quantity_required": value("quantity_required"),
        "location": value("location"),
        "risk_level": reconciled.risk_level if reconciled else None,
        "recommendation": chosen.title if chosen else None,
        "status": case.status,
        **extra,
    }


ORIGINAL_MAX_CHARS = 2_000


def original_request(case: Case) -> dict[str, Any]:
    """The requester's original message, forwarded to approvers. Uses the sanitized text, so
    quarantined injection spans are never passed on."""
    text = case.sanitized_text or case.raw_text
    sender = " ".join(x for x in (case.sender_name, f"<{case.sender_email}>") if x)
    return {
        "original_from": sender if case.sender_email else case.sender_name,
        "original_channel": case.channel,
        "original_received_at": case.received_at,
        "original_text": text[:ORIGINAL_MAX_CHARS]
        + ("…" if len(text) > ORIGINAL_MAX_CHARS else ""),
    }


def create(
    db: Session, case: Case | None, d: dict[str, Any], created_by: str = "agent"
) -> Communication:
    comm = Communication(
        request_id=case.id if case else None,
        type=d["type"],
        to=d["to"],
        subject=d["subject"],
        body=d["body"],
        model=d.get("model", "template"),
        created_by=created_by,
    )
    if case is not None:
        comm.case = case
    db.add(comm)
    db.flush()
    return comm


def notify(
    db: Session,
    case: Case,
    comm_type: CommType,
    to: list[str],
    *,
    actor: str = "system",
    **facts: Any,
) -> Communication:
    """Draft from a template and send immediately (internal, system-originated messages)."""
    d, _ = comms_agent.draft(comm_type, case_facts(case, **facts), to)
    comm = create(db, case, d)
    send(db, comm, actor=actor, actor_type=ActorType.SYSTEM)
    return comm


def send(
    db: Session, comm: Communication, *, actor: str, actor_type: ActorType = ActorType.HUMAN
) -> Communication:
    if comm.status not in SENDABLE:
        raise conflict("COMM_NOT_SENDABLE", f"Communication is already {comm.status}")
    comm.attempts += 1
    try:
        message_id = notifier.deliver(db, comm)
    except notifier.DeliveryError as exc:
        _record_failure(db, comm, str(exc), actor, actor_type)
        return comm
    comm.status, comm.sent_at, comm.delivered_via = CommStatus.SENT, utcnow(), "email"
    comm.last_error, comm.next_retry_at = None, None
    _close_failure_issue(db, comm)
    audit.log_event(
        db,
        action="comm.sent",
        actor=actor,
        actor_type=actor_type,
        request_id=comm.request_id,
        after={
            "id": comm.id,
            "type": comm.type,
            "to": comm.to,
            "message_id": message_id,
            "attempt": comm.attempts,
        },
    )
    return comm


def _record_failure(
    db: Session, comm: Communication, error: str, actor: str, actor_type: ActorType
) -> None:
    comm.status, comm.last_error = CommStatus.FAILED, error
    exhausted = comm.attempts >= MAX_ATTEMPTS
    comm.next_retry_at = (
        None if exhausted else utcnow() + timedelta(minutes=BACKOFF_MINUTES[comm.attempts - 1])
    )
    audit.log_event(
        db,
        action="comm.failed",
        actor=actor,
        actor_type=actor_type,
        request_id=comm.request_id,
        after={
            "id": comm.id,
            "attempt": comm.attempts,
            "error": error,
            "next_retry_at": comm.next_retry_at,
        },
    )
    if exhausted:
        _fallback_channel(db, comm)
    _raise_failure_issue(db, comm)


def _fallback_channel(db: Session, comm: Communication) -> None:
    comm.delivered_via = "in_app"
    audit.log_event(
        db,
        action="comm.fallback_channel",
        actor="notifier",
        actor_type=ActorType.SYSTEM,
        request_id=comm.request_id,
        after={"id": comm.id, "channel": "in_app"},
        reason=f"Email failed {comm.attempts} times; posted as in-app notification",
    )


def _failure_issue(db: Session, comm: Communication) -> Issue | None:
    if comm.request_id is None:
        return None
    key = f"notifier:communication_failure:{comm.id}"
    return db.scalar(select(Issue).where(Issue.request_id == comm.request_id, Issue.key == key))


def _raise_failure_issue(db: Session, comm: Communication) -> None:
    """Alert the team on the first failure; keep one issue per message up to date."""
    if comm.request_id is None:
        return
    to = ", ".join(comm.to) or "no recipient"
    if comm.delivered_via == "in_app":
        message = (
            f"'{comm.subject}' to {to} could not be emailed after {comm.attempts} attempts; "
            f"posted in-app instead. Last error: {comm.last_error}"
        )
    else:
        retry = comm.next_retry_at.astimezone(IST).strftime("%H:%M IST")
        message = (
            f"'{comm.subject}' to {to} was not delivered (attempt {comm.attempts}/"
            f"{MAX_ATTEMPTS}): {comm.last_error}. Retrying automatically at {retry}."
        )
    issue = _failure_issue(db, comm)
    if issue is None:
        issue = Issue(
            request_id=comm.request_id,
            key=f"notifier:communication_failure:{comm.id}",
            agent="notifier",
            type=str(IssueType.COMMUNICATION_FAILURE),
            severity=str(Severity.WARNING),
            status=str(IssueStatus.OPEN),
            message=message,
            details={"communication_id": comm.id, "to": comm.to},
        )
        db.add(issue)
        audit.log_event(
            db,
            action="issue.raised",
            actor="notifier",
            actor_type=ActorType.SYSTEM,
            request_id=comm.request_id,
            after={"type": issue.type, "communication_id": comm.id},
            reason=message,
        )
    issue.status, issue.message = str(IssueStatus.OPEN), message
    db.flush()


def _close_failure_issue(db: Session, comm: Communication) -> None:
    issue = _failure_issue(db, comm)
    if issue is None or issue.status != IssueStatus.OPEN:
        return
    note = f"Delivered by email on attempt {comm.attempts}"
    issue.status, issue.resolution_note = str(IssueStatus.RESOLVED), note
    audit.log_event(
        db,
        action="issue.resolved",
        actor="notifier",
        actor_type=ActorType.SYSTEM,
        request_id=comm.request_id,
        after={"issue_id": issue.id, "type": issue.type, "resolution": "delivered"},
        reason=note,
    )


def retry_due(db: Session) -> int:
    due = db.scalars(
        select(Communication).where(
            Communication.status == CommStatus.FAILED,
            Communication.attempts < MAX_ATTEMPTS,
            Communication.next_retry_at <= utcnow(),
        )
    )
    count = 0
    for comm in due:
        audit.log_event(
            db,
            action="comm.retry",
            actor="scheduler",
            actor_type=ActorType.SYSTEM,
            request_id=comm.request_id,
            after={"id": comm.id, "attempt": comm.attempts + 1},
        )
        send(db, comm, actor="scheduler", actor_type=ActorType.SYSTEM)
        count += 1
    return count


def discard(db: Session, comm: Communication, user: User) -> Communication:
    """Delete an unsent draft. Kept as status `discarded` (hidden in the UI) so the audit trail
    can still point at it."""
    if comm.status not in {CommStatus.DRAFT, CommStatus.FAILED}:
        raise conflict("COMM_NOT_DISCARDABLE", f"A {comm.status} communication cannot be deleted")
    before = comm.status
    comm.status, comm.next_retry_at = CommStatus.DISCARDED, None
    audit.log_event(
        db,
        action="comm.discarded",
        actor=user.email,
        request_id=comm.request_id,
        before={"status": before},
        after={"id": comm.id, "type": comm.type, "subject": comm.subject},
    )
    return comm


def update(
    db: Session, comm: Communication, subject: str, body: str, to: list[str] | None, user: User
) -> Communication:
    if comm.status not in {CommStatus.DRAFT, CommStatus.FAILED}:
        raise conflict("COMM_NOT_EDITABLE", f"A {comm.status} communication cannot be edited")
    before = {"subject": comm.subject, "body": comm.body, "to": comm.to}
    comm.subject, comm.body, comm.edited = subject, body, True
    if to is not None:
        comm.to = to
    audit.log_event(
        db,
        action="comm.edited",
        actor=user.email,
        request_id=comm.request_id,
        before=before,
        after={"subject": subject, "body": body, "to": comm.to},
    )
    return comm


def last_question(case: Case) -> Communication | None:
    """The latest clarification the requester actually received."""
    sent = [m for m in case.communications if m.type == CommType.CLARIFICATION and m.sent_at]
    return max(sent, key=lambda m: m.sent_at) if sent else None


def record_reply(db: Session, case: Case, text: str, user: User) -> Communication:
    """Store the requester's in-app answer in the case conversation (inbound, never emailed)."""
    question = last_question(case)
    team = list(db.scalars(select(User.email).where(User.role == str(Role.OPS_ANALYST))))
    comm = create(
        db,
        case,
        {
            "type": str(CommType.REQUESTER_REPLY),
            "to": team,
            "subject": f"Re: {question.subject if question else case.subject}"[:300],
            "body": text,
            "model": "human",
        },
        created_by="human",
    )
    comm.status, comm.sent_at, comm.delivered_via = CommStatus.SENT, utcnow(), "in_app"
    audit.log_event(
        db,
        action="comm.reply_received",
        actor=user.email,
        request_id=case.id,
        after={"id": comm.id, "in_reply_to": question.id if question else None},
    )
    return comm


CLARIFY_ISSUE_TYPES = {IssueType.MISSING_INFO, IssueType.AMBIGUITY, IssueType.CONFLICT}


def open_draft(case: Case, comm_type: CommType) -> Communication | None:
    return next(
        (
            m
            for m in case.communications
            if m.type == comm_type and m.status in {CommStatus.DRAFT, CommStatus.FAILED}
        ),
        None,
    )


def _clarify_facts(case: Case) -> dict[str, Any]:
    """Facts for one clarification covering every open question, each with its context."""
    open_issues = [
        {"type": i.type, "field": i.field, "details": i.details or {}, "status": i.status}
        for i in case.issues
        if i.status == IssueStatus.OPEN and i.field and i.type in CLARIFY_ISSUE_TYPES
    ]
    open_ambiguity = any(
        i.status == IssueStatus.OPEN and i.type == IssueType.AMBIGUITY and not i.field
        for i in case.issues
    )
    return {
        "missing": list(dict.fromkeys(i["field"] for i in open_issues)),
        "questions": comms_agent.clarify_questions(open_issues),
        "sub_issues": [s["title"] for s in case.sub_requests or []] if open_ambiguity else [],
    }


def _draft_audit(
    db: Session, case: Case, comm: Communication, d: dict[str, Any], result: Any, reason: str
) -> None:
    audit.log_event(
        db,
        action="communication.drafted",
        actor="communication",
        actor_type=ActorType.AGENT,
        request_id=case.id,
        after={"id": comm.id, "type": comm.type},
        reason=reason,
        meta=audit.AgentMeta(
            model=d["model"],
            prompt_hash=result.prompt_hash if result else None,
            latency_ms=result.latency_ms if result else None,
        ),
    )


def generate(db: Session, case: Case, comm_type: CommType, user: User) -> Communication:
    # One unsent draft per type: asking again opens the existing one instead of duplicating it.
    # An untouched clarification is re-drafted so it asks only what is still open.
    existing = open_draft(case, comm_type)
    if existing and (existing.edited or comm_type != CommType.CLARIFICATION):
        return existing
    to = [case.sender_email] if case.sender_email else []
    if comm_type == CommType.ESCALATION:
        to = recipients(db, Role.ADMIN, case.region)
    extra = _clarify_facts(case) if comm_type == CommType.CLARIFICATION else {}
    llm = LLMClient(get_settings())
    d, result = comms_agent.draft(comm_type, case_facts(case, **extra), to, llm)
    if existing:
        existing.subject, existing.body, existing.model = d["subject"], d["body"], d["model"]
        _draft_audit(db, case, existing, d, result, f"Refreshed for {user.email}")
        return existing
    comm = create(db, case, d)
    _draft_audit(db, case, comm, d, result, f"Requested by {user.email}")
    return comm


def refresh_clarification(db: Session, case: Case, actor: str) -> None:
    """After re-analysis, an unsent and unedited clarification follows the open questions: it is
    deleted once nothing is left to ask, otherwise re-drafted (template, no extra LLM call)."""
    draft = open_draft(case, CommType.CLARIFICATION)
    if draft is None or draft.edited:
        return
    facts = _clarify_facts(case)
    if not facts["questions"] and not facts["sub_issues"]:
        draft.status, draft.next_retry_at = CommStatus.DISCARDED, None
        audit.log_event(
            db,
            action="comm.discarded",
            actor=actor,
            actor_type=ActorType.SYSTEM,
            request_id=case.id,
            after={"id": draft.id, "type": draft.type},
            reason="All questions answered; the clarification is no longer needed",
        )
        return
    d, _ = comms_agent.draft(CommType.CLARIFICATION, case_facts(case, **facts), draft.to)
    if (draft.subject, draft.body) != (d["subject"], d["body"]):
        draft.subject, draft.body, draft.model = d["subject"], d["body"], d["model"]
        audit.log_event(
            db,
            action="comm.refreshed",
            actor=actor,
            actor_type=ActorType.SYSTEM,
            request_id=case.id,
            after={"id": draft.id, "questions": facts["questions"]},
        )
