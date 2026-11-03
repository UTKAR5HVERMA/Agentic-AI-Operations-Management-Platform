"""ExtractionAgent: fields + evidence + confidence, grounded against the source (BACKEND.md §7.3).

field_conf = self_score × grounding (1.0 found / 0.3 not found) × 0.6 if source == fallback.
"""

from __future__ import annotations

import difflib
import re
from datetime import datetime, timedelta
from typing import Any

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field, field_validator

from app.agents.common import Timer, agent_output, clamp, ctx, issue
from app.agents.state import CaseState
from app.enums import Category, FieldName, FieldSource, IssueType, Severity
from app.llm import fallback, guard, prompts
from app.normalize import NUMBER_WORD_RE, NUMBER_WORDS, normalize_field

AGENT = "extraction"
FALLBACK_FACTOR = 0.6
UNGROUNDED_FACTOR = 0.3
OUT_OF_BOUNDS_FACTOR = 0.5
FUZZY_MATCH = 0.9
MAX_QUANTITY = 1_000_000
MAX_COST_INR = 100_000_000
FIELD_NAMES = [str(f) for f in FieldName]


class FieldOut(BaseModel):
    value: str | None = None
    evidence: str | None = None
    confidence: float = 0.5

    @field_validator("value", "evidence", mode="before")
    @classmethod
    def _to_text(cls, v: Any) -> str | None:
        return None if v is None or v == "" else str(v)


class IssueItem(BaseModel):
    title: str
    text: str
    category: str = "other"


class ExtractionOut(BaseModel):
    fields: dict[str, FieldOut] = Field(default_factory=dict)
    category: str = "other"
    requested_actions: list[str] = Field(default_factory=list)
    is_multi_issue: bool = False
    issues_list: list[IssueItem] = Field(default_factory=list)


def source_text(state: CaseState) -> str:
    return f"{state['subject']}\n\n{state['sanitized_text']}"


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


NUMERIC_FIELDS = {"quantity_required", "quantity_available", "delay_days", "cost_impact"}


def value_supported(field: str, normalized: Any, evidence: str | None) -> bool:
    """A numeric value must appear in its own evidence quote, as digits ("2,000 racks") or as a
    number word ("delayed by five days")."""
    if field not in NUMERIC_FIELDS or normalized is None:
        return True
    if str(normalized) in re.sub(r"[,\s]", "", evidence or ""):
        return True
    words = {w.lower() for w in NUMBER_WORD_RE.findall(evidence or "")}
    return any(NUMBER_WORDS[w] == normalized for w in words)


def evidence_hedge(evidence: str | None, source: str) -> float:
    """Deterministic cap from hedging ("maybe", "I heard", "not sure") around the evidence."""
    idx = source.lower().find((evidence or "").lower())
    return fallback.hedge_score(fallback.sentence_at(source, idx)) if idx >= 0 else 1.0


def is_grounded(evidence: str | None, source: str) -> bool:
    """Evidence must be a verbatim (or ≥0.9 fuzzy) substring of the source text."""
    if not evidence:
        return False
    ev, src = _squash(evidence), _squash(source)
    if ev in src:
        return True
    words = src.split(" ")
    span = len(ev.split(" "))
    for i in range(max(len(words) - span + 1, 1)):
        window = " ".join(words[i : i + span])
        if difflib.SequenceMatcher(None, ev, window).ratio() >= FUZZY_MATCH:
            return True
    return False


def _llm_extract(state: CaseState, config: RunnableConfig) -> tuple[Any, ExtractionOut | None]:
    system = prompts.EXTRACTION.replace("{received_at}", state["received_at"])
    result = ctx(config).llm.call_json(
        prompt_name="extraction",
        system=system,
        user=guard.wrap_untrusted(source_text(state)),
        schema=ExtractionOut,
    )
    return result, result.data


def _from_fallback(state: CaseState) -> ExtractionOut:
    received = datetime.fromisoformat(state["received_at"])
    fb = fallback.extract(
        source_text(state), received, state["catalog"], [s["name"] for s in state["suppliers"]]
    )
    return ExtractionOut(
        fields={
            k: FieldOut(value=v.value, evidence=v.evidence, confidence=v.confidence)
            for k, v in fb.fields.items()
        },
        category=str(fb.category),
        requested_actions=fb.requested_actions,
        is_multi_issue=fb.is_multi_issue,
        issues_list=[IssueItem(**i) for i in fb.issues_list],
    )


def _out_of_bounds(field: str, normalized: Any, received: datetime) -> str | None:
    quantity = field in {"quantity_required", "quantity_available"}
    if quantity and normalized is not None and not 0 <= normalized <= MAX_QUANTITY:
        return f"{field} {normalized} is outside 0–{MAX_QUANTITY:,}"
    if field == "delay_days" and normalized is not None and not 0 <= normalized <= 365:
        return f"delay of {normalized} days is outside 0–365"
    if field == "cost_impact" and normalized is not None and normalized > MAX_COST_INR:
        return f"cost {normalized} exceeds the sanity bound"
    if field in {"required_date", "approval_deadline", "original_delivery_date"} and normalized:
        when = datetime.fromisoformat(normalized["start"])
        if when > received + timedelta(days=365) or when < received - timedelta(days=30):
            return f"date {when.date()} is more than a year away or long past"
    return None


def _process_field(
    name: str, raw: FieldOut, source: str, src_kind: FieldSource, state: CaseState
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    received = datetime.fromisoformat(state["received_at"])
    normalized, ambiguous = normalize_field(name, raw.value, received, state["catalog"])
    grounded = is_grounded(raw.evidence, source) and value_supported(name, normalized, raw.evidence)
    conf = clamp(raw.confidence) * (1.0 if grounded else UNGROUNDED_FACTOR)
    if src_kind == FieldSource.FALLBACK:
        conf *= FALLBACK_FACTOR  # fallback self-scores already include the hedge penalty
    elif grounded:
        conf = min(conf, evidence_hedge(raw.evidence, source))
    issues: list[dict[str, Any]] = []
    if not grounded:
        issues.append(
            issue(
                AGENT,
                IssueType.LOW_CONFIDENCE,
                Severity.WARNING,
                f"'{raw.value}' for {name} is not supported by the email text.",
                field=name,
                details={"evidence": raw.evidence},
            )
        )
    if ambiguous:
        issues.append(
            issue(
                AGENT,
                IssueType.AMBIGUITY,
                Severity.WARNING,
                f"{name} '{raw.value}' is relative/approximate; please confirm.",
                field=name,
                details={"normalized": normalized},
            )
        )
    if reason := _out_of_bounds(name, normalized, received):
        conf *= OUT_OF_BOUNDS_FACTOR
        issues.append(issue(AGENT, IssueType.OUT_OF_BOUNDS, Severity.WARNING, reason, field=name))
    record = {
        "value": raw.value,
        "normalized": normalized,
        "evidence": raw.evidence,
        "confidence": round(conf, 4),
        "source": str(src_kind),
        "ambiguous": ambiguous,
    }
    return record, issues


def _intent_issues(out: ExtractionOut) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    subs = [i.model_dump() for i in out.issues_list] if len(out.issues_list) >= 2 else []
    if subs:
        return subs, [
            issue(
                AGENT,
                IssueType.AMBIGUITY,
                Severity.BLOCKER,
                f"This email contains {len(subs)} separate issues. Handle them in this "
                f"request: ask the sender which to prioritise, or confirm and continue.",
                details={"sub_requests": subs},
            )
        ]
    if not out.requested_actions and not out.fields.get("requested_action"):
        return [], [
            issue(
                AGENT,
                IssueType.AMBIGUITY,
                Severity.WARNING,
                "The request does not state what action is expected.",
                field="requested_action",
            )
        ]
    return [], []


def extraction_node(state: CaseState, config: RunnableConfig) -> dict[str, Any]:
    timer = Timer()
    result, out = _llm_extract(state, config)
    src_kind = FieldSource.LLM
    if out is None:
        out, src_kind = _from_fallback(state), FieldSource.FALLBACK

    source = source_text(state)
    fields: dict[str, dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []
    for name, raw in out.fields.items():
        if name not in FIELD_NAMES or raw.value is None:
            continue
        fields[name], field_issues = _process_field(name, raw, source, src_kind, state)
        issues += field_issues
    locked = state.get("locked_fields", {})
    fields.update(locked)  # human corrections always win
    issues = [i for i in issues if i["field"] not in locked]

    category = out.category if out.category in set(Category) else str(Category.OTHER)
    sub_requests, intent_issues = _intent_issues(out)
    summary = {k: v["value"] for k, v in fields.items()}
    return {
        "fields": fields,
        "category": state.get("category_hint") or category,
        "requested_actions": out.requested_actions,
        "sub_requests": sub_requests,
        **agent_output(
            AGENT,
            timer,
            action="extraction.completed",
            after={"fields": summary, "category": category, "source": str(src_kind)},
            result=result,
            issues=issues + intent_issues,
        ),
    }
