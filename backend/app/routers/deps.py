"""Shared router dependencies: load a case with visibility + action checks."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app import rbac
from app.models import Case, User
from app.services.cases import check_version, get_case


def case_for_action(
    db: Session, user: User, case_id: str, action: str, version: int | None = None
) -> Case:
    case = get_case(db, case_id)
    rbac.ensure_action(db, user, case, action)
    check_version(case, version)
    return case


def case_for_view(db: Session, user: User, case_id: str) -> Case:
    case = get_case(db, case_id)
    rbac.ensure_can_view(db, user, case)
    return case
