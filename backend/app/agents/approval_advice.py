"""ApprovalAdvisor: suggests a decision to the person who must approve. Advice only (A4).

The Regional Manager or Director sees "AI suggests: approve / reject / forward to the Director"
with the reasons and what to check, then decides themselves: no code path acts on the
suggestion (DEVELOPMENT_RULES §0.4). Deterministic guards: a suggestion the approver cannot take
is replaced (approve above the manager's limit → forward; forward by the Director → rules), and
advice that cites numbers not in the facts is discarded for the rule-based advice.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agents.composer import unsupported_numbers
from app.llm import prompts
from app.llm.client import LLMClient, LLMResult

Suggestion = Literal["approve", "reject", "forward"]
RULES_MODEL = "rule-based"
APPROVER_LABEL = {"ops_manager": "Regional Manager", "admin": "Director"}


class AdviceOut(BaseModel):
    suggestion: Suggestion
    rationale: str = Field(min_length=10, max_length=400)
    checks: list[str] = Field(default_factory=list, max_length=3)


def _inr(amount: int) -> str:
    return f"₹{amount:,}"


def _over_limit(f: dict[str, Any]) -> bool:
    return f["approver_role"] == "ops_manager" and f["amount_inr"] > f["approver_limit_inr"]


def _better_alternative(f: dict[str, Any]) -> dict[str, Any] | None:
    """A proposed option that is cheaper and at least as fast as the one being approved."""
    return next(
        (
            a
            for a in f.get("alternatives", [])
            if a["cost_inr"] < f["amount_inr"] and a["lead_time_days"] <= f["lead_time_days"]
        ),
        None,
    )


def rule_advice(f: dict[str, Any]) -> dict[str, Any]:
    """Advice without the LLM (mock mode, outage, or rejected LLM output)."""
    checks = [f"Approval needed because: {r}" for r in f.get("reasons", [])][:2]
    if f.get("stale_reason"):
        checks.insert(0, f"Circumstances changed: {f['stale_reason']}")
    if _over_limit(f):
        return {
            "suggestion": "forward",
            "rationale": f"{_inr(f['amount_inr'])} is above your {_inr(f['approver_limit_inr'])} "
            "limit, so only the Director can approve it. Forward it with your view, or reject it.",
            "checks": checks[:3],
        }
    if alt := _better_alternative(f):
        return {
            "suggestion": "reject",
            "rationale": f"'{alt['title']}' costs {_inr(alt['cost_inr'])} and is ready in "
            f"{alt['lead_time_days']} days, so it is cheaper and at least as fast.",
            "checks": checks[:3],
        }
    return {
        "suggestion": "approve",
        "rationale": f"It costs {_inr(f['amount_inr'])}, is ready in {f['lead_time_days']} days "
        "and is within your approval authority.",
        "checks": checks[:3],
    }


def _enforce(advice: dict[str, Any], f: dict[str, Any]) -> dict[str, Any] | None:
    """Keep only suggestions the approver can actually take; None → use the rules."""
    if advice["suggestion"] == "forward" and f["approver_role"] != "ops_manager":
        return None  # nobody is above the Director
    if advice["suggestion"] == "approve" and _over_limit(f):
        return None
    return advice


def advise(f: dict[str, Any], llm: LLMClient) -> tuple[dict[str, Any], LLMResult[AdviceOut]]:
    """Return (advice, LLMResult). Advice: suggestion, rationale, checks, model."""
    source = json.dumps(f, default=str)
    result = llm.call_json(
        prompt_name="approval_advice",
        system=prompts.APPROVAL_ADVICE.format(
            approver=APPROVER_LABEL.get(f["approver_role"], "approver")
        ),
        user="FACTS:\n" + source,
        schema=AdviceOut,
    )
    advice: dict[str, Any] | None = None
    if result.data is not None:
        candidate = {
            "suggestion": result.data.suggestion,
            "rationale": result.data.rationale.strip(),
            "checks": [c.strip()[:160] for c in result.data.checks if c.strip()],
        }
        said = " ".join([candidate["rationale"], *candidate["checks"]])
        if not unsupported_numbers(source, said):  # grounded: every number is in the facts
            advice = _enforce(candidate, f)
    if advice is None:
        return {**rule_advice(f), "model": RULES_MODEL}, result
    return {**advice, "model": result.model}, result
