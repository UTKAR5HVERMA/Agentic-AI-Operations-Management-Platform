"""ApprovalRouter — deterministic policy, NOT an LLM (BACKEND.md §9).

Human approval is mandatory when the option costs money, risk is high/critical, overall
confidence < AUTO threshold, agents disagree, or the case carries an injection flag.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.agents.common import Timer, agent_output, ctx
from app.agents.state import CaseState
from app.enums import Role

MANAGER_LIMIT_INR = 50_000
ESCALATION_CHAIN = [Role.OPS_MANAGER, Role.ADMIN]  # Regional Manager → Director


@dataclass
class ApprovalStep:
    role: Role
    # "financial" carries spend authority (the approval limit applies); "operational" is a ₹0
    # sign-off
    kind: str


@dataclass
class ApprovalPlan:
    required: bool
    reasons: list[str] = field(default_factory=list)
    steps: list[ApprovalStep] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "required": self.required,
            "reasons": self.reasons,
            "approvers": [str(s.role) for s in self.steps],
        }


@dataclass(frozen=True)
class PolicyContext:
    risk_level: str | None
    confidence: float
    disagreement: bool
    injection: bool
    auto_threshold: float


def mandatory_reasons(amount: int, ctx_: PolicyContext) -> list[str]:
    reasons = []
    if amount > 0:
        reasons.append(f"Additional cost ₹{amount:,}")
    if ctx_.risk_level in {"high", "critical"}:
        reasons.append(f"Risk is {ctx_.risk_level}")
    if ctx_.confidence < ctx_.auto_threshold:
        reasons.append(f"Confidence {ctx_.confidence:.0%} is below {ctx_.auto_threshold:.0%}")
    if ctx_.disagreement:
        reasons.append("Risk agents disagree")
    if ctx_.injection:
        reasons.append("Email contained suspicious instructions")
    return reasons


def plan(amount: int, ctx_: PolicyContext) -> ApprovalPlan:
    """One Regional Manager decision, chosen by the Operations Team. The manager approves within
    their limit, rejects, or forwards to the Director; above the limit they cannot approve alone."""
    reasons = mandatory_reasons(amount, ctx_)
    if not reasons:
        return ApprovalPlan(required=False)  # ₹0 and nothing risky: the analyst may proceed
    if amount > MANAGER_LIMIT_INR:
        reasons = [
            *reasons,
            f"Above the Regional Manager's ₹{MANAGER_LIMIT_INR:,} limit: they must forward it "
            "to the Director or reject it",
        ]
    kind = "operational" if amount == 0 else "financial"
    return ApprovalPlan(
        required=True, reasons=reasons, steps=[ApprovalStep(Role.OPS_MANAGER, kind)]
    )


def next_escalation_role(current: str) -> Role | None:
    chain = [str(r) for r in ESCALATION_CHAIN]
    idx = chain.index(current) if current in chain else -1
    return ESCALATION_CHAIN[idx + 1] if 0 <= idx < len(chain) - 1 else None


def policy_context(state: CaseState, auto_threshold: float) -> PolicyContext:
    reconciled = state.get("risk", {}).get("reconciled") or {}
    return PolicyContext(
        risk_level=reconciled.get("risk_level"),
        confidence=state.get("confidence", 0.0),
        disagreement=bool(reconciled.get("disagreement")),
        injection=bool(state.get("injection", {}).get("flag")),
        auto_threshold=auto_threshold,
    )


def approval_router_node(state: CaseState, config: RunnableConfig) -> dict[str, Any]:
    timer = Timer()
    policy = policy_context(state, ctx(config).settings.confidence_auto_threshold)
    recs = []
    for rec in state.get("recommendations", []):
        p = plan(rec["estimated_cost_inr"], policy)
        recs.append(
            {
                **rec,
                "requires_approval": p.required,
                "approval_reasons": p.reasons,
                "approval_plan": p.summary(),
            }
        )
    return {
        "recommendations": recs,
        **agent_output(
            "approval_router",
            timer,
            action="approval.plan_computed",
            after=[{"title": r["title"], **r["approval_plan"]} for r in recs],
        ),
    }
