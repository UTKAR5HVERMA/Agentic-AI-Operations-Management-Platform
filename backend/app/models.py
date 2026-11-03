"""SQLAlchemy models (BACKEND.md §5). Enum-valued columns are plain strings from app.enums."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UTCDateTime, utcnow
from app.enums import (
    ApprovalStatus,
    CommStatus,
    IssueStatus,
    Priority,
    RecStatus,
    Status,
)


def new_id() -> str:
    return str(uuid.uuid4())


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32))
    region: Mapped[str] = mapped_column(String(32))
    approval_limit_inr: Mapped[int] = mapped_column(Integer, default=0)


class Case(TimestampMixin, Base):
    """An operational request ("case"). Table name follows the spec: `requests`."""

    __tablename__ = "requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    ref: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    channel: Mapped[str] = mapped_column(String(16))
    subject: Mapped[str] = mapped_column(String(300))
    raw_text: Mapped[str] = mapped_column(Text)
    sender_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sender_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    sanitized_text: Mapped[str] = mapped_column(Text, default="")
    injection_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    injection_details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    status: Mapped[str] = mapped_column(String(24), default=Status.NEW, index=True)
    previous_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    priority: Mapped[str] = mapped_column(String(4), default=Priority.P3)
    category: Mapped[str] = mapped_column(String(32), default="other")
    deadline_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    sla_due_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    sla_breached: Mapped[bool] = mapped_column(Boolean, default=False)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    overall_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_breakdown: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)
    degraded_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    agent_trace: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    sub_requests: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    duplicate_candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    dedup_dismissed: Mapped[bool] = mapped_column(Boolean, default=False)

    duplicate_of_id: Mapped[str | None] = mapped_column(ForeignKey("requests.id"), nullable=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("requests.id"), nullable=True)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    region: Mapped[str] = mapped_column(String(32), default="West")
    version: Mapped[int] = mapped_column(Integer, default=1)

    owner: Mapped[User | None] = relationship(foreign_keys=[owner_id])
    fields: Mapped[list[ExtractedField]] = relationship(
        back_populates="case", order_by="ExtractedField.created_at"
    )
    issues: Mapped[list[Issue]] = relationship(back_populates="case", order_by="Issue.created_at")
    risk_assessments: Mapped[list[RiskAssessment]] = relationship(
        back_populates="case", order_by="RiskAssessment.created_at"
    )
    recommendations: Mapped[list[Recommendation]] = relationship(
        back_populates="case", order_by="Recommendation.created_at"
    )
    approvals: Mapped[list[Approval]] = relationship(
        back_populates="case", order_by="Approval.created_at"
    )
    communications: Mapped[list[Communication]] = relationship(
        back_populates="case", order_by="Communication.created_at"
    )
    events: Mapped[list[Event]] = relationship(back_populates="case", order_by="Event.created_at")


class ExtractedField(TimestampMixin, Base):
    """Corrections never overwrite: a new row is inserted and the old one gets is_current=False."""

    __tablename__ = "extracted_fields"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    request_id: Mapped[str] = mapped_column(ForeignKey("requests.id"), index=True)
    field: Mapped[str] = mapped_column(String(32))
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_value: Mapped[Any] = mapped_column(JSON, nullable=True)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(16))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    corrected_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    correction_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    case: Mapped[Case] = relationship(back_populates="fields")
    corrected_by: Mapped[User | None] = relationship()


class Issue(TimestampMixin, Base):
    __tablename__ = "issues"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    request_id: Mapped[str] = mapped_column(ForeignKey("requests.id"), index=True)
    key: Mapped[str] = mapped_column(String(80))
    agent: Mapped[str] = mapped_column(String(32))
    type: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(16))
    field: Mapped[str | None] = mapped_column(String(32), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default=IssueStatus.OPEN)
    resolved_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    case: Mapped[Case] = relationship(back_populates="issues")


class RiskAssessment(TimestampMixin, Base):
    __tablename__ = "risk_assessments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    request_id: Mapped[str] = mapped_column(ForeignKey("requests.id"), index=True)
    agent: Mapped[str] = mapped_column(String(32))
    urgency: Mapped[int] = mapped_column(Integer)
    impact: Mapped[int] = mapped_column(Integer)
    risk_level: Mapped[str] = mapped_column(String(16))
    score: Mapped[float] = mapped_column(Float)
    rationale: Mapped[str] = mapped_column(Text)
    factors: Mapped[list[str]] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float)
    model: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)

    case: Mapped[Case] = relationship(back_populates="risk_assessments")


class Recommendation(TimestampMixin, Base):
    __tablename__ = "recommendations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    request_id: Mapped[str] = mapped_column(ForeignKey("requests.id"), index=True)
    rank: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32), default="custom")
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text, default="")
    estimated_cost_inr: Mapped[int] = mapped_column(Integer, default=0)
    estimated_lead_time_days: Mapped[float] = mapped_column(Float, default=0)
    risk_reduction: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence: Mapped[list[str]] = mapped_column(JSON, default=list)
    allocations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    approval_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    approvers: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default=RecStatus.PROPOSED)
    created_by: Mapped[str] = mapped_column(String(16), default="agent")
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(String(64), default="fallback")

    case: Mapped[Case] = relationship(back_populates="recommendations")


class Approval(TimestampMixin, Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    request_id: Mapped[str] = mapped_column(ForeignKey("requests.id"), index=True)
    recommendation_id: Mapped[str] = mapped_column(ForeignKey("recommendations.id"))
    approver_role: Mapped[str] = mapped_column(String(32))
    # financial = carries spend authority (limit applies); operational = sign-off only.
    kind: Mapped[str] = mapped_column(String(16), default="financial")
    approver_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    # Chosen by the Operations Team when routing; None = any holder of approver_role.
    assigned_to_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    amount_inr: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default=ApprovalStatus.PENDING, index=True)
    due_at: Mapped[datetime] = mapped_column(UTCDateTime)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    escalation_level: Mapped[int] = mapped_column(Integer, default=0)
    escalated_to_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    # The Operations Team's note to the approver, sent along with the original request.
    routing_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The Director approved their own request with a written justification (top of the chain).
    self_approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # AI advice for the approver (suggestion, rationale, checks, model). Advice only.
    advice: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    stale_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    deadline_alerted: Mapped[bool] = mapped_column(Boolean, default=False)

    case: Mapped[Case] = relationship(back_populates="approvals")
    recommendation: Mapped[Recommendation] = relationship()
    approver: Mapped[User | None] = relationship(foreign_keys=[approver_id])
    assigned_to: Mapped[User | None] = relationship(foreign_keys=[assigned_to_id])


class Communication(TimestampMixin, Base):
    __tablename__ = "communications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    request_id: Mapped[str | None] = mapped_column(
        ForeignKey("requests.id"), index=True, nullable=True
    )
    type: Mapped[str] = mapped_column(String(32))
    to: Mapped[list[str]] = mapped_column(JSON, default=list)
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default=CommStatus.DRAFT)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    delivered_via: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_by: Mapped[str] = mapped_column(String(16), default="agent")
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    model: Mapped[str] = mapped_column(String(64), default="template")

    case: Mapped[Case | None] = relationship(back_populates="communications")


class Event(TimestampMixin, Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    request_id: Mapped[str] = mapped_column(ForeignKey("requests.id"), index=True)
    type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    diff: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    case: Mapped[Case] = relationship(back_populates="events")


class AuditLog(Base):
    """Append-only, hash-chained. There is no update or delete code path for this table."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    actor_type: Mapped[str] = mapped_column(String(16))
    actor: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(64), index=True)
    before: Mapped[Any] = mapped_column(JSON, nullable=True)
    after: Mapped[Any] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class InventoryItem(Base):
    __tablename__ = "inventory"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    sku: Mapped[str] = mapped_column(String(32), index=True)
    item_name: Mapped[str] = mapped_column(String(120))
    location: Mapped[str] = mapped_column(String(64))
    on_hand: Mapped[int] = mapped_column(Integer)
    reserved: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    @property
    def free(self) -> int:
        return max(self.on_hand - self.reserved, 0)


class Supplier(TimestampMixin, Base):
    __tablename__ = "suppliers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    items: Mapped[list[str]] = mapped_column(JSON, default=list)
    lead_time_days: Mapped[int] = mapped_column(Integer)
    reliability_score: Mapped[float] = mapped_column(Float)
    express_cost_per_unit_inr: Mapped[int] = mapped_column(Integer)
    contact_email: Mapped[str] = mapped_column(String(255))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)


class SystemFlag(Base):
    __tablename__ = "system_flags"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Counter(Base):
    """Monotonic counters (e.g. case reference numbers) that survive concurrent inserts."""

    __tablename__ = "counters"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)
