"""LangGraph wiring (BACKEND.md §7.2). Agents coordinate only through the shared CaseState.

intake_guard → extraction → [validation ∥ dedup] → triage (gate 1)
  duplicate  → communication → END
  needs_info → communication → END
  assess     → [ops_risk ∥ financial_risk] → reconcile → recommendation → score (gate 2)
                 withheld → withhold → communication → END
                 else     → approval_router → communication → END
The graph never sends or approves anything: it always stops for a human (PENDING_REVIEW).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from app.agents import confidence as conf
from app.agents.approval_router import approval_router_node
from app.agents.common import AgentContext, Timer, agent_output, issue
from app.agents.communication import communication_node
from app.agents.dedup import AUTO_LINK, dedup_node
from app.agents.extraction import extraction_node
from app.agents.intake import intake_guard_node
from app.agents.recommendation import recommendation_node
from app.agents.risk import financial_risk_node, ops_risk_node, reconcile_node
from app.agents.state import CaseState
from app.agents.validation import FIELD_LABELS, required_fields, validation_node
from app.enums import IssueType, Severity


def _open_blockers(state: CaseState) -> list[dict[str, Any]]:
    suppressed = set(state.get("suppressed_issue_keys", []))
    return [
        i
        for i in state.get("issues", [])
        if i["severity"] == Severity.BLOCKER and i["key"] not in suppressed
    ]


def _extraction_conf(state: CaseState) -> float:
    return conf.extraction_confidence(state["fields"], required_fields(state["category"]))


def triage_node(state: CaseState, config: RunnableConfig) -> dict[str, Any]:
    """Gate 1: duplicate → link; blocker issues → needs info; otherwise assess risk."""
    dups = state.get("duplicates", [])
    if dups and dups[0]["similarity"] >= AUTO_LINK:
        outcome = "duplicate"
    elif _open_blockers(state):
        outcome = "needs_info"
    else:
        outcome = "assess"
    breakdown = {
        "extraction": round(_extraction_conf(state), 4),
        "data": state.get("data_conf", 1.0),
        "risk": 0.0,
        "recommendation": 0.0,
    }
    update: dict[str, Any] = {"outcome": outcome, "confidence_breakdown": breakdown}
    if outcome != "assess":
        update["confidence"] = conf.overall(**breakdown)
    return update


def score_node(state: CaseState, config: RunnableConfig) -> dict[str, Any]:
    """Gate 2: compute overall confidence (§7.4)."""
    previous = state.get("confidence_breakdown", {})
    breakdown = {
        "extraction": round(_extraction_conf(state), 4),
        "data": state.get("data_conf", 1.0),
        "risk": previous.get("risk", 0.0),
        "recommendation": previous.get("recommendation", 0.0),
    }
    overall = conf.overall(**breakdown)
    settings = config["configurable"]["agent_context"].settings
    band = conf.band(
        overall, settings.confidence_auto_threshold, settings.confidence_block_threshold
    )
    return {
        "confidence": overall,
        "confidence_breakdown": breakdown,
        "outcome": "withheld" if band == "withheld" else "pending_review",
    }


def withhold_node(state: CaseState, config: RunnableConfig) -> dict[str, Any]:
    """Edge case 6: not enough evidence → no recommendation, ask for information."""
    timer = Timer()
    weak = [
        f
        for f in required_fields(state["category"])
        if state["fields"].get(f, {}).get("confidence", 0) < 0.5
    ]
    labels = ", ".join(FIELD_LABELS.get(f, f) for f in weak) or "key facts"
    withheld = [r["title"] for r in state.get("recommendations", [])]
    low = issue(
        "score",
        IssueType.LOW_CONFIDENCE,
        Severity.BLOCKER,
        f"Not enough evidence to recommend an action safely. Missing or uncertain: {labels}.",
        details={"confidence": state["confidence"], "weak_fields": weak},
    )
    return {
        "recommendations": [],
        "outcome": "needs_info",
        **agent_output(
            "score",
            timer,
            action="recommendation.withheld",
            after={"confidence": state["confidence"], "withheld_options": withheld},
            confidence=state["confidence"],
            issues=[low],
        ),
    }


def _route_start(state: CaseState) -> str | list[str]:
    return (
        "intake_guard" if state.get("start_at", "intake") == "intake" else ["validation", "dedup"]
    )


def _route_triage(state: CaseState) -> str | list[str]:
    return ["ops_risk", "financial_risk"] if state["outcome"] == "assess" else "communication"


def _route_score(state: CaseState) -> str:
    return "withhold" if state["outcome"] == "withheld" else "approval_router"


@lru_cache
def build_graph() -> Any:
    g = StateGraph(CaseState)
    for name, node in [
        ("intake_guard", intake_guard_node),
        ("extraction", extraction_node),
        ("validation", validation_node),
        ("dedup", dedup_node),
        ("triage", triage_node),
        ("ops_risk", ops_risk_node),
        ("financial_risk", financial_risk_node),
        ("reconcile", reconcile_node),
        ("recommendation", recommendation_node),
        ("score", score_node),
        ("withhold", withhold_node),
        ("approval_router", approval_router_node),
        ("communication", communication_node),
    ]:
        g.add_node(name, node)
    g.add_conditional_edges(START, _route_start, ["intake_guard", "validation", "dedup"])
    g.add_edge("intake_guard", "extraction")
    g.add_edge("extraction", "validation")
    g.add_edge("extraction", "dedup")
    g.add_edge(["validation", "dedup"], "triage")
    g.add_conditional_edges(
        "triage", _route_triage, ["ops_risk", "financial_risk", "communication"]
    )
    g.add_edge(["ops_risk", "financial_risk"], "reconcile")
    g.add_edge("reconcile", "recommendation")
    g.add_edge("recommendation", "score")
    g.add_conditional_edges("score", _route_score, ["withhold", "approval_router"])
    g.add_edge("withhold", "communication")
    g.add_edge("approval_router", "communication")
    g.add_edge("communication", END)
    return g.compile()


def run(state: CaseState, agent_context: AgentContext) -> CaseState:
    return build_graph().invoke(state, config={"configurable": {"agent_context": agent_context}})
