"""Prompt-injection detection and quarantine (BACKEND.md §7.5.6).

Layer 1 is deterministic regex (always on). Layer 2 is an optional LLM classifier whose spans
are only accepted when they occur verbatim in the email. Quarantined sentences are removed from
the sanitized text and kept in `injection_details` for display. Structurally, no LLM output can
approve or send anything, so a missed injection still cannot trigger a binding action.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

INJECTION_PATTERNS: dict[str, str] = {
    "ignore_instructions": r"\bignore\s+(?:all\s+|any\s+)?(?:previous|prior|above|earlier|all)\b"
    r"[^.\n]*\binstructions?\b",
    "disregard": r"\bdisregard\s+(?:all|any|previous|prior|the above|your|these)\b",
    "role_override": r"\byou are now\b|\bact as (?:an?|the) (?:admin|system|approver)\b",
    "system_prompt": r"\bsystem prompt\b|\bdeveloper message\b",
    "auto_approve": r"\bapprove (?:this|it|immediately|automatically|now)\b",
    "mark_approved": r"\bmark (?:this |it |the )?(?:request |case )?(?:as )?approved\b",
    "exfiltrate": r"\bsend\b[^.\n]{0,80}\bto\b[^.\n]{0,40}[\w.+-]+@[\w-]+\.[\w.]+",
    "reveal": r"\breveal\b[^.\n]{0,40}\b(?:prompt|instructions?|secrets?|keys?|password)",
    "as_an_ai": r"\bas an ai\b",
    "hidden_html": r"<!--.*?-->|<[^>]+style\s*=\s*[\"'][^\"']*display\s*:\s*none",
    "base64_blob": r"\b[A-Za-z0-9+/]{80,}={0,2}",
}
ZERO_WIDTH = re.compile("[​‌‍⁠﻿]")
_SENTENCE = re.compile(r"[^.!?\n]+[.!?]*", re.MULTILINE)


@dataclass
class GuardResult:
    sanitized_text: str
    flag: bool = False
    patterns: list[str] = field(default_factory=list)
    quarantined_spans: list[dict[str, Any]] = field(default_factory=list)

    def as_details(self) -> dict[str, Any]:
        return {
            "flag": self.flag,
            "patterns": self.patterns,
            "quarantined_spans": self.quarantined_spans,
        }


def _sentence_bounds(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _SENTENCE.finditer(text) if m.group(0).strip()]


def _regex_hits(text: str) -> list[tuple[int, int, str]]:
    hits: list[tuple[int, int, str]] = []
    for name, pattern in INJECTION_PATTERNS.items():
        for m in re.finditer(pattern, text, flags=re.IGNORECASE | re.DOTALL):
            hits.append((m.start(), m.end(), name))
    return hits


def scan(text: str, extra_spans: list[str] | None = None) -> GuardResult:
    """Detect injection attempts; quarantine every sentence that contains one."""
    patterns: set[str] = set()
    if ZERO_WIDTH.search(text):
        patterns.add("zero_width_chars")
        text = ZERO_WIDTH.sub("", text)

    hits = _regex_hits(text)
    for span in extra_spans or []:
        idx = text.find(span) if span else -1
        if idx >= 0:  # LLM-proposed spans count only when they are verbatim in the email
            hits.append((idx, idx + len(span), "llm_classifier"))

    quarantined = _quarantine(text, hits)
    patterns.update(q["pattern"] for q in quarantined)
    sanitized = _remove(text, quarantined)
    return GuardResult(
        sanitized_text=sanitized,
        flag=bool(patterns),
        patterns=sorted(patterns),
        quarantined_spans=quarantined,
    )


def _quarantine(text: str, hits: list[tuple[int, int, str]]) -> list[dict[str, Any]]:
    spans: dict[tuple[int, int], dict[str, Any]] = {}
    for start, end, name in hits:
        for s, e in _sentence_bounds(text):
            if s < end and start < e:
                s, e = min(s, start), max(e, end)
                key = (s, e)
                spans.setdefault(
                    key, {"start": s, "end": e, "text": text[s:e].strip(), "pattern": name}
                )
    merged: list[dict[str, Any]] = []
    for span in sorted(spans.values(), key=lambda x: x["start"]):
        if merged and span["start"] < merged[-1]["end"]:
            merged[-1]["end"] = max(merged[-1]["end"], span["end"])
            merged[-1]["text"] = text[merged[-1]["start"] : merged[-1]["end"]].strip()
            continue
        merged.append(span)
    return merged


def _remove(text: str, spans: list[dict[str, Any]]) -> str:
    out, cursor = [], 0
    for span in spans:
        out.append(text[cursor : span["start"]])
        out.append("[quarantined]")
        cursor = span["end"]
    out.append(text[cursor:])
    return re.sub(r"[ \t]+\n", "\n", "".join(out)).strip()


def wrap_untrusted(text: str) -> str:
    """Wrap email content as data; neutralise any attempt to close the tag early."""
    safe = re.sub(r"</?\s*untrusted_email\s*>", "[tag removed]", text, flags=re.IGNORECASE)
    return f"<untrusted_email>\n{safe}\n</untrusted_email>"
