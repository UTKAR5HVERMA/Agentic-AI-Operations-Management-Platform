"""Deterministic, costed candidate options built only from real inventory and supplier data.

The RecommendationAgent (LLM) may re-rank and re-word these, but costs, lead times and
allocations always come from here, so the LLM cannot invent numbers or sources.
"""

from __future__ import annotations

from typing import Any

from app.normalize import region_for

# TRADE-OFF: flat logistics rates; a real system would price per lane from a TMS.
TRANSFER_COST_PER_UNIT_INR = 100
TRANSFER_LEAD_DAYS_SAME_REGION = 2
TRANSFER_LEAD_DAYS_CROSS_REGION = 4


def _warehouse_region(location: str) -> str | None:
    return region_for(location.removesuffix("-WH"))


def transfer_option(
    facts: dict[str, Any], inventory: list[dict[str, Any]]
) -> dict[str, Any] | None:
    sku, city, need = facts["sku"], facts["city"], facts["shortfall"]
    target = f"{city}-WH"
    sources = [
        r for r in inventory if r["sku"] == sku and r["location"] != target and r["free"] > 0
    ]
    region = facts.get("region")
    sources.sort(key=lambda r: (_warehouse_region(r["location"]) != region, -r["free"]))
    allocations, remaining = [], need
    for row in sources:
        if remaining <= 0:
            break
        units = min(row["free"], remaining)
        allocations.append({"location": row["location"], "sku": sku, "units": units})
        remaining -= units
    if not allocations:
        return None
    moved = need - remaining
    cross = any(_warehouse_region(a["location"]) != region for a in allocations)
    parts = ", ".join(f"{a['location']} ({a['units']})" for a in allocations)
    cost = moved * TRANSFER_COST_PER_UNIT_INR
    return {
        "kind": "transfer",
        "title": f"Transfer {moved} units from {parts}",
        "description": f"Move {moved} units of {sku} to {target}. Cost: {moved} units × "
        f"₹{TRANSFER_COST_PER_UNIT_INR}/unit transfer = ₹{cost:,}.",
        "estimated_cost_inr": cost,
        "estimated_lead_time_days": TRANSFER_LEAD_DAYS_CROSS_REGION
        if cross
        else TRANSFER_LEAD_DAYS_SAME_REGION,
        "coverage": round(moved / need, 4),
        "risk_reduction": f"Covers {moved / need:.0%} of the {need}-unit shortfall.",
        "evidence": [f"inventory.{a['location']}" for a in allocations],
        "allocations": allocations,
        "base_confidence": 0.9 if moved >= need else 0.6 + 0.3 * moved / need,
    }


def expedite_option(
    facts: dict[str, Any], suppliers: list[dict[str, Any]]
) -> dict[str, Any] | None:
    sku, need = facts["sku"], facts["shortfall"]
    named = (facts.get("supplier") or "").lower()
    candidates = [
        s
        for s in suppliers
        if sku in s["items"]
        and s["name"].lower() not in named
        and not (not named and s["is_primary"])  # unnamed supplier → assume the primary is late
    ]
    if not candidates:
        return None
    best = min(candidates, key=lambda s: (s["express_cost_per_unit_inr"], s["lead_time_days"]))
    cost = need * best["express_cost_per_unit_inr"]
    return {
        "kind": "expedite",
        "title": f"Expedite {need} units from {best['name']} ({best['lead_time_days']}-day lead)",
        "description": f"Order {need} units of {sku} from {best['name']} on express terms. "
        f"Cost: {need} × ₹{best['express_cost_per_unit_inr']}/unit = ₹{cost:,}.",
        "estimated_cost_inr": cost,
        "estimated_lead_time_days": best["lead_time_days"],
        "coverage": 1.0,
        "risk_reduction": f"Covers the full shortfall; supplier reliability "
        f"{best['reliability_score']:.0%}.",
        "evidence": [f"supplier.{best['name']}"],
        "allocations": [],
        "base_confidence": 0.85 * best["reliability_score"] + 0.1,
    }


def zero_cost_options(facts: dict[str, Any]) -> list[dict[str, Any]]:
    need, have = facts.get("shortfall"), facts.get("quantity_available")
    supplier = facts.get("supplier") or "the primary supplier"
    options = []
    if need and have is not None:
        options.append(
            {
                "kind": "partial",
                "title": f"Proceed with the {have} units on hand; defer the remaining {need}",
                "description": "No additional spend. Launch/fulfil partially and complete when the "
                "delayed delivery arrives.",
                "estimated_cost_inr": 0,
                "estimated_lead_time_days": 0,
                "coverage": 0.0,
                "risk_reduction": "Avoids cost; leaves the shortfall open.",
                "evidence": ["facts.quantity_available"],
                "allocations": [],
                "base_confidence": 0.7,
            }
        )
    options.append(
        {
            "kind": "negotiate",
            "title": f"Ask {supplier} for a partial early shipment",
            "description": "Request a split delivery of the most critical quantity at no extra "
            "cost; escalate the delay through the supplier account manager.",
            "estimated_cost_inr": 0,
            "estimated_lead_time_days": max((facts.get("delay_days") or 3) - 2, 1),
            "coverage": 0.0,
            "risk_reduction": "Uncertain — depends on supplier response.",
            "evidence": ["facts.supplier"] if facts.get("supplier") else ["facts.delay_days"],
            "allocations": [],
            "base_confidence": 0.5,
        }
    )
    return options


def build_candidates(
    facts: dict[str, Any],
    inventory: list[dict[str, Any]] | None,
    suppliers: list[dict[str, Any]],
    excluded_kinds: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Ranked candidate options. Zero-cost options are always present."""
    excluded = set(excluded_kinds or [])
    paid: list[dict[str, Any]] = []
    if facts.get("sku") and facts.get("shortfall"):
        if inventory is not None and facts.get("city"):
            paid.append(transfer_option(facts, inventory))
        paid.append(expedite_option(facts, suppliers))
    options = [o for o in paid if o] + zero_cost_options(facts)
    options = [o for o in options if o["kind"] not in excluded]
    if excluded:  # after a rejection, highlight no-cost alternatives first (edge case 8)
        options.sort(key=lambda o: (o["estimated_cost_inr"] > 0, -o["base_confidence"]))
    else:  # full cover first, then more coverage, then faster, then cheaper
        options.sort(
            key=lambda o: (
                o["coverage"] < 0.999,
                -o["coverage"],
                o["estimated_lead_time_days"],
                o["estimated_cost_inr"],
            )
        )
    return options


def cheapest_full_cover_cost(options: list[dict[str, Any]]) -> int | None:
    full = [o["estimated_cost_inr"] for o in options if o["coverage"] >= 0.999]
    return min(full) if full else None
