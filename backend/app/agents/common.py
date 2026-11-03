"""Helpers shared by agent nodes: run context, trace entries, audit events, issues."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.config import Settings
from app.enums import IssueType, Severity
from app.llm.client import FALLBACK_MODEL, LLMClient, LLMResult


@dataclass
class AgentContext:
    llm: LLMClient
    settings: Settings


def ctx(config: RunnableConfig) -> AgentContext:
    return config["configurable"]["agent_context"]


class Timer:
    def __init__(self) -> None:
        self.started = time.perf_counter()

    @property
    def ms(self) -> int:
        return int((time.perf_counter() - self.started) * 1000)


def issue(
    agent: str,
    type_: IssueType,
    severity: Severity,
    message: str,
    *,
    field: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """An issue raised by an agent. `key` identifies it across re-runs for merging."""
    return {
        "key": f"{agent}:{type_}:{field or ''}",
        "agent": agent,
        "type": str(type_),
        "severity": str(severity),
        "field": field,
        "message": message,
        "details": details or {},
    }


def agent_output(
    agent: str,
    timer: Timer,
    *,
    action: str,
    after: Any,
    result: LLMResult[Any] | None = None,
    confidence: float | None = None,
    degraded_reason: str | None = None,
    issues: list[dict[str, Any]] | None = None,
    extra_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Trace entry + audit event(s) + issues (+ degraded marker) for one agent run."""
    model = result.model if result else "deterministic"
    used_fallback = result is not None and result.data is None
    if used_fallback:
        model = FALLBACK_MODEL
    trace = {
        "agent": agent,
        "ms": timer.ms,
        "model": model,
        "ok": not (result and result.failed),
        "llm_status": result.status if result else "n/a",
        "error": result.error if result and result.failed else None,
    }
    event = {
        "action": action,
        "actor": agent,
        "after": after,
        "confidence": confidence,
        "model": model,
        "prompt_hash": result.prompt_hash if result else None,
        "latency_ms": timer.ms,
        "tokens": result.tokens if result else None,
    }
    all_issues = list(issues or [])
    out: dict[str, Any] = {"trace": [trace], "audit_events": [event, *(extra_events or [])]}
    if result is not None and result.failed:
        out["degraded_reasons"] = [degraded_reason or "llm"]
        all_issues.append(
            issue(
                agent,
                IssueType.SYSTEM_UNAVAILABLE,
                Severity.WARNING,
                f"LLM unavailable for {agent} ({result.error}); used the rule-based fallback.",
                details={"system": "llm", "status": result.status},
            )
        )
    out["issues"] = all_issues
    return out


def agent_event(agent: str, action: str, after: Any, reason: str | None = None) -> dict[str, Any]:
    """An additional audit event emitted by an agent (e.g. security.injection_detected)."""
    return {"action": action, "actor": agent, "after": after, "reason": reason}


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))
