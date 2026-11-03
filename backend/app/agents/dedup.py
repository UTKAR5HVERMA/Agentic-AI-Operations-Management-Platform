"""DuplicateDetectionAgent (deterministic).

similarity = 0.5·same(location, item) + 0.3·Jaccard(subject+text tokens) + 0.2·closeness
(quantity and delay). ≥ 0.85 auto-link; 0.60–0.85 suggest to the user.
"""

from __future__ import annotations

import re
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.agents.common import Timer, agent_output, issue
from app.agents.state import CaseState
from app.enums import IssueType, Severity

AGENT = "dedup"
AUTO_LINK = 0.85
SUGGEST = 0.60
# Function words plus request/reporting boilerplate that says nothing about *which* issue it is.
_STOPWORDS = frozenset(
    "the a an and or for to of in on at by is are be will with we our us this that it from "
    "have has they them their hi team please thanks regards can you your into as was were "
    "currently only next any possible required inform note call tell told help just".split()
)
_SUFFIXES = ("ing", "ed", "s")


def _stem(word: str) -> str:
    """Light suffix stripping so 'delayed'/'delay' and 'units'/'unit' compare equal."""
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def tokens(text: str) -> set[str]:
    # TRADE-OFF: lexical Jaccard; embeddings would catch paraphrases (roadmap).
    words = (w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2)
    return {_stem(w) for w in words if w not in _STOPWORDS and _stem(w) not in _STOPWORDS}


def _closeness(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    if a == b:
        return 1.0
    return max(0.0, 1 - abs(a - b) / max(abs(a), abs(b)))


def similarity(new: dict[str, Any], other: dict[str, Any]) -> float:
    same = (
        1.0
        if (
            new["location"]
            and new["sku"]
            and new["location"] == other["location"]
            and new["sku"] == other["sku"]
        )
        else 0.0
    )
    a, b = tokens(new["text"]), tokens(other["text"])
    jaccard = len(a & b) / len(a | b) if a | b else 0.0
    parts = [
        c
        for c in (
            _closeness(new["quantity"], other["quantity"]),
            _closeness(new["delay_days"], other["delay_days"]),
        )
        if c is not None
    ]
    close = sum(parts) / len(parts) if parts else 0.0
    return round(0.5 * same + 0.3 * jaccard + 0.2 * close, 4)


def case_signature(state: CaseState) -> dict[str, Any]:
    fields = state["fields"]

    def norm(name: str) -> Any:
        return fields.get(name, {}).get("normalized")

    return {
        "location": norm("location"),
        "sku": norm("item"),
        "quantity": norm("quantity_required"),
        "delay_days": norm("delay_days"),
        "text": f"{state['subject']} {state['sanitized_text']}",
    }


def dedup_node(state: CaseState, config: RunnableConfig) -> dict[str, Any]:
    timer = Timer()
    if state.get("start_at") != "intake" or state.get("dedup_dismissed"):
        return {
            "duplicates": [],
            "trace": [
                {
                    "agent": AGENT,
                    "ms": 0,
                    "model": "deterministic",
                    "ok": True,
                    "llm_status": "skipped",
                    "error": None,
                }
            ],
        }
    signature = case_signature(state)
    scored = sorted(
        (
            {"id": c["id"], "ref": c["ref"], "similarity": similarity(signature, c)}
            for c in state.get("open_cases", [])
        ),
        key=lambda d: d["similarity"],
        reverse=True,
    )
    matches = [d for d in scored if d["similarity"] >= SUGGEST][:3]
    issues = []
    if matches:
        top = matches[0]
        auto = top["similarity"] >= AUTO_LINK
        issues.append(
            issue(
                AGENT,
                IssueType.DUPLICATE,
                Severity.INFO if auto else Severity.WARNING,
                f"Likely duplicate of {top['ref']} ({top['similarity']:.0%} match)"
                + (" — linked automatically." if auto else " — please confirm."),
                details={"candidates": matches, "auto_linked": auto},
            )
        )
    return {
        "duplicates": matches,
        **agent_output(
            AGENT, timer, action="dedup.completed", after={"candidates": matches}, issues=issues
        ),
    }
