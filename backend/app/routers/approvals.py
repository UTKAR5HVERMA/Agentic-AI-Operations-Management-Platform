from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.enums import ActorType, Role
from app.errors import bad_request
from app.models import User
from app.rbac import require_role
from app.schemas import ApprovalDecision, ApprovalOut, ApproverOut
from app.services import approvals, views

router = APIRouter(prefix="/approvals", tags=["approvals"])
staff = require_role(Role.OPS_ANALYST, Role.OPS_MANAGER)
MIN_REJECT_NOTE = 5


@router.get("/approvers", response_model=list[ApproverOut])
def list_approvers(db: Session = Depends(get_db), user: User = Depends(staff)) -> list[ApproverOut]:
    """Regional Managers the Operations Team can route an approval to."""
    return [ApproverOut.model_validate(u) for u in approvals.list_approvers(db)]


@router.get("", response_model=list[ApprovalOut])
def list_approvals(
    status: str | None = "pending",
    mine: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ApprovalOut]:
    return [views.approval(a, user) for a in approvals.list_for_user(db, user, status, mine)]


@router.post("/{approval_id}/approve", response_model=ApprovalOut)
def approve(
    approval_id: str,
    body: ApprovalDecision,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ApprovalOut:
    approval = approvals.get_approval(db, approval_id)
    approvals.approve(db, approval, user, body.note, body.reconfirm, body.self_override)
    db.commit()
    return views.approval(approval, user)


@router.post("/{approval_id}/reject", response_model=ApprovalOut)
def reject(
    approval_id: str,
    body: ApprovalDecision,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ApprovalOut:
    if not body.note or len(body.note.strip()) < MIN_REJECT_NOTE:
        raise bad_request("REASON_REQUIRED", "A rejection reason (≥ 5 characters) is required")
    approval = approvals.get_approval(db, approval_id)
    approvals.reject(db, approval, user, body.note.strip())
    db.commit()
    return views.approval(approval, user)


@router.post("/{approval_id}/escalate", response_model=ApprovalOut)
def escalate(
    approval_id: str,
    body: ApprovalDecision,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ApprovalOut:
    approval = approvals.get_approval(db, approval_id)
    approvals.escalate(
        db, approval, actor=user.email, actor_type=ActorType.HUMAN, note=body.note, user=user
    )
    db.commit()
    return views.approval(approval, user)
