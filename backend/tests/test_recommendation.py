"""RecommendationAgent merge: the LLM writes the rationale; title and sources come from data."""

from __future__ import annotations

from typing import Any

from app.agents.recommendation import OptionOut, RecommendationOut, _merge_llm

SUPPLIERS = [{"name": "ShelfMart"}, {"name": "RackWorks"}]
BASE = {
    "kind": "expedite",
    "title": "Expedite 150 units from RackWorks (12-day lead)",
    "description": "Order 150 units of RACK-SH from RackWorks on express terms.",
    "estimated_cost_inr": 48_000,
    "estimated_lead_time_days": 12,
    "coverage": 1.0,
    "evidence": ["supplier.RackWorks"],
    "allocations": [],
    "base_confidence": 0.7,
}


def _state(late_supplier: str | None) -> dict[str, Any]:
    return {
        "suppliers": SUPPLIERS,
        "inventory_snapshot": [{"location": "Mumbai-WH", "sku": "RACK-SH", "free": 150}],
        "facts": {"supplier": late_supplier},
        "excluded_kinds": [],
    }


def _llm(title: str, rationale: str) -> RecommendationOut:
    option = OptionOut(
        kind="expedite",
        title=title,
        description="x",
        estimated_cost_inr=1,
        estimated_lead_time_days=1,
        rationale=rationale,
        evidence=["supplier.RackWorks"],
    )
    return RecommendationOut(options=[option])


def test_llm_cannot_rename_the_costed_supplier() -> None:
    out = _llm("Expedite 150 racks from ShelfMart", "Fast and reliable.")
    merged, discarded = _merge_llm(out, [dict(BASE)], _state("ShelfMart"))
    assert merged[0]["title"] == BASE["title"]
    assert merged[0]["rationale"] == "Fast and reliable." and not discarded


def test_rationale_naming_another_supplier_is_dropped() -> None:
    out = _llm("Expedite", "ShelfMart is cheapest and fastest.")
    merged, discarded = _merge_llm(out, [dict(BASE)], _state(None))
    assert merged[0]["rationale"] == ""  # recommendation_node falls back to a data rationale
    assert "ShelfMart" in discarded[0]["reason"]


def test_rationale_may_mention_the_late_supplier() -> None:
    out = _llm("Expedite", "Replaces the delayed ShelfMart delivery.")
    merged, discarded = _merge_llm(out, [dict(BASE)], _state("ShelfMart"))
    assert merged[0]["rationale"].startswith("Replaces") and not discarded
