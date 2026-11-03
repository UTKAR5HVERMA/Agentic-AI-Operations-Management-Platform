"""ValidationAgent (deterministic): missing fields, inventory conflicts, and the shared FACTS.

Critical fields missing → blocker (case goes to NEEDS_INFO). Important fields missing → warning.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.agents.common import Timer, agent_output, issue
from app.agents.state import CaseState
from app.enums import Category, FieldSource, IssueType, Severity
from app.normalize import region_for

AGENT = "validation"
INVENTORY_DOWN_CONF = 0.5
ASSUMED_STOCK_CONF = 0.75  # stock looked up in inventory but never stated by the requester

# category → (critical, important). Edge case 1 lists supplier/quantity/date/impact as gaps.
REQUIRED_FIELDS: dict[str, tuple[list[str], list[str]]] = {
    Category.DELIVERY_DELAY: (
        ["item", "quantity_required", "location"],
        ["supplier", "required_date", "delay_days"],
    ),
    Category.INVENTORY_SHORTAGE: (["item", "quantity_required", "location"], ["required_date"]),
    Category.SUPPLIER_ISSUE: (["supplier"], ["item", "cost_impact", "requested_action"]),
    Category.CUSTOMER_COMMITMENT: (["item", "quantity_required", "required_date"], ["location"]),
    Category.URGENT_APPROVAL: (["requested_action", "cost_impact"], ["approval_deadline"]),
    Category.OTHER: (["item", "location"], ["requested_action"]),
}
FIELD_LABELS = {
    "item": "item",
    "quantity_required": "quantity required",
    "quantity_available": "units on hand / available",
    "location": "location",
    "supplier": "supplier",
    "required_date": "required date",
    "delay_days": "delay (days)",
    "cost_impact": "cost / business impact",
    "requested_action": "expected action",
    "approval_deadline": "approval deadline",
    "original_delivery_date": "original / revised delivery date",
}
_PENALTY = re.compile(r"penalty[^.\n]*?₹\s?(\d[\d,]*)\s*per unit", re.IGNORECASE)


def required_fields(category: str) -> list[str]:
    critical, important = REQUIRED_FIELDS.get(category, REQUIRED_FIELDS[Category.OTHER])
    return critical + important


def _norm(fields: dict[str, dict[str, Any]], name: str) -> Any:
    f = fields.get(name)
    return f.get("normalized") if f else None


def _missing_issues(category: str, fields: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    critical, important = REQUIRED_FIELDS.get(category, REQUIRED_FIELDS[Category.OTHER])
    issues = []
    for name in critical + important:
        if fields.get(name, {}).get("value") is None:
            blocker = name in critical
            issues.append(
                issue(
                    AGENT,
                    IssueType.MISSING_INFO,
                    Severity.BLOCKER if blocker else Severity.WARNING,
                    f"Missing {FIELD_LABELS.get(name, name)}"
                    + (" — needed before any recommendation." if blocker else "."),
                    field=name,
                    details={"critical": blocker},
                )
            )
    if fields.get("item", {}).get("value") and _norm(fields, "item") is None:
        issues.append(
            issue(
                AGENT,
                IssueType.AMBIGUITY,
                Severity.WARNING,
                f"Item '{fields['item']['value']}' is not in the product catalog.",
                field="item",
            )
        )
    return issues


def _inventory_row(state: CaseState, sku: str | None, city: str | None) -> dict[str, Any] | None:
    if not sku or not city or state.get("inventory_snapshot") is None:
        return None
    location = f"{city}-WH"
    return next(
        (r for r in state["inventory_snapshot"] if r["sku"] == sku and r["location"] == location),
        None,
    )


def _assumed_stock_issue(row: dict[str, Any]) -> dict[str, Any]:
    return issue(
        AGENT,
        IssueType.AMBIGUITY,
        Severity.WARNING,
        f"The request does not say how many units are on hand. Inventory shows {row['free']} "
        f"free at {row['location']}; the shortfall assumes all of them can be used for this "
        f"request — confirm with the requester or correct the field.",
        field="quantity_available",
        details={
            "assumption": "inventory_stock_usable",
            "inventory_value": row["free"],
            "location": row["location"],
            "sku": row["sku"],
            "inventory_updated_at": row["updated_at"],
        },
    )


def _check_inventory(
    state: CaseState, fields: dict[str, dict[str, Any]]
) -> tuple[int | None, float, list[dict[str, Any]], list[str], str | None]:
    """Return (effective_available, data_conf, issues, degraded_reasons, available_source)."""
    email_value = _norm(fields, "quantity_available")
    avail_field = fields.get("quantity_available", {})
    email_source = "email" if email_value is not None else None
    if state.get("inventory_snapshot") is None:
        if email_value is not None:
            avail_field["confidence"] = INVENTORY_DOWN_CONF
        return (
            email_value,
            INVENTORY_DOWN_CONF,
            [
                issue(
                    AGENT,
                    IssueType.SYSTEM_UNAVAILABLE,
                    Severity.WARNING,
                    "Inventory system unavailable — using the quantity stated in the email "
                    "(unverified).",
                    details={"system": "inventory"},
                )
            ],
            ["inventory"],
            email_source,
        )

    row = _inventory_row(state, _norm(fields, "item"), _norm(fields, "location"))
    if row is None:
        return email_value, 1.0, [], [], email_source
    system_value = row["free"]
    if avail_field.get("source") == FieldSource.HUMAN:
        return email_value, 1.0, [], [], "human"  # a human already decided which value is right
    if email_value is None:
        # TRADE-OFF: we still use warehouse stock (it is real data), but flag it as an
        # assumption and lower data confidence instead of presenting it as a stated fact.
        return system_value, ASSUMED_STOCK_CONF, [_assumed_stock_issue(row)], [], "inventory"
    if email_value == system_value:
        return system_value, 1.0, [], [], "email"
    return (
        system_value,
        0.7,
        [
            issue(
                AGENT,
                IssueType.CONFLICT,
                Severity.WARNING,
                f"Email says {email_value} units available, inventory shows {system_value} at "
                f"{row['location']}.",
                field="quantity_available",
                details={
                    "email_value": email_value,
                    "inventory_value": system_value,
                    "location": row["location"],
                    "sku": row["sku"],
                    "inventory_updated_at": row["updated_at"],
                },
            )
        ],
        [],
        "inventory",
    )


def revised_eta(original_due: str | None, delay_days: Any) -> datetime | None:
    """When the delayed delivery now arrives: the original due date plus the delay."""
    if not original_due or not delay_days:
        return None
    return datetime.fromisoformat(original_due) + timedelta(days=float(delay_days))


def delay_vs_deadline(
    now: datetime, delay_days: Any, required_by: str | None, original_due: str | None = None
) -> str | None:
    """'meets' / 'misses' when the original due date is known (revised ETA vs required date).
    Without it: 'misses' if even a delivery due today plus the delay is late, else 'unclear'."""
    if not delay_days or not required_by:
        return None
    required = datetime.fromisoformat(required_by)
    if eta := revised_eta(original_due, delay_days):
        return "meets" if eta.date() <= required.date() else "misses"
    days_left = (required - now).total_seconds() / 86400
    return "misses" if float(delay_days) >= days_left else "unclear"


def _timing_issue(facts: dict[str, Any]) -> dict[str, Any]:
    required = datetime.fromisoformat(facts["required_by"]).strftime("%d %b")
    return issue(
        AGENT,
        IssueType.MISSING_INFO,
        Severity.WARNING,
        f"Delayed by {facts['delay_days']} days, needed by {required}: whether this misses the "
        f"date depends on the original delivery date, which the request does not give. Ask for "
        f"the revised delivery date before committing spend.",
        field="original_delivery_date",
        details={"delay_vs_deadline": "unclear", "required_by": facts["required_by"]},
    )


def build_facts(
    state: CaseState,
    fields: dict[str, dict[str, Any]],
    available: int | None,
    available_source: str | None = None,
) -> dict[str, Any]:
    now = datetime.fromisoformat(state["analysis_at"])
    required = _norm(fields, "quantity_required")
    shortfall = (
        max(required - available, 0) if required is not None and available is not None else None
    )
    deadlines = [
        datetime.fromisoformat(d["start"])
        for d in (_norm(fields, "approval_deadline"), _norm(fields, "required_date"))
        if d
    ]
    deadline = min(deadlines) if deadlines else None
    text = f"{state['subject']} {state.get('sanitized_text', '')}".lower()
    event = (fields.get("event", {}).get("value") or "").lower()
    penalty = _PENALTY.search(state.get("sanitized_text", ""))
    delay = _norm(fields, "delay_days")
    city = _norm(fields, "location")
    required_by = (_norm(fields, "required_date") or {}).get("end")
    original_due = (_norm(fields, "original_delivery_date") or {}).get("end")
    eta = revised_eta(original_due, delay)
    return {
        "category": state.get("category"),
        "sku": _norm(fields, "item"),
        "item": fields.get("item", {}).get("value"),
        "city": city,
        "region": region_for(city),
        "supplier": fields.get("supplier", {}).get("value"),
        "quantity_required": required,
        "quantity_available": available,
        # where quantity_available came from: email | inventory (system lookup, not stated) |
        # human (analyst correction) | None
        "available_source": available_source,
        "shortfall": shortfall,
        "shortfall_pct": round(shortfall / required, 4)
        if shortfall is not None and required
        else None,
        "delay_days": delay,
        "delay_vs_deadline": delay_vs_deadline(now, delay, required_by, original_due),
        "original_delivery_date": original_due,
        "revised_eta": eta.isoformat() if eta else None,
        "deadline_at": deadline.isoformat() if deadline else None,
        "hours_to_deadline": round((deadline - now).total_seconds() / 3600, 1)
        if deadline
        else None,
        "required_by": required_by,
        "event": event or None,
        "mentions_launch": "launch" in text or "opening" in text,
        "mentions_customer": "customer" in text or "client" in text,
        "mentions_penalty": "penalty" in text,
        "penalty_per_unit_day_inr": int(penalty.group(1).replace(",", "")) if penalty else None,
        "stated_cost_inr": _norm(fields, "cost_impact"),
    }


def validation_node(state: CaseState, config: RunnableConfig) -> dict[str, Any]:
    timer = Timer()
    fields = {k: dict(v) for k, v in state["fields"].items()}
    issues = _missing_issues(state["category"], fields)
    available, data_conf, inv_issues, degraded, available_source = _check_inventory(state, fields)
    issues += inv_issues
    facts = build_facts(state, fields, available, available_source)
    if facts["delay_vs_deadline"] == "unclear":
        issues.append(_timing_issue(facts))
    out = {
        "fields": fields,
        "facts": facts,
        "data_conf": data_conf,
        **agent_output(
            AGENT,
            timer,
            action="validation.completed",
            after={"issues": [i["key"] for i in issues], "data_conf": data_conf},
            issues=issues,
        ),
    }
    if degraded:
        out["degraded_reasons"] = degraded
    if any(i["type"] == IssueType.MISSING_INFO for i in issues):
        out["audit_events"].append(
            {
                "action": "validation.missing_fields",
                "actor": AGENT,
                "after": [i["field"] for i in issues if i["type"] == IssueType.MISSING_INFO],
            }
        )
    if inv_issues and inv_issues[0]["type"] == IssueType.CONFLICT:
        out["audit_events"].append(
            {"action": "validation.conflict", "actor": AGENT, "after": inv_issues[0]["details"]}
        )
    return out
