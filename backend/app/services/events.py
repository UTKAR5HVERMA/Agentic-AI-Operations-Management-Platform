"""External changes after the workflow started (edge cases 9 and 15)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app import audit, rbac
from app.db import utcnow
from app.enums import (
    ActorType,
    CommType,
    EventType,
    FieldSource,
    IssueStatus,
    IssueType,
    Severity,
    Status,
)
from app.errors import bad_request, conflict
from app.models import Case, Event, ExtractedField, Issue, User
from app.normalize import normalize_field
from app.services import cases, inventory
from app.services.analysis import current_fields, run_analysis
from app.state_machine import TERMINAL, transition


def _int(payload: dict[str, Any], key: str) -> int:
    try:
        value = int(payload[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise bad_request("INVALID_PAYLOAD", f"payload.{key} must be an integer") from exc
    if value < 0:
        raise bad_request("INVALID_PAYLOAD", f"payload.{key} must be ≥ 0")
    return value


def _set_field(db: Session, case: Case, name: str, value: str, reason: str) -> dict[str, Any]:
    old = current_fields(case).get(name)
    normalized, _ = normalize_field(name, value, utcnow(), inventory.catalog(db))
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
            source=str(FieldSource.EVENT),
            correction_reason=reason,
            case=case,
        )
    )
    return {"field": name, "old": old.value if old else None, "new": value}


def _changed_banner(db: Session, case: Case, event: Event, message: str) -> None:
    db.add(
        Issue(
            request_id=case.id,
            key=f"events:circumstances_changed:{event.id}",
            agent="events",
            type=str(IssueType.CIRCUMSTANCES_CHANGED),
            severity=str(Severity.INFO),
            status=str(IssueStatus.OPEN),
            message=message,
            details={"event_id": event.id, "diff": event.diff},
            case=case,
        )
    )


def add_event(
    db: Session, case: Case, event_type: EventType, payload: dict[str, Any], user: User
) -> Event:
    if Status(case.status) in TERMINAL or case.status in {Status.NEW, Status.ANALYZING}:
        raise conflict("ILLEGAL_TRANSITION", f"Events cannot be added in {case.status}")
    event = Event(
        request_id=case.id, type=str(event_type), payload=payload, created_by=user.email, case=case
    )
    db.add(event)
    db.flush()
    handler = {
        EventType.SUPPLIER_DATE_REVISED: _supplier_revised,
        EventType.INVENTORY_UPDATED: _inventory_updated,
        EventType.STAKEHOLDER_REPLY: _stakeholder_reply,
        EventType.LAUNCH_POSTPONED: _launch_postponed,
    }[event_type]
    handler(db, case, event, user)
    event.processed = True
    audit.log_event(
        db,
        action="event.processed",
        actor=user.email,
        request_id=case.id,
        after={"event_id": event.id, "type": event.type, "diff": event.diff},
    )
    return event


def _supplier_revised(db: Session, case: Case, event: Event, user: User) -> None:
    payload = event.payload
    if "new_delay_days" not in payload and "new_required_date" not in payload:
        raise bad_request("INVALID_PAYLOAD", "Provide new_delay_days and/or new_required_date")
    diffs = []
    if "new_delay_days" in payload:
        days = _int(payload, "new_delay_days")
        diffs.append(_set_field(db, case, "delay_days", str(days), "Supplier revised delay"))
    if "new_required_date" in payload:
        diffs.append(
            _set_field(
                db,
                case,
                "required_date",
                str(payload["new_required_date"]),
                "Required date revised",
            )
        )
    event.diff = {"changes": diffs}
    text = "; ".join(f"{d['field']} {d['old']} → {d['new']}" for d in diffs)
    _changed_banner(
        db,
        case,
        event,
        f"Circumstances changed: {text}. Risk and recommendations "
        f"were re-assessed; pending approvals need re-confirmation.",
    )
    db.flush()
    _reassess(db, case, user, f"Supplier revision: {text}")


def _inventory_updated(db: Session, case: Case, event: Event, user: User) -> None:
    p = event.payload
    if not p.get("sku") or not p.get("location"):
        raise bad_request("INVALID_PAYLOAD", "Provide sku, location and on_hand")
    change = inventory.set_on_hand(
        db, str(p["sku"]), str(p["location"]), _int(p, "on_hand"), user.email, case.id
    )
    event.diff = {"changes": [{"field": f"inventory.{p['location']}", **change}]}
    _changed_banner(
        db,
        case,
        event,
        f"Inventory at {p['location']} changed {change['old']} → "
        f"{change['new']}; case re-assessed.",
    )
    db.flush()
    _reassess(db, case, user, "Inventory updated")


def _stakeholder_reply(db: Session, case: Case, event: Event, user: User) -> None:
    text = str(event.payload.get("text", "")).strip()
    if not text:
        raise bad_request("INVALID_PAYLOAD", "Provide payload.text")
    event.diff = {"changes": [{"field": "raw_text", "appended": text[:200]}]}
    cases.provide_info(db, case, text, user)


def _launch_postponed(db: Session, case: Case, event: Event, user: User) -> None:
    detail = event.payload.get("reason")
    reason = f"Launch postponed: {detail}" if detail else "Launch postponed"
    event.diff = {"changes": [{"field": "status", "old": case.status, "new": "CANCELLED"}]}
    if rbac.has_approved_spend(case) and user.role not in rbac.SPEND_CANCEL_ROLES:
        # Cancelling approved spend needs a manager: hold the case and ask for that decision.
        event.diff = {"changes": [{"field": "status", "old": case.status, "new": "ON_HOLD"}]}
        db.add(
            Issue(
                request_id=case.id,
                key=f"events:circumstances_changed:{event.id}",
                agent="events",
                type=str(IssueType.CIRCUMSTANCES_CHANGED),
                severity=str(Severity.BLOCKER),
                status=str(IssueStatus.OPEN),
                message=f"{reason}. Spend is already approved, so an Ops Manager must "
                f"confirm the cancellation.",
                details={"event_id": event.id},
                case=case,
            )
        )
        transition(db, case, Status.ON_HOLD, actor=user.email, reason=reason)
        return
    cases.cancel(db, case, reason, user.email)


def _reassess(db: Session, case: Case, user: User, reason: str) -> None:
    run_analysis(
        db, case, actor=user.email, actor_type=ActorType.HUMAN, start_at="validation", reason=reason
    )
    if case.status in {Status.APPROVED, Status.IN_PROGRESS} and case.sender_email:
        cases.draft_to_sender(db, case, CommType.STAKEHOLDER_UPDATE)
