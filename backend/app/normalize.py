"""Deterministic normalisation of extracted values (dates, cities, items, numbers).

Used for both LLM and fallback extractions so that downstream agents see identical shapes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

CITY_REGION: dict[str, str] = {
    "Pune": "West",
    "Mumbai": "West",
    "Ahmedabad": "West",
    "Nagpur": "West",
    "Indore": "West",
    "Delhi": "North",
    "Bengaluru": "South",
    "Hyderabad": "South",
    "Chennai": "South",
}
CITY_ALIASES = {"bangalore": "Bengaluru", "new delhi": "Delhi", "bombay": "Mumbai"}
DEFAULT_REGION = "West"
# TRADE-OFF: "by tomorrow" with no time means end of business day (18:00 IST).
END_OF_BUSINESS = time(18, 0)

_MONTHS = {
    m: i + 1
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ]
    )
    for m in names
}
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))
_TIME_RE = r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)"

DATE_PATTERNS: list[tuple[str, str]] = [
    ("time_today", rf"(?:{_TIME_RE}\s*today|today\s*(?:by|at|before)?\s*{_TIME_RE})"),
    ("tomorrow", rf"tomorrow(?:\s*(?:by|at|before)?\s*{_TIME_RE})?"),
    ("today", r"\b(?:today|eod|end of (?:the )?day)\b"),
    ("next_week", r"\bnext week\b"),
    ("this_week", r"\b(?:this week|end of (?:the|this) week)\b"),
    ("in_days", r"\b(?:in|within)\s+(\d{1,2})\s+days?\b"),
    ("day_month", rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_RE})\b"),
    ("month_day", rf"\b({_MONTH_RE})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b"),
    ("iso_datetime", r"\b(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})"),
    ("iso", r"\b(\d{4})-(\d{2})-(\d{2})(?!\d)"),
    ("weekday", rf"\b(?:this\s+|next\s+|by\s+|on\s+)?({'|'.join(_WEEKDAYS)})\b"),
]


@dataclass(frozen=True)
class DateMatch:
    text: str
    start: int
    end: int
    value: dict[str, Any]  # {"start": iso, "end": iso, "ambiguous": bool}


def _iso(d: datetime) -> str:
    return d.astimezone(IST).isoformat()


def _at(day: date, t: time) -> datetime:
    return datetime.combine(day, t, tzinfo=IST)


def _clock(hour: str | None, minute: str | None, ampm: str | None) -> time | None:
    if hour is None or ampm is None:
        return None
    h = int(hour) % 12 + (12 if ampm.lower() == "pm" else 0)
    return time(h, int(minute or 0))


def _point(moment: datetime, ambiguous: bool = False) -> dict[str, Any]:
    return {"start": _iso(moment), "end": _iso(moment), "ambiguous": ambiguous}


def _range(start: datetime, end: datetime) -> dict[str, Any]:
    return {"start": _iso(start), "end": _iso(end), "ambiguous": True}


def _resolve(kind: str, m: re.Match[str], received: datetime) -> dict[str, Any] | None:
    local = received.astimezone(IST)
    today = local.date()
    g = m.groups()
    if kind == "time_today":
        t = _clock(g[0], g[1], g[2]) or _clock(g[3], g[4], g[5])
        return _point(_at(today, t or END_OF_BUSINESS))
    if kind == "tomorrow":
        t = _clock(g[0], g[1], g[2])
        return _point(_at(today + timedelta(days=1), t or END_OF_BUSINESS), ambiguous=t is None)
    if kind == "today":
        return _point(_at(today, END_OF_BUSINESS), ambiguous=True)
    if kind in {"next_week", "this_week"}:
        monday = today - timedelta(days=today.weekday())
        if kind == "next_week":
            monday += timedelta(days=7)
        start = max(monday, today)
        return _range(_at(start, time(0, 0)), _at(monday + timedelta(days=6), time(23, 59)))
    if kind == "in_days":
        return _point(_at(today + timedelta(days=int(g[0])), END_OF_BUSINESS))
    if kind in {"day_month", "month_day"}:
        day_s, month_s = (g[0], g[1]) if kind == "day_month" else (g[1], g[0])
        return _calendar(int(day_s), _MONTHS[month_s.lower()], today)
    if kind == "iso_datetime":  # LLMs often reformat dates; naive times are read as IST
        try:
            moment = datetime(int(g[0]), int(g[1]), int(g[2]), int(g[3]), int(g[4]), tzinfo=IST)
        except ValueError:
            return None
        return _point(moment)
    if kind == "iso":
        try:
            return _point(_at(date(int(g[0]), int(g[1]), int(g[2])), END_OF_BUSINESS))
        except ValueError:
            return None
    if kind == "weekday":
        target = _WEEKDAYS.index(g[0].lower())
        ahead = (target - today.weekday()) % 7
        if m.group(0).lower().startswith("next"):
            ahead += 7 if ahead == 0 else 0
        return _point(_at(today + timedelta(days=ahead), END_OF_BUSINESS))
    return None


def _calendar(day: int, month: int, today: date) -> dict[str, Any] | None:
    try:
        candidate = date(today.year, month, day)
    except ValueError:
        return None
    if (today - candidate).days > 30:  # "5 Jan" written in December means next year
        candidate = candidate.replace(year=today.year + 1)
    return _point(_at(candidate, END_OF_BUSINESS))


def find_dates(text: str, received: datetime) -> list[DateMatch]:
    """All non-overlapping date expressions in `text`, in reading order."""
    found: list[DateMatch] = []
    taken: list[tuple[int, int]] = []
    for kind, pattern in DATE_PATTERNS:
        for m in re.finditer(pattern, text, flags=re.IGNORECASE):
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue
            value = _resolve(kind, m, received)
            if value is None:
                continue
            taken.append((m.start(), m.end()))
            found.append(DateMatch(m.group(0), m.start(), m.end(), value))
    return sorted(found, key=lambda d: d.start)


def parse_date(text: str, received: datetime) -> dict[str, Any] | None:
    matches = find_dates(text, received)
    return matches[0].value if matches else None


NUMBER_WORDS = {
    w: i
    for i, w in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
        "fifteen sixteen seventeen eighteen nineteen twenty".split()
    )
} | {"thirty": 30, "forty": 40, "fifty": 50, "hundred": 100}
NUMBER_WORDS_ALT = "|".join(NUMBER_WORDS)
NUMBER_WORD_RE = re.compile(rf"\b({NUMBER_WORDS_ALT})\b", re.IGNORECASE)


def to_int(text: str | None) -> int | None:
    """'2,000' → 2000, '₹5,60,000' → 560000, 'around 50 units' → 50, 'five days' → 5."""
    if text is None:
        return None
    if m := re.search(r"\d[\d,]*", str(text)):
        return int(m.group(0).replace(",", ""))
    # TRADE-OFF: single number words only ("five", "twenty"); compounds need digits.
    word = NUMBER_WORD_RE.search(str(text))
    return NUMBER_WORDS[word.group(1).lower()] if word else None


def canonical_city(text: str | None) -> str | None:
    if not text:
        return None
    lowered = text.lower()
    for alias, city in CITY_ALIASES.items():
        if alias in lowered:
            return city
    for city in CITY_REGION:
        if re.search(rf"\b{city.lower()}\b", lowered):
            return city
    return None


def region_for(city: str | None) -> str | None:
    return CITY_REGION.get(city) if city else None


def _singular(word: str) -> str:
    word = word.lower()
    return word[:-1] if word.endswith("s") and not word.endswith("ss") else word


def _name_tokens(item_name: str) -> list[str]:
    return [_singular(t) for t in re.findall(r"[A-Za-z]+", item_name) if len(t) > 1]


def match_sku(text: str | None, catalog: dict[str, str]) -> str | None:
    """Best SKU for free text. `catalog` maps sku → item name; the head noun must match."""
    if not text:
        return None
    words = {_singular(w) for w in re.findall(r"[A-Za-z]+", text)}
    best: tuple[int, str] | None = None
    for sku, name in catalog.items():
        tokens = _name_tokens(name)
        if not tokens or tokens[-1] not in words:
            continue
        score = sum(t in words for t in tokens)
        if best is None or score > best[0]:
            best = (score, sku)
    return best[1] if best else None


def normalize_field(
    field: str, value: str | None, received: datetime, catalog: dict[str, str]
) -> tuple[Any, bool]:
    """Return (normalized_value, ambiguous)."""
    if value is None:
        return None, False
    if field in {"quantity_required", "quantity_available", "delay_days", "cost_impact"}:
        return to_int(value), False
    if field == "location":
        return canonical_city(value), False
    if field == "item":
        return match_sku(value, catalog), False
    if field in {"required_date", "approval_deadline", "original_delivery_date"}:
        parsed = parse_date(value, received)
        return parsed, bool(parsed and parsed["ambiguous"])
    return value.strip(), False
