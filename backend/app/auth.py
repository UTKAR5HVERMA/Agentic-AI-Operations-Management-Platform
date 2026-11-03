"""Password hashing (PBKDF2-SHA256), JWT issuing/verification and the current-user dependency."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import timedelta

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db, utcnow
from app.errors import ApiError
from app.models import User

PBKDF2_ITERATIONS = 240_000
_ALGORITHM = "HS256"
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    encoded_salt = base64.b64encode(salt).decode()
    encoded_digest = base64.b64encode(digest).decode()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${encoded_salt}${encoded_digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt_b64, digest_b64 = stored.split("$")
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), base64.b64decode(salt_b64), int(iterations)
    )
    return hmac.compare_digest(digest, base64.b64decode(digest_b64))


def create_access_token(user: User) -> str:
    settings = get_settings()
    now = utcnow()
    claims = {
        "sub": user.id,
        "role": user.role,
        "region": user.region,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=_ALGORITHM)


def _unauthorized(detail: str) -> ApiError:
    error = ApiError(401, "UNAUTHORIZED", detail)
    error.headers = {"WWW-Authenticate": "Bearer"}
    return error


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise _unauthorized("Not authenticated")
    try:
        claims = jwt.decode(
            credentials.credentials, get_settings().jwt_secret, algorithms=[_ALGORITHM]
        )
    except jwt.ExpiredSignatureError as exc:
        raise _unauthorized("Session expired, please log in again") from exc
    except jwt.InvalidTokenError as exc:
        raise _unauthorized("Invalid token") from exc
    user = db.get(User, claims.get("sub"))
    if user is None:
        raise _unauthorized("User no longer exists")
    return user
