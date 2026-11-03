"""String enums shared by models, schemas, agents and the frontend contract (BACKEND.md §5, §6)."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    REQUESTER = "requester"
    OPS_ANALYST = "ops_analyst"  # central triage desk: reviews AI output, routes for approval
    OPS_MANAGER = "ops_manager"  # regional decision-maker: approves, holds, cancels
    ADMIN = "admin"


class Status(StrEnum):
    NEW = "NEW"
    ANALYZING = "ANALYZING"
    NEEDS_INFO = "NEEDS_INFO"
    PENDING_REVIEW = "PENDING_REVIEW"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ESCALATED = "ESCALATED"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    DUPLICATE = "DUPLICATE"
    ON_HOLD = "ON_HOLD"
    CANCELLED = "CANCELLED"


class Channel(StrEnum):
    EMAIL = "email"
    MANUAL = "manual"
    WHATSAPP = "whatsapp"
    PHONE = "phone"


class Category(StrEnum):
    DELIVERY_DELAY = "delivery_delay"
    INVENTORY_SHORTAGE = "inventory_shortage"
    SUPPLIER_ISSUE = "supplier_issue"
    URGENT_APPROVAL = "urgent_approval"
    CUSTOMER_COMMITMENT = "customer_commitment"
    OTHER = "other"


class Priority(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class FieldName(StrEnum):
    SUPPLIER = "supplier"
    ITEM = "item"
    QUANTITY_REQUIRED = "quantity_required"
    QUANTITY_AVAILABLE = "quantity_available"
    LOCATION = "location"
    REQUIRED_DATE = "required_date"
    DELAY_DAYS = "delay_days"
    EVENT = "event"
    COST_IMPACT = "cost_impact"
    REQUESTED_ACTION = "requested_action"
    APPROVAL_DEADLINE = "approval_deadline"
    ORIGINAL_DELIVERY_DATE = "original_delivery_date"  # when the delayed delivery was first due


class FieldSource(StrEnum):
    LLM = "llm"
    FALLBACK = "fallback"
    HUMAN = "human"
    EVENT = "event"


class IssueType(StrEnum):
    MISSING_INFO = "missing_info"
    CONFLICT = "conflict"
    AMBIGUITY = "ambiguity"
    INJECTION = "injection"
    DUPLICATE = "duplicate"
    LOW_CONFIDENCE = "low_confidence"
    SYSTEM_UNAVAILABLE = "system_unavailable"
    AGENT_DISAGREEMENT = "agent_disagreement"
    COMMUNICATION_FAILURE = "communication_failure"
    CIRCUMSTANCES_CHANGED = "circumstances_changed"
    DEADLINE_MISSED = "deadline_missed"
    OUT_OF_BOUNDS = "out_of_bounds"
    EXTRACTION_FLAGGED = "extraction_flagged"  # a human marked an extracted value as wrong


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    BLOCKER = "blocker"


class IssueStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


RISK_ORDER: list[RiskLevel] = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]


class RiskAgentName(StrEnum):
    OPS = "ops_risk"
    FINANCIAL = "financial_risk"
    RECONCILED = "reconciled"


class RecStatus(StrEnum):
    PROPOSED = "proposed"
    SELECTED = "selected"
    OVERRIDDEN = "overridden"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


IN_FLIGHT_APPROVALS = {ApprovalStatus.PENDING, ApprovalStatus.ESCALATED}


class CommType(StrEnum):
    STAKEHOLDER_UPDATE = "stakeholder_update"
    APPROVAL_REQUEST = "approval_request"
    ESCALATION = "escalation"
    CLOSURE = "closure"
    MANAGEMENT_SUMMARY = "management_summary"
    CLARIFICATION = "clarification"
    CANCELLATION = "cancellation"
    DUPLICATE_NOTICE = "duplicate_notice"
    REMINDER = "reminder"
    REQUESTER_REPLY = "requester_reply"  # inbound: the requester answered the team in-app


class CommStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"
    DISCARDED = "discarded"  # unsent draft deleted by a human; hidden, kept for the audit trail


class ActorType(StrEnum):
    AGENT = "agent"
    HUMAN = "human"
    SYSTEM = "system"


class EventType(StrEnum):
    SUPPLIER_DATE_REVISED = "supplier_date_revised"
    LAUNCH_POSTPONED = "launch_postponed"
    INVENTORY_UPDATED = "inventory_updated"
    STAKEHOLDER_REPLY = "stakeholder_reply"


class Flag(StrEnum):
    LLM_DOWN = "llm_down"
    INVENTORY_DOWN = "inventory_down"
    EMAIL_DOWN = "email_down"
