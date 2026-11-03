"""Overall confidence (BACKEND.md §7.4). Never the LLM's self-report alone.

overall = 0.4·extraction + 0.2·data + 0.2·risk_agreement + 0.2·recommendation
"""

from __future__ import annotations

from typing import Any

WEIGHTS = {"extraction": 0.4, "data": 0.2, "risk": 0.2, "recommendation": 0.2}
# A recommendation can't be more confident than the facts it rests on.
REC_HEADROOM_OVER_EXTRACTION = 0.3
FALLBACK_CAP = 0.6


def extraction_confidence(fields: dict[str, dict[str, Any]], required: list[str]) -> float:
    """Mean field confidence over required fields; a missing required field counts as 0."""
    if not required:
        return 1.0
    return sum(fields.get(name, {}).get("confidence", 0.0) for name in required) / len(required)


def overall(extraction: float, data: float, risk: float, recommendation: float) -> float:
    parts = {"extraction": extraction, "data": data, "risk": risk, "recommendation": recommendation}
    return round(sum(WEIGHTS[k] * v for k, v in parts.items()), 4)


def band(score: float, auto: float, block: float) -> str:
    """'recommended' ≥ auto; 'needs_review' between; 'withheld' below block."""
    if score >= auto:
        return "recommended"
    if score >= block:
        return "needs_review"
    return "withheld"


def cap_option_confidence(base: float, extraction: float, *, from_fallback: bool) -> float:
    capped = min(base, extraction + REC_HEADROOM_OVER_EXTRACTION)
    return round(min(capped, FALLBACK_CAP) if from_fallback else capped, 4)
