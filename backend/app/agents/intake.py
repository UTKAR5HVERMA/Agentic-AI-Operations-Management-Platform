"""IntakeGuardAgent: regex + LLM classifier injection defence; produces the sanitized text."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from app.agents.common import Timer, agent_event, agent_output, ctx, issue
from app.agents.state import CaseState
from app.enums import IssueType, Severity
from app.llm import guard, prompts

AGENT = "intake_guard"


class InjectionVerdict(BaseModel):
    is_injection: bool
    spans: list[str] = Field(default_factory=list)
    reason: str = ""


def intake_guard_node(state: CaseState, config: RunnableConfig) -> dict[str, Any]:
    timer = Timer()
    raw = state["raw_text"]
    result = ctx(config).llm.call_json(
        prompt_name="injection_classifier",
        system=prompts.INJECTION_CLASSIFIER,
        user=guard.wrap_untrusted(raw),
        schema=InjectionVerdict,
    )
    llm_spans = result.data.spans if result.data and result.data.is_injection else []
    scanned = guard.scan(raw, extra_spans=llm_spans)

    issues: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    if scanned.flag:
        issues.append(
            issue(
                AGENT,
                IssueType.INJECTION,
                Severity.WARNING,
                "Suspicious instructions detected and quarantined. They were NOT followed.",
                details=scanned.as_details(),
            )
        )
        events.append(
            agent_event(
                AGENT,
                "security.injection_detected",
                scanned.as_details(),
                reason="Content that tries to instruct the AI was removed from analysis",
            )
        )
    return {
        "sanitized_text": scanned.sanitized_text,
        "injection": scanned.as_details(),
        **agent_output(
            AGENT,
            timer,
            action="intake.completed",
            after={"injection_flag": scanned.flag, "patterns": scanned.patterns},
            result=result,
            issues=issues,
            extra_events=events,
        ),
    }
