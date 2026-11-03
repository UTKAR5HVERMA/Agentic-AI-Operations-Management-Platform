"""Health, demo reset and simulation helpers (admin / Scenario Lab)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app import audit
from app.config import get_settings
from app.db import Base, SessionLocal, get_engine, utcnow
from app.enums import IN_FLIGHT_APPROVALS, ActorType
from app.errors import conflict, not_found
from app.faults import get_flags
from app.models import Approval, User
from app.seed import seed_if_empty


def health(db: Session) -> dict[str, str]:
    settings = get_settings()
    try:
        db.execute(text("SELECT 1"))
        db_status = "up"
    except Exception:  # health must report, not raise
        db_status = "down"
    flags = get_flags(db) if db_status == "up" else {}
    if flags.get("llm_down"):
        llm = "down"
    elif settings.llm_configured:
        llm = "up"
    else:
        llm = "fallback"
    inventory = "down" if flags.get("inventory_down") else "up"
    email = "down" if flags.get("email_down") else "up"
    ok = db_status == "up" and llm != "down" and inventory == "up" and email == "up"
    return {
        "status": "ok" if ok else "degraded",
        "llm": llm,
        "inventory": inventory,
        "email": email,
        "db": db_status,
        "llm_mode": settings.llm_mode,
        "model": settings.llm_model if settings.llm_configured else "fallback",
    }


def reset_demo(db: Session, user: User) -> None:
    """Wipe every table and reseed. The audit chain restarts with a reset record."""
    actor = user.email
    db.close()
    engine = get_engine()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as fresh:
        seed_if_empty(fresh)
        audit.log_event(
            fresh, action="admin.demo_reset", actor=actor, reason="Demo data wiped and reseeded"
        )
        fresh.commit()


def expire_approval(db: Session, approval_id: str, user: User) -> Approval:
    approval = db.get(Approval, approval_id)
    if approval is None:
        raise not_found("Approval")
    if approval.status not in IN_FLIGHT_APPROVALS:
        raise conflict("APPROVAL_NOT_PENDING", f"Approval is already {approval.status}")
    before = approval.due_at
    approval.due_at = utcnow() - timedelta(minutes=1)
    audit.log_event(
        db,
        action="simulate.approval_timeout",
        actor=user.email,
        actor_type=ActorType.HUMAN,
        request_id=approval.request_id,
        before={"due_at": before},
        after={"due_at": approval.due_at},
        reason="Scenario Lab: simulate approver not responding",
    )
    return approval
