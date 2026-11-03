"""OpsRiskAgent + FinancialRiskAgent (independent LLM prompts) and RiskReconciler (deterministic).

Reconciler: levels ≥2 steps apart → agent_disagreement issue, take the HIGHER risk, require a
human decision, confidence = min of both. 1 step apart → take the higher and note it.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field, field_validator

from app.agents import options
from app.agents.common import Timer, agent_output, clamp, ctx, issue
from app.agents.state import CaseState
from app.enums import RISK_ORDER, IssueType, Priority, RiskLevel, Severity
from app.llm import fallback, prompts

PRIORITY_BY_RISK = {
    RiskLevel.CRITICAL: Priority.P1,
    RiskLevel.HIGH: Priority.P2,
    RiskLevel.MEDIUM: Priority.P3,
    RiskLevel.LOW: Priority.P4,
}
RISK_CONF = {0: 1.0, 1: 0.75}
DISAGREEMENT_CONF = 0.5


class RiskOut(BaseModel):
    urgency: int = Field(ge=1, le=5)
    impact: int = Field(ge=1, le=5)
    risk_level: Literal["low", "medium", "high", "critical"]
    factors: list[str] = Field(default_factory=list)
    rationale: str
    confidence: float = 0.7
    cost_exposure_inr: int | None = None

    @field_validator("risk_level", mode="before")
    @classmethod
    def _lower(cls, v: Any) -> Any:
        return v.lower() if isinstance(v, str) else v


def _facts_for_financial(state: CaseState) -> dict[str, Any]:
    facts = dict(state["facts"])
    candidates = options.build_candidates(
        facts, state.get("inventory_snapshot"), state["suppliers"]
    )
    facts["cheapest_cover_cost_inr"] = options.cheapest_full_cover_cost(candidates)
    if facts.get("penalty_per_unit_day_inr") and facts.get("shortfall"):
        days = max(facts.get("delay_days") or 1, 1)
        facts["penalty_exposure_inr"] = (
            facts["penalty_per_unit_day_inr"] * facts["shortfall"] * days
        )
    return facts


def _assess(
    agent: str, prompt_name: str, system: str, facts: dict[str, Any], config: RunnableConfig
) -> dict[str, Any]:
    timer = Timer()
    result = ctx(config).llm.call_json(
        prompt_name=prompt_name,
        system=system,
        user="FACTS:\n" + json.dumps(facts, default=str),
        schema=RiskOut,
    )
    if result.data is not None:
        assessment = result.data.model_dump()
        assessment["confidence"] = clamp(assessment["confidence"])
    else:
        heuristic = fallback.ops_risk if agent == "ops_risk" else fallback.financial_risk
        assessment = heuristic(facts)
        assessment["confidence"] = min(assessment["confidence"], 0.6)
    assessment["risk_level"] = str(assessment["risk_level"])
    assessment["score"] = assessment["urgency"] * assessment["impact"]
    assessment["model"] = "fallback" if result.data is None else result.model
    key = "ops" if agent == "ops_risk" else "financial"
    return {
        "risk": {key: assessment},
        **agent_output(
            agent,
            timer,
            action=f"risk.{key}_assessed",
            after=assessment,
            result=result,
            confidence=assessment["confidence"],
        ),
    }


def ops_risk_node(state: CaseState, config: RunnableConfig) -> dict[str, Any]:
    return _assess("ops_risk", "ops_risk", prompts.OPS_RISK, state["facts"], config)


def financial_risk_node(state: CaseState, config: RunnableConfig) -> dict[str, Any]:
    return _assess(
        "financial_risk",
        "financial_risk",
        prompts.FINANCIAL_RISK,
        _facts_for_financial(state),
        config,
    )


def reconcile(ops: dict[str, Any], fin: dict[str, Any]) -> tuple[dict[str, Any], int]:
    a, b = (
        RISK_ORDER.index(RiskLevel(ops["risk_level"])),
        RISK_ORDER.index(RiskLevel(fin["risk_level"])),
    )
    gap = abs(a - b)
    level = RISK_ORDER[max(a, b)]
    urgency, impact = max(ops["urgency"], fin["urgency"]), max(ops["impact"], fin["impact"])
    note = ""
    if gap == 1:
        note = (
            f" Agents differed by one level ({ops['risk_level']} vs {fin['risk_level']}); "
            f"using the higher."
        )
    elif gap >= 2:
        note = (
            f" Agents disagreed ({ops['risk_level']} vs {fin['risk_level']}); using the "
            f"higher risk — human decision required."
        )
    reconciled = {
        "urgency": urgency,
        "impact": impact,
        "risk_level": str(level),
        "score": urgency * impact,
        "factors": list(dict.fromkeys(ops["factors"] + fin["factors"])),
        "rationale": f"Ops: {ops['rationale']} Financial: {fin['rationale']}{note}".strip(),
        "confidence": min(ops["confidence"], fin["confidence"]),
        "disagreement": gap >= 2,
        "needs_human": gap >= 2,
        "gap": gap,
        "model": "deterministic",
    }
    return reconciled, gap


def reconcile_node(state: CaseState, config: RunnableConfig) -> dict[str, Any]:
    timer = Timer()
    ops, fin = state["risk"]["ops"], state["risk"]["financial"]
    reconciled, gap = reconcile(ops, fin)
    issues = []
    events = []
    if gap >= 2:
        issues.append(
            issue(
                "reconciler",
                IssueType.AGENT_DISAGREEMENT,
                Severity.WARNING,
                f"Agents disagree: ops says {ops['risk_level']}, financial says "
                f"{fin['risk_level']}. Using the higher risk; human decision required.",
                details={"ops": ops, "financial": fin},
            )
        )
        events.append(
            {
                "action": "risk.disagreement",
                "actor": "reconciler",
                "after": {"ops": ops["risk_level"], "financial": fin["risk_level"]},
            }
        )
    return {
        "risk": {"reconciled": reconciled},
        "confidence_breakdown": {"risk": RISK_CONF.get(gap, DISAGREEMENT_CONF)},
        **agent_output(
            "reconciler",
            timer,
            action="risk.reconciled",
            after=reconciled,
            confidence=reconciled["confidence"],
            issues=issues,
            extra_events=events,
        ),
    }
