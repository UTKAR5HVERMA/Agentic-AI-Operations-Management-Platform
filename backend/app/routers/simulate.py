from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import scheduler
from app.db import get_db
from app.enums import Role
from app.models import User
from app.rbac import require_role
from app.schemas import ApprovalOut, TickResult
from app.services import admin, views

router = APIRouter(prefix="/simulate", tags=["simulate"])
admin_only = require_role(Role.ADMIN)


@router.post("/approval-timeout/{approval_id}", response_model=ApprovalOut)
def approval_timeout(
    approval_id: str, db: Session = Depends(get_db), user: User = Depends(admin_only)
) -> ApprovalOut:
    approval = admin.expire_approval(db, approval_id, user)
    db.flush()
    scheduler.tick(db)
    return views.approval(approval, user)


@router.post("/scheduler-tick", response_model=TickResult)
def scheduler_tick(db: Session = Depends(get_db), user: User = Depends(admin_only)) -> TickResult:
    return TickResult(**scheduler.tick(db))
