"""Rule-based fallback engine (BACKEND.md §7.7): extraction, classification, multi-issue split
and heuristic risk. Used when LLM_MODE=mock, when the LLM is down, or when its output fails
validation. Outputs carry source/model "fallback" and are confidence-capped downstream.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.enums import Category, RiskLevel
from app.normalize import CITY_REGION, NUMBER_WORDS_ALT, find_dates

UNIT_NOUNS = r"units?|pcs|pieces|racks?|terminals?|signs?|signage|scanners?|items?"
_QTY = re.compile(
    rf"(?<![₹\d,.])(\d{{1,3}}(?:,\d{{2,3}})+|\d+)\s+((?:[A-Za-z][\w-]*\s+){{0,3}}?)({UNIT_NOUNS})\b",
    re.IGNORECASE,
)
_SHORT_BY = re.compile(r"\bshort(?:fall)?\s+(?:by|of)\s+(\d[\d,]*)\s*(?:units?)?", re.IGNORECASE)
_AVAILABLE_HINT = re.compile(
    r"\b(available|in stock|on hand|current stock|stock is|we have|have only|only have|left)\b",
    re.IGNORECASE,
)
_DAYS = rf"(\d{{1,3}}|{NUMBER_WORDS_ALT})"
_DELAY = re.compile(rf"\bdelay(?:ed)?\b[^.\n]*?\bby\s+{_DAYS}\s*days?", re.IGNORECASE)
_DELAY_ALT = re.compile(rf"\b{_DAYS}[- ]day delay", re.IGNORECASE)
_SUPPLIER = re.compile(r"\bsupplier\s+([A-Z][\w&]+(?:\s+[A-Z][\w&]+)?)")
_EVENT = re.compile(
    r"\b(store launch|launch|store opening|grand opening|store refits?|refits?|bulk order|"
    r"corporate (?:client )?order|customer order|promotion)\b",
    re.IGNORECASE,
)
_MONEY = re.compile(r"(?:₹|rs\.?\s?|inr\s?)\s?(\d[\d,]*)", re.IGNORECASE)
_REQUEST = re.compile(
    r"\b(please|kindly|can (?:someone|you)|could you|need you to|we need|advise)\b", re.IGNORECASE
)
_ORIGINAL_CONTEXT = re.compile(
    r"\boriginal(?:ly)?\b|\bwas (?:due|scheduled)\b|\bscheduled delivery\b", re.IGNORECASE
)
_APPROVAL_CONTEXT = re.compile(r"\bapprov|\bsign[- ]?off\b|\bdecision\b", re.IGNORECASE)
_HEDGES = re.compile(
    r"\b(maybe|might|possibly|perhaps|not sure|unsure|around|approximately|roughly|or so|"
    r"i think|i heard|could be|unconfirmed|nobody has confirmed|probably)\b",
    re.IGNORECASE,
)
_LIST_ITEM = re.compile(r"^\s*(?:\d+[).]|[-•*])\s+(.+)$", re.MULTILINE)

CATEGORY_KEYWORDS: dict[Category, list[str]] = {
    Category.DELIVERY_DELAY: [r"\bdelay", r"\blate\b", r"\bpushed back\b", r"\brevised delivery"],
    Category.CUSTOMER_COMMITMENT: [
        r"\bcustomer\b",
        r"\bclient\b",
        r"\bpromised\b",
        r"\bcorporate order\b",
        r"\bbulk order\b",
    ],
    Category.INVENTORY_SHORTAGE: [
        r"\bshort\b",
        r"\bshortage\b",
        r"\bout of stock\b",
        r"\brunning low\b",
        r"\bstock-?out\b",
    ],
    Category.SUPPLIER_ISSUE: [
        r"\binvoice\b",
        r"\bdispute",
        r"\bbilled\b",
        r"\bovercharg",
        r"\bquality issue",
    ],
    Category.URGENT_APPROVAL: [r"\bapproval needed\b", r"\bneeds? approval\b", r"\bsign-?off\b"],
}


@dataclass
class FieldGuess:
    value: str | None
    evidence: str | None
    confidence: float  # self-score before grounding/source factors


@dataclass
class FallbackExtraction:
    fields: dict[str, FieldGuess] = field(default_factory=dict)
    category: Category = Category.OTHER
    requested_actions: list[str] = field(default_factory=list)
    issues_list: list[dict[str, str]] = field(default_factory=list)

    @property
    def is_multi_issue(self) -> bool:
        return len(self.issues_list) >= 2


_SENTENCE_END = ".?!\n"


def sentence_at(text: str, pos: int) -> str:
    """The sentence containing `pos` (bounded by . ? ! or a newline)."""
    start = max(text.rfind(ch, 0, pos) for ch in _SENTENCE_END) + 1
    ends = [i for i in (text.find(ch, pos) for ch in _SENTENCE_END) if i != -1]
    return text[start : min(ends) if ends else len(text)]


def hedge_score(sentence: str) -> float:
    return 0.5 ** min(len(_HEDGES.findall(sentence)), 3)


def _guess(text: str, m: re.Match[str], value: str, group: int = 0) -> FieldGuess:
    return FieldGuess(value, m.group(group).strip(), hedge_score(sentence_at(text, m.start())))


def classify(text: str) -> Category:
    scores = {
        cat: sum(len(re.findall(p, text, re.IGNORECASE)) for p in pats)
        for cat, pats in CATEGORY_KEYWORDS.items()
    }
    best = max(scores.values())
    if best == 0:
        return Category.OTHER
    return next(cat for cat in CATEGORY_KEYWORDS if scores[cat] == best)  # dict order = tie-break


def split_issues(text: str) -> list[dict[str, str]]:
    items = [m.group(1).strip() for m in _LIST_ITEM.finditer(text)]
    if len(items) < 2:
        return []
    return [
        {"title": item[:80].rstrip(" .,"), "text": item, "category": str(classify(item))}
        for item in items
    ]


def _quantities(text: str, out: dict[str, FieldGuess], catalog: dict[str, str]) -> None:
    for m in _QTY.finditer(text):
        sentence = sentence_at(text, m.start())
        number = m.group(1).replace(",", "")
        window = text[max(m.start() - 25, 0) : m.end() + 35]
        if _AVAILABLE_HINT.search(window):
            out.setdefault("quantity_available", _guess(text, m, number))
        else:
            out.setdefault("quantity_required", _guess(text, m, number))
            descriptive = (m.group(2) + m.group(3)).strip()
            if m.group(2).strip() or m.group(3).lower() not in {"unit", "units", "items", "item"}:
                out.setdefault("item", FieldGuess(descriptive, descriptive, hedge_score(sentence)))
    if "quantity_required" not in out and (m := _SHORT_BY.search(text)):
        out["quantity_required"] = _guess(text, m, m.group(1).replace(",", ""))
    if "item" not in out:
        _item_from_catalog(text, out, catalog)


def _item_from_catalog(text: str, out: dict[str, FieldGuess], catalog: dict[str, str]) -> None:
    for name in catalog.values():
        words = [w for w in re.findall(r"[A-Za-z]+", name) if len(w) > 1]
        if not words:
            continue
        pattern = r"\b" + r"\s+".join(re.escape(w) for w in words[-2:]) + r"s?\b"
        if m := re.search(pattern, text, re.IGNORECASE):
            out["item"] = _guess(text, m, m.group(0))
            return


def _location(text: str, out: dict[str, FieldGuess]) -> None:
    cities = "|".join(CITY_REGION)
    pattern = rf"\b({cities}|Bangalore)\b(?:\s+(?:store|stores|warehouse|WH|office|outlet))?"
    if m := re.search(pattern, text, re.IGNORECASE):
        out["location"] = _guess(text, m, m.group(1))


def _supplier(text: str, out: dict[str, FieldGuess], suppliers: list[str]) -> None:
    if m := _SUPPLIER.search(text):
        out["supplier"] = _guess(text, m, m.group(1), group=0)
        return
    for name in suppliers:
        if m := re.search(rf"\b{re.escape(name)}\b", text):
            out["supplier"] = _guess(text, m, name)
            return


def _dates(text: str, received: datetime, out: dict[str, FieldGuess]) -> None:
    for d in find_dates(text, received):
        sentence = sentence_at(text, d.start)
        key = (
            "original_delivery_date"
            if _ORIGINAL_CONTEXT.search(sentence)
            else "approval_deadline"
            if _APPROVAL_CONTEXT.search(sentence)
            else "required_date"
        )
        conf = hedge_score(sentence) * (0.7 if d.value["ambiguous"] else 1.0)
        out.setdefault(key, FieldGuess(d.text, d.text, conf))


def _simple_fields(text: str, out: dict[str, FieldGuess]) -> list[str]:
    if m := (_DELAY.search(text) or _DELAY_ALT.search(text)):
        out["delay_days"] = _guess(text, m, m.group(1))
    if m := _EVENT.search(text):
        out["event"] = _guess(text, m, m.group(1).lower())
    if m := _MONEY.search(text):
        out["cost_impact"] = _guess(text, m, m.group(1).replace(",", ""))
    actions = []
    for m in _REQUEST.finditer(text):
        sentence = sentence_at(text, m.start()).strip()
        if sentence and sentence not in actions:
            actions.append(sentence)
    if actions:
        out["requested_action"] = FieldGuess(actions[0], actions[0], hedge_score(actions[0]))
    return actions


def extract(
    text: str, received: datetime, catalog: dict[str, str], suppliers: list[str]
) -> FallbackExtraction:
    out: dict[str, FieldGuess] = {}
    _quantities(text, out, catalog)
    _location(text, out)
    _supplier(text, out, suppliers)
    _dates(text, received, out)
    actions = _simple_fields(text, out)
    return FallbackExtraction(
        fields=out,
        category=classify(text),
        requested_actions=actions,
        issues_list=split_issues(text),
    )


# ---------------------------------------------------------------- heuristic risk (§7.7)


def level_from_score(score: float) -> RiskLevel:
    if score >= 20:
        return RiskLevel.CRITICAL
    if score >= 12:
        return RiskLevel.HIGH
    if score >= 6:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def urgency_from_hours(hours: float | None) -> int:
    if hours is None:
        return 3
    if hours < 24:
        return 5
    if hours <= 72:
        return 4
    if hours <= 168:
        return 3
    if hours <= 336:
        return 2
    return 1


def _deadline_factor(hours: float | None) -> str:
    if hours is None:
        return "No firm deadline stated"
    if hours < 0:
        return f"Deadline passed {abs(hours):.0f}h ago"
    return f"Deadline in {hours:.0f}h"


def ops_risk(facts: dict[str, Any]) -> dict[str, Any]:
    urgency = urgency_from_hours(facts.get("hours_to_deadline"))
    pct = facts.get("shortfall_pct")
    impact = 1 if pct is None else 4 if pct >= 0.5 else 3 if pct >= 0.2 else 2 if pct > 0 else 1
    factors = [_deadline_factor(facts.get("hours_to_deadline"))]
    if pct is not None:
        source = (
            " (stock from inventory, not stated)"
            if facts.get("available_source") == ("inventory")
            else ""
        )
        factors.append(f"Shortfall {pct:.0%} of required quantity{source}")
    if facts.get("delay_vs_deadline") == "meets":
        impact = 1
        factors.append("Revised delivery still arrives by the required date")
    if facts.get("delay_vs_deadline") == "unclear":
        impact = max(impact - 1, 1)
        factors.append("Original delivery date unknown — delay may not breach the deadline")
    for kw in ("launch", "customer", "penalty"):
        if facts.get(f"mentions_{kw}"):
            impact = min(impact + 1, 5)
            factors.append(f"Business dependency: {kw}")
    level = level_from_score(urgency * impact)
    return {
        "urgency": urgency,
        "impact": impact,
        "risk_level": level,
        "factors": factors,
        "rationale": f"Urgency {urgency}/5 from time to deadline; impact {impact}/5 from "
        f"stock gap and business dependencies.",
        "confidence": 1.0,
    }


def financial_risk(facts: dict[str, Any]) -> dict[str, Any]:
    exposure = int(facts.get("cheapest_cover_cost_inr") or 0) + int(
        facts.get("penalty_exposure_inr") or 0
    )
    if facts.get("stated_cost_inr"):
        exposure = max(exposure, int(facts["stated_cost_inr"]))
    impact = 5 if exposure > 200_000 else 4 if exposure > 50_000 else 2 if exposure > 0 else 1
    urgency = urgency_from_hours(facts.get("hours_to_deadline"))
    level = (
        RiskLevel.CRITICAL
        if exposure > 200_000
        else RiskLevel.HIGH
        if exposure > 50_000
        else RiskLevel.MEDIUM
        if exposure > 0
        else RiskLevel.LOW
    )
    return {
        "urgency": urgency,
        "impact": impact,
        "risk_level": level,
        "factors": [f"Cost exposure ₹{exposure:,}"],
        "rationale": f"Estimated cost exposure ₹{exposure:,} from covering the shortfall and "
        f"any stated penalties.",
        "confidence": 1.0,
        "cost_exposure_inr": exposure,
    }
