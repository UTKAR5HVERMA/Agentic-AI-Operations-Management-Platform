"""Mock email/notification sender. Fails while the email_down fault flag is on (edge case 13)."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app import faults
from app.enums import Flag
from app.models import Communication


class DeliveryError(Exception):
    pass


def deliver(db: Session, comm: Communication) -> str:
    """Return a provider message id, or raise DeliveryError."""
    if faults.is_down(db, Flag.EMAIL_DOWN):
        raise DeliveryError("Email service unavailable (SMTP connection refused)")
    if not comm.to:
        raise DeliveryError("No recipients")
    return f"mock-{uuid.uuid4().hex[:12]}"
