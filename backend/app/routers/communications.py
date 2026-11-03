from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import rbac
from app.auth import get_current_user
from app.db import get_db
from app.errors import not_found
from app.models import Communication, User
from app.schemas import CommunicationOut, CommUpdate
from app.services import communications

router = APIRouter(prefix="/communications", tags=["communications"])


def _load(db: Session, user: User, comm_id: str) -> Communication:
    comm = db.get(Communication, comm_id)
    if comm is None:
        raise not_found("Communication")
    if comm.case is not None:
        rbac.ensure_action(db, user, comm.case, "send_comm")
    elif user.role not in rbac.STAFF_ROLES:
        raise rbac.deny(db, user, "Only staff can manage management summaries")
    return comm


@router.patch("/{comm_id}", response_model=CommunicationOut)
def update(
    comm_id: str,
    body: CommUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommunicationOut:
    comm = _load(db, user, comm_id)
    communications.update(db, comm, body.subject, body.body, body.to, user)
    db.commit()
    return CommunicationOut.model_validate(comm)


@router.delete("/{comm_id}", status_code=204)
def discard(
    comm_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> None:
    comm = _load(db, user, comm_id)
    communications.discard(db, comm, user)
    db.commit()


@router.post("/{comm_id}/send", response_model=CommunicationOut)
def send(
    comm_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> CommunicationOut:
    comm = _load(db, user, comm_id)
    communications.send(db, comm, actor=user.email)
    db.commit()
    return CommunicationOut.model_validate(comm)
