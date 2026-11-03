from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db, utcnow
from app.enums import Role
from app.models import User
from app.rbac import require_role
from app.schemas import ManagementSummary
from app.services import reports

router = APIRouter(prefix="/reports", tags=["reports"])
staff = require_role(Role.OPS_ANALYST, Role.OPS_MANAGER)


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), user: User = Depends(staff)) -> dict[str, Any]:
    return reports.dashboard(db)


@router.post("/management-summary", response_model=ManagementSummary)
def management_summary(
    db: Session = Depends(get_db), user: User = Depends(staff)
) -> ManagementSummary:
    markdown, metrics, model, comm_id = reports.management_summary(db, user)
    db.commit()
    return ManagementSummary(
        markdown=markdown,
        metrics=metrics,
        generated_at=utcnow(),
        model=model,
        communication_id=comm_id,
    )
