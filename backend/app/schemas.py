"""Pydantic API models (BACKEND.md §8). ORM objects are never returned directly."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.enums import Channel, CommType, EventType, FieldName, Status

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- auth
class LoginRequest(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(max_length=128)


class UserOut(ApiModel):
    id: str
    name: str
    email: str
    role: str
    region: str
    approval_limit_inr: int


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class UserRef(BaseModel):
    id: str
    name: str


class ApproverOut(ApiModel):
    id: str
    name: str
    region: str
    approval_limit_inr: int


# ---------------------------------------------------------------- inputs
class Versioned(BaseModel):
    version: int | None = Field(default=None, description="Optimistic lock: current case version")


class CreateRequest(BaseModel):
    channel: Channel = Channel.MANUAL
    subject: str = Field(min_length=1, max_length=300)
    raw_text: str = Field(min_length=1, max_length=20_000)
    sender_email: str | None = Field(default=None, max_length=255, pattern=EMAIL_PATTERN)
    sender_name: str | None = Field(default=None, max_length=120)
    received_at: datetime | None = None


class ComposeRequest(BaseModel):
    subject: str | None = Field(default=None, max_length=300)
    sender_name: str | None = Field(default=None, max_length=120)  # who signs the email
    text: str = Field(min_length=3, max_length=20_000)


class ComposeReply(BaseModel):
    text: str = Field(min_length=2, max_length=20_000)


class ComposedEmailOut(BaseModel):
    subject: str
    body: str
    model: str
    note: str | None


class FieldCorrection(Versioned):
    field: FieldName
    value: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=5, max_length=1000)


class FieldFlag(Versioned):
    field: FieldName
    reason: str = Field(min_length=5, max_length=1000)


class ProvideInfo(Versioned):
    text: str = Field(min_length=1, max_length=20_000)


class IssueResolution(Versioned):
    resolution: Literal["use_inventory", "use_email", "custom", "dismiss", "resolved"]
    value: str | None = Field(default=None, max_length=500)
    note: str = Field(min_length=3, max_length=1000)


class SelectRecommendation(Versioned):
    note: str | None = Field(default=None, max_length=1000)
    approver_id: str | None = None  # Regional Manager chosen by the Operations Team


class OverrideRecommendation(Versioned):
    approver_id: str | None = None  # Regional Manager chosen by the Operations Team
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=3, max_length=2000)
    estimated_cost_inr: int = Field(ge=0, le=100_000_000)
    estimated_lead_time_days: float = Field(default=0, ge=0, le=365)
    reason: str = Field(min_length=5, max_length=1000)


class DuplicateLink(Versioned):
    master_id: str


class TransitionRequest(Versioned):
    to: Status
    reason: str | None = Field(default=None, max_length=1000)


class ReasonRequest(Versioned):
    reason: str = Field(min_length=5, max_length=1000)


class EventIn(Versioned):
    type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)


class ApprovalDecision(BaseModel):
    note: str | None = Field(default=None, max_length=1000)
    reconfirm: bool = False
    # Director only: approve a request they raised themselves; `note` becomes the justification.
    self_override: bool = False


class CommUpdate(BaseModel):
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=10_000)
    to: list[str] | None = Field(default=None, max_length=20)


class GenerateComm(BaseModel):
    type: CommType


class FlagsUpdate(BaseModel):
    llm_down: bool | None = None
    inventory_down: bool | None = None
    email_down: bool | None = None


# ---------------------------------------------------------------- outputs
class FieldHistory(BaseModel):
    value: str | None
    source: str
    confidence: float
    corrected_by: str | None
    correction_reason: str | None
    created_at: datetime


class ExtractedFieldOut(BaseModel):
    field: str
    value: str | None
    normalized_value: Any
    evidence: str | None
    confidence: float
    source: str
    corrected_by: str | None
    correction_reason: str | None
    flagged: bool = False  # an open "extraction_flagged" issue exists for this field
    flag_reason: str | None = None
    history: list[FieldHistory]


class IssueOut(ApiModel):
    id: str
    type: str
    severity: str
    field: str | None
    message: str
    details: dict[str, Any]
    status: str
    resolution_note: str | None
    created_at: datetime


class RiskOut(ApiModel):
    agent: str
    urgency: int
    impact: int
    risk_level: str
    score: float
    rationale: str
    factors: list[str]
    confidence: float
    model: str
    disagreement: bool = False


class RecommendationOut(ApiModel):
    id: str
    rank: int
    kind: str
    title: str
    description: str
    rationale: str
    estimated_cost_inr: int
    estimated_lead_time_days: float
    risk_reduction: str
    confidence: float
    evidence: list[str]
    allocations: list[dict[str, Any]]
    requires_approval: bool
    approval_reasons: list[str]
    approvers: list[str]
    status: str
    created_by: str
    override_reason: str | None
    model: str


class ApprovalOut(BaseModel):
    id: str
    request_id: str
    request_ref: str
    request_subject: str
    recommendation_id: str
    recommendation_title: str
    approver_role: str
    kind: str
    approver: UserRef | None
    assigned_to: UserRef | None
    amount_inr: int
    status: str
    due_at: datetime
    decided_at: datetime | None
    decision_note: str | None
    escalation_level: int
    reasons: list[str]
    routing_note: str | None
    self_approved: bool = False
    needs_self_override: bool = False  # the Director raised it: approve only with a justification
    stale: bool
    stale_reason: str | None
    risk_level: str | None
    requested_by: str | None
    can_decide: bool
    created_at: datetime


class CommunicationOut(ApiModel):
    id: str
    request_id: str | None
    type: str
    to: list[str]
    subject: str
    body: str
    status: str
    attempts: int
    last_error: str | None
    next_retry_at: datetime | None
    sent_at: datetime | None
    delivered_via: str | None
    created_by: str
    edited: bool
    model: str
    created_at: datetime


class EventOut(ApiModel):
    id: str
    type: str
    payload: dict[str, Any]
    diff: dict[str, Any]
    processed: bool
    created_by: str | None
    created_at: datetime


class CaseRef(BaseModel):
    id: str
    ref: str
    status: str
    subject: str


class DuplicateOut(BaseModel):
    id: str
    ref: str
    similarity: float


class Sender(BaseModel):
    name: str | None
    email: str | None


class RequestSummary(BaseModel):
    id: str
    ref: str
    subject: str
    status: str
    priority: str
    category: str
    channel: str
    sender: Sender
    region: str
    risk_level: str | None
    overall_confidence: float
    degraded: bool
    injection_flag: bool
    open_issues: int
    pending_approvals: int
    awaiting_role: str | None  # approver role of the in-flight approval, for status labels
    deadline_at: datetime | None
    sla_due_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RequestDetail(RequestSummary):
    raw_text: str
    sanitized_text: str
    received_at: datetime
    closed_at: datetime | None
    previous_status: str | None
    confidence_breakdown: dict[str, float]
    confidence_band: str
    degraded_reasons: list[str]
    version: int
    injection: dict[str, Any]
    fields: list[ExtractedFieldOut]
    missing_fields: list[str]
    issues: list[IssueOut]
    risk: dict[str, RiskOut | None]
    recommendations: list[RecommendationOut]
    approvals: list[ApprovalOut]
    communications: list[CommunicationOut]
    events: list[EventOut]
    duplicates: list[DuplicateOut]
    duplicate_of: CaseRef | None
    parent: CaseRef | None
    children: list[CaseRef]
    sub_requests: list[dict[str, Any]]
    agent_trace: list[dict[str, Any]]
    allowed_actions: list[str]


class AuditOut(ApiModel):
    id: int
    request_id: str | None
    request_ref: str | None = None
    actor_type: str
    actor: str
    action: str
    before: Any
    after: Any
    confidence: float | None
    model: str | None
    prompt_hash: str | None
    latency_ms: int | None
    tokens: int | None
    reason: str | None
    ip: str | None
    created_at: datetime
    hash: str


class AuditVerify(BaseModel):
    valid: bool
    rows: int
    broken_at_id: int | None


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    llm: Literal["up", "down", "fallback"]
    inventory: Literal["up", "down"]
    email: Literal["up", "down"]
    db: Literal["up", "down"]
    llm_mode: str
    model: str


class Flags(BaseModel):
    llm_down: bool
    inventory_down: bool
    email_down: bool


class ManagementSummary(BaseModel):
    markdown: str
    metrics: dict[str, Any]
    generated_at: datetime
    model: str
    communication_id: str


class Sample(BaseModel):
    id: str
    label: str
    channel: str
    subject: str
    raw_text: str
    sender_email: str | None
    sender_name: str | None
    edge_cases: list[int]


class InventoryOut(ApiModel):
    sku: str
    item_name: str
    location: str
    on_hand: int
    reserved: int
    free: int
    updated_at: datetime


class SupplierOut(ApiModel):
    name: str
    items: list[str]
    lead_time_days: int
    reliability_score: float
    express_cost_per_unit_inr: int
    contact_email: str
    is_primary: bool


class TickResult(BaseModel):
    reminders: int
    escalations: int
    deadline_alerts: int
    retries: int
    reanalyzed: int
    sla_breaches: int
