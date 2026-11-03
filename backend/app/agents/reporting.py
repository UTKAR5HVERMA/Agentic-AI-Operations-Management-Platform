"""ReportingAgent: numbers come from SQL aggregates; the LLM only writes the narrative."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from app.llm import prompts
from app.llm.client import LLMClient, LLMResult


class SummaryOut(BaseModel):
    markdown: str = Field(max_length=8000)


def _template(m: dict[str, Any]) -> str:
    critical = m.get("critical_cases", [])
    pending = m.get("pending_approval_items", [])
    lines = [
        "## Headline",
        f"{m['open_cases']} open cases; {m['pending_approvals']} approvals pending; "
        f"{m['overdue']} overdue; {m['degraded_cases']} running in degraded mode.",
        "",
        "## Critical items",
        *(
            [
                f"- {c['ref']}: {c['subject']} ({c['status']}, risk {c['risk_level']})"
                for c in critical
            ]
            or ["- None"]
        ),
        "",
        "## Pending approvals",
        *(
            [
                f"- {p['ref']}: {p['title']} — ₹{p['amount_inr']:,} awaiting {p['approver_role']}"
                for p in pending
            ]
            or ["- None"]
        ),
        "",
        "## Risks",
        f"- AI override rate {m['ai_override_rate']:.0%}; extraction accuracy "
        f"{m['auto_extraction_accuracy']:.0%}; fallback rate {m['fallback_rate']:.0%}.",
        f"- Approval SLA breaches: {m['approval_sla_breaches']}.",
        *(
            f"- Self-approved by the Director (review): {s['ref']} "
            f"₹{s['amount_inr']:,} — {s['justification']}"
            for s in m.get("self_approvals", [])
        ),
        "",
        "## Actions needed",
        "- Decide pending approvals before their due time."
        if pending
        else "- No approvals waiting.",
        "- Provide missing information on NEEDS_INFO cases."
        if m["counts_by_status"].get("NEEDS_INFO")
        else "- No cases are blocked on information.",
    ]
    return "\n".join(lines)


def summarize(metrics: dict[str, Any], llm: LLMClient) -> tuple[str, LLMResult[SummaryOut]]:
    result = llm.call_json(
        prompt_name="reporting",
        system=prompts.REPORTING,
        user="METRICS:\n" + json.dumps(metrics, default=str),
        schema=SummaryOut,
    )
    markdown = result.data.markdown if result.data else _template(metrics)
    return markdown, result
