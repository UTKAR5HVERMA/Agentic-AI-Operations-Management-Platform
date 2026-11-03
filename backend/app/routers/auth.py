from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.auth import create_access_token, get_current_user, verify_password
from app.db import get_db
from app.enums import ActorType
from app.errors import ApiError
from app.models import User
from app.schemas import LoginRequest, LoginResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.strip().lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        audit.log_event(
            db, action="auth.login_failed", actor=body.email[:255], actor_type=ActorType.SYSTEM
        )
        db.commit()
        raise ApiError(401, "INVALID_CREDENTIALS", "Invalid email or password")
    audit.log_event(db, action="auth.login", actor=user.email)
    db.commit()
    return LoginResponse(access_token=create_access_token(user), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)
