"""RecommendationAgent: 2–4 ranked options with cost, lead time, rationale, evidence, confidence.

Unsupported LLM output (unknown warehouses/suppliers/evidence) is discarded and audited as
`recommendation.discarded_unsupported`. Costs for known option kinds always come from data.
"""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from app.agents import options as option_builder
from app.agents.common import Timer, agent_output, clamp, ctx
from app.agents.confidence import cap_option_confidence, extraction_confidence
from app.agents.state import CaseState
from app.agents.validation import required_fields
from app.llm import prompts

AGENT = "recommendation"
MAX_OPTIONS = 4
CUSTOM_OPTION_FACTOR = 0.8


class OptionOut(BaseModel):
    kind: str = "custom"
    title: str
    description: str
    estimated_cost_inr: int = Field(ge=0)
    estimated_lead_time_days: float = Field(ge=0)
    rationale: str = ""
    evidence: list[str] = Field(default_factory=list)
    confidence: float = 0.5


class RecommendationOut(BaseModel):
    options: list[OptionOut]


def _context(state: CaseState, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    sku = state["facts"].get("sku")
    stock = [
        {"location": r["location"], "free": r["free"]}
        for r in state.get("inventory_snapshot") or []
        if r["sku"] == sku
    ]
    suppliers = [
        {
            "name": s["name"],
            "lead_time_days": s["lead_time_days"],
            "express_cost_per_unit_inr": s["express_cost_per_unit_inr"],
            "reliability": s["reliability_score"],
        }
        for s in state["suppliers"]
        if sku in s["items"]
    ]
    return {
        "facts": state["facts"],
        "risk": state["risk"].get("reconciled"),
        "available_stock_by_location": stock,
        "suppliers": suppliers,
        "candidate_options": [
            {
                k: o[k]
                for k in (
                    "kind",
                    "title",
                    "estimated_cost_inr",
                    "estimated_lead_time_days",
                    "coverage",
                    "evidence",
                )
            }
            for o in candidates
        ],
        "excluded_kinds": state.get("excluded_kinds", []),
    }


def unsupported_reason(option: OptionOut, state: CaseState) -> str | None:
    """Reference check: every warehouse/supplier an option cites must exist in our data."""
    warehouses = {r["location"] for r in state.get("inventory_snapshot") or []}
    suppliers = {s["name"] for s in state["suppliers"]}
    for ref in option.evidence:
        source, _, name = ref.partition(".")
        if source == "inventory" and name not in warehouses:
            return f"unknown warehouse '{name}'"
        if source == "supplier" and name not in suppliers:
            return f"unknown supplier '{name}'"
    for wh in re.findall(r"\b[A-Z][a-z]+-WH\b", f"{option.title} {option.description}"):
        if wh not in warehouses:
            return f"unknown warehouse '{wh}'"
    if option.kind in set(state.get("excluded_kinds", [])):
        return f"option kind '{option.kind}' was rejected by an approver"
    return None


def _names_other_source(text: str, base: dict[str, Any], state: CaseState) -> str | None:
    """A rationale must not name a supplier/warehouse other than the ones the option uses
    (e.g. "expedite from ShelfMart" when the costed option is RackWorks)."""
    used = {ref.partition(".")[2] for ref in base["evidence"]}
    known = {s["name"] for s in state["suppliers"]} | {
        r["location"] for r in state.get("inventory_snapshot") or []
    }
    late_supplier = (state["facts"].get("supplier") or "").lower()
    for name in known - used:
        if late_supplier and name.lower() == late_supplier:
            continue  # mentioning the late supplier itself is fine
        if re.search(rf"\b{re.escape(name)}\b", text):
            return f"'{name}', which this option does not use"
    return None


def _merge_llm(
    out: RecommendationOut, candidates: list[dict[str, Any]], state: CaseState
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_kind = {c["kind"]: c for c in candidates}
    merged, discarded = [], []
    for opt in out.options:
        if reason := unsupported_reason(opt, state):
            discarded.append({"title": opt.title, "reason": reason})
            continue
        if opt.kind in by_kind:  # rationale from the LLM; title, numbers and sources from data
            base = by_kind.pop(opt.kind)
            if reason := _names_other_source(opt.rationale, base, state):
                discarded.append({"title": opt.title, "reason": f"rationale cites {reason}"})
            merged.append(
                {
                    **base,
                    "rationale": "" if reason else opt.rationale,
                    "base_confidence": min(clamp(opt.confidence), base["base_confidence"]),
                }
            )
        else:
            merged.append(
                {
                    "kind": "custom",
                    "title": opt.title,
                    "description": opt.description,
                    "estimated_cost_inr": opt.estimated_cost_inr,
                    "estimated_lead_time_days": opt.estimated_lead_time_days,
                    "coverage": 0.0,
                    "risk_reduction": "",
                    "evidence": opt.evidence,
                    "allocations": [],
                    "rationale": opt.rationale,
                    "base_confidence": clamp(opt.confidence) * CUSTOM_OPTION_FACTOR,
                }
            )
    if not any(o["estimated_cost_inr"] == 0 for o in merged):
        zero = next((c for c in by_kind.values() if c["estimated_cost_inr"] == 0), None)
        if zero:
            merged.append(zero)
    return merged, discarded


def _fallback_rationale(option: dict[str, Any], facts: dict[str, Any]) -> str:
    deadline = facts.get("hours_to_deadline")
    timing = f"; deadline in ~{deadline / 24:.1f} days" if deadline and deadline > 0 else ""
    return (
        f"Covers {option['coverage']:.0%} of the shortfall in "
        f"{option['estimated_lead_time_days']:g} day(s) for ₹{option['estimated_cost_inr']:,}"
        f"{timing}."
    )


def recommendation_node(state: CaseState, config: RunnableConfig) -> dict[str, Any]:
    timer = Timer()
    candidates = option_builder.build_candidates(
        state["facts"],
        state.get("inventory_snapshot"),
        state["suppliers"],
        state.get("excluded_kinds"),
    )
    result = ctx(config).llm.call_json(
        prompt_name="recommendation",
        system=prompts.RECOMMENDATION,
        user="CONTEXT:\n" + json.dumps(_context(state, candidates), default=str),
        schema=RecommendationOut,
    )
    from_fallback = result.data is None
    chosen, discarded = (
        (candidates, []) if from_fallback else _merge_llm(result.data, candidates, state)
    )

    extraction = extraction_confidence(state["fields"], required_fields(state["category"]))
    recs = []
    for rank, opt in enumerate(chosen[:MAX_OPTIONS], start=1):
        recs.append(
            {
                **{k: v for k, v in opt.items() if k not in {"base_confidence", "coverage"}},
                "rank": rank,
                "coverage": opt["coverage"],
                "rationale": opt.get("rationale") or _fallback_rationale(opt, state["facts"]),
                "confidence": cap_option_confidence(
                    opt["base_confidence"], extraction, from_fallback=from_fallback
                ),
                "model": "fallback" if from_fallback else result.model,
            }
        )
    events = [
        {
            "action": "recommendation.discarded_unsupported",
            "actor": AGENT,
            "after": d,
            "reason": d["reason"],
        }
        for d in discarded
    ]
    return {
        "recommendations": recs,
        "confidence_breakdown": {
            **state.get("confidence_breakdown", {}),
            "recommendation": recs[0]["confidence"] if recs else 0.0,
        },
        **agent_output(
            AGENT,
            timer,
            action="recommendation.generated",
            after=[
                {"rank": r["rank"], "title": r["title"], "cost": r["estimated_cost_inr"]}
                for r in recs
            ],
            result=result,
            confidence=recs[0]["confidence"] if recs else None,
            extra_events=events,
        ),
    }
