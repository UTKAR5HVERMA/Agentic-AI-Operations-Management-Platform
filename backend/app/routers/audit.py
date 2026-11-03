from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import audit as audit_trail
from app.db import get_db
from app.enums import Role
from app.models import User
from app.rbac import require_role
from app.schemas import AuditOut, AuditVerify

router = APIRouter(prefix="/audit", tags=["audit"])
staff = require_role(Role.OPS_ANALYST, Role.OPS_MANAGER)


@router.get("", response_model=list[AuditOut])
def list_audit(
    request_id: str | None = None,
    actor_type: str | None = None,
    action: str | None = None,
    actor: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(default=500, ge=1, le=2000),
    db: Session = Depends(get_db),
    user: User = Depends(staff),
) -> list[AuditOut]:
    rows = audit_trail.search(
        db,
        request_id=request_id,
        actor_type=actor_type,
        actor=actor,
        action=action,
        since=since,
        until=until,
        limit=limit,
    )
    return [AuditOut.model_validate(r).model_copy(update={"request_ref": ref}) for r, ref in rows]


@router.get("/verify", response_model=AuditVerify)
def verify(db: Session = Depends(get_db), user: User = Depends(staff)) -> AuditVerify:
    return AuditVerify(**audit_trail.verify_chain(db))
