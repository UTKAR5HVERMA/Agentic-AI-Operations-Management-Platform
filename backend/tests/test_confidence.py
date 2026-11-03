"""Confidence formula and thresholds (BACKEND.md §7.4)."""

from __future__ import annotations

import pytest

from app.agents.confidence import band, cap_option_confidence, extraction_confidence, overall
from app.agents.extraction import is_grounded
from app.agents.risk import reconcile


def test_overall_weights() -> None:
    assert overall(1, 1, 1, 1) == 1.0
    assert overall(0.5, 0.7, 0.75, 0.6) == pytest.approx(
        0.4 * 0.5 + 0.2 * 0.7 + 0.2 * 0.75 + 0.2 * 0.6
    )


def test_missing_required_field_counts_as_zero() -> None:
    fields = {"item": {"confidence": 0.9}, "location": {"confidence": 0.9}}
    assert extraction_confidence(fields, ["item", "location", "supplier"]) == pytest.approx(0.6)


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.85, "recommended"),
        (0.80, "recommended"),
        (0.79, "needs_review"),
        (0.50, "needs_review"),
        (0.49, "withheld"),
    ],
)
def test_bands(score: float, expected: str) -> None:
    assert band(score, auto=0.80, block=0.50) == expected


def test_option_confidence_capped_by_evidence_and_fallback() -> None:
    assert cap_option_confidence(0.9, extraction=0.2, from_fallback=False) == 0.5
    assert cap_option_confidence(0.9, extraction=0.9, from_fallback=True) == 0.6


def test_grounding_requires_evidence_in_source() -> None:
    source = "Our supplier said 500 display units for Pune are delayed by 10 days."
    assert is_grounded("500 display units", source)
    assert is_grounded("500 display  Units", source)  # whitespace/case-insensitive
    assert not is_grounded("700 display units for Mumbai", source)
    assert not is_grounded(None, source)


def _risk(level: str, conf: float = 0.8) -> dict:
    return {
        "risk_level": level,
        "urgency": 3,
        "impact": 3,
        "factors": [],
        "rationale": level,
        "confidence": conf,
    }


@pytest.mark.parametrize(
    ("ops", "fin", "level", "gap", "disagreement"),
    [
        ("high", "high", "high", 0, False),
        ("medium", "high", "high", 1, False),
        ("low", "critical", "critical", 3, True),
    ],
)
def test_reconciler_takes_higher_risk(
    ops: str, fin: str, level: str, gap: int, disagreement: bool
) -> None:
    reconciled, got_gap = reconcile(_risk(ops, 0.9), _risk(fin, 0.6))
    assert reconciled["risk_level"] == level and got_gap == gap
    assert reconciled["disagreement"] is disagreement
    assert reconciled["confidence"] == 0.6  # min of both


def test_numeric_value_must_appear_in_its_evidence() -> None:
    from app.agents.extraction import value_supported

    assert value_supported("quantity_required", 2000, "2,000 shelving racks")
    assert value_supported("cost_impact", 560000, "₹5,60,000 in total")
    # Evidence exists in the email but does not support the value (unsupported LLM output).
    assert not value_supported("quantity_available", 2000, "ShelfMart can supply at ₹280 per unit")
    assert value_supported("location", "Pune", "unrelated")  # only numeric fields are checked
    assert value_supported("delay_days", 5, "delayed by five days")  # number words count
    assert not value_supported("delay_days", 5, "delayed by ten days")


def test_llm_iso_datetimes_keep_their_time() -> None:
    from datetime import datetime

    from app.normalize import IST, parse_date

    received = datetime(2026, 11, 2, 10, 0, tzinfo=IST)
    parsed = parse_date("2026-11-03T12:00:00", received)
    assert parsed is not None and parsed["start"].startswith("2026-11-03T12:00")
    assert parse_date("2026-11-20", received)["start"].startswith("2026-11-20T18:00")


def test_hedged_evidence_caps_llm_confidence() -> None:
    from app.agents.extraction import evidence_hedge

    source = (
        "I heard the racks for Delhi might possibly be delayed, maybe 50 units? Store opens soon."
    )
    assert evidence_hedge("racks for Delhi", source) <= 0.125  # 3+ hedges in that sentence
    assert evidence_hedge("Store opens soon", source) == 1.0
