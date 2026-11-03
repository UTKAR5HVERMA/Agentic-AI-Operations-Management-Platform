"""CaseState — the single shared context all agents read and write (BACKEND.md §7.1).

Keys written by parallel branches use reducers (lists are appended, dicts merged) so agents
return only their own partial update.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


def merge_dicts(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {**left, **right}


class CaseState(TypedDict, total=False):
    # Inputs (prepared by services/analysis.py — agents never touch the DB)
    request_id: str
    ref: str
    start_at: str  # "intake" | "validation"
    sender_email: str | None
    sender_name: str | None
    subject: str
    raw_text: str
    channel: str
    received_at: str
    analysis_at: str
    category_hint: str | None
    locked_fields: dict[str, dict[str, Any]]  # human/event-sourced fields: never overwritten
    inventory_snapshot: list[dict[str, Any]] | None  # None = inventory system unavailable
    suppliers: list[dict[str, Any]]
    catalog: dict[str, str]
    open_cases: list[dict[str, Any]]
    excluded_kinds: list[str]
    suppressed_issue_keys: list[str]
    dedup_dismissed: bool

    # Produced by agents
    sanitized_text: str
    injection: dict[str, Any]
    category: str
    requested_actions: list[str]
    sub_requests: list[dict[str, Any]]
    fields: dict[str, dict[str, Any]]
    facts: dict[str, Any]
    data_conf: float
    duplicates: list[dict[str, Any]]
    risk: Annotated[dict[str, Any], merge_dicts]
    recommendations: list[dict[str, Any]]
    drafts: list[dict[str, Any]]
    confidence: float
    confidence_breakdown: dict[str, float]
    outcome: str  # "duplicate" | "needs_info" | "pending_review"
    issues: Annotated[list[dict[str, Any]], operator.add]
    degraded_reasons: Annotated[list[str], operator.add]
    trace: Annotated[list[dict[str, Any]], operator.add]
    audit_events: Annotated[list[dict[str, Any]], operator.add]
