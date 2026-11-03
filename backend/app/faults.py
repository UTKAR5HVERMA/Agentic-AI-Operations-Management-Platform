"""Fault-injection flags for the demo (llm_down, inventory_down, email_down) — edge cases 10, 13."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.enums import Flag
from app.models import SystemFlag, User


def get_flags(db: Session) -> dict[str, bool]:
    stored = {f.key: f.value for f in db.scalars(select(SystemFlag))}
    return {str(flag): stored.get(str(flag), False) for flag in Flag}


def is_down(db: Session, flag: Flag) -> bool:
    row = db.get(SystemFlag, str(flag))
    return bool(row and row.value)


def set_flags(db: Session, updates: dict[str, bool], user: User) -> dict[str, bool]:
    before = get_flags(db)
    for key, value in updates.items():
        row = db.get(SystemFlag, key) or SystemFlag(key=key)
        row.value = value
        db.add(row)
    db.flush()
    after = get_flags(db)
    audit.log_event(db, action="system.flags_changed", actor=user.email, before=before, after=after)
    for key, value in updates.items():
        if value and not before[key]:
            audit.log_event(
                db,
                action="system.unavailable",
                actor=user.email,
                after={"system": key.removesuffix("_down")},
                reason="Fault injected from Scenario Lab",
            )
    return after
