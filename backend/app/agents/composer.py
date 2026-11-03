"""Email composer: turns a requester's rough notes into a clean request email (subject + body).

The LLM only rewrites wording. Numbers must come from the notes, or be a verifiable sum or
difference of two of them (e.g. a shortfall). Anything else gets one repair retry, then a
deterministic template (BACKEND.md §7.5).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.llm import guard, prompts
from app.llm.client import LLMClient

SUBJECT_MAX = 100
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_HARMLESS = {"0", "00"}  # "4 PM" → "4:00 PM" is a reformat, not a new fact


class ComposeOut(BaseModel):
    subject: str = Field(min_length=3, max_length=300)
    body: str = Field(min_length=10, max_length=8000)


@dataclass(frozen=True)
class ComposedEmail:
    subject: str
    body: str
    model: str
    note: str | None = None  # why the template was used, if it was


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in _NUMBER.findall(text)} - _HARMLESS


def unsupported_numbers(source: str, output: str) -> set[str]:
    """Numbers in the output that are neither in the source nor a sum/difference of two of its
    numbers (a shortfall 500 - 120 = 380 is a verifiable calculation, not a new fact)."""
    src = _numbers(source)
    values = [float(n) for n in src]
    derivable = {a + b for a in values for b in values} | {
        abs(a - b) for a in values for b in values
    }
    return {n for n in _numbers(output) - src if float(n) not in derivable}


def introduces_new_numbers(source: str, output: str) -> bool:
    return bool(unsupported_numbers(source, output))


def _template(subject: str | None, text: str, sender: str, note: str) -> ComposedEmail:
    first_sentence = re.split(r"(?<=[.!?])\s|\n", text.strip(), maxsplit=1)[0]
    title = (subject or first_sentence).strip()[:SUBJECT_MAX]
    body = f"Hi Operations Team,\n\n{text.strip()}\n\nRegards,\n{sender}"
    return ComposedEmail(subject=title, body=body, model="template", note=note)


def _ask(llm: LLMClient, sender: str, notes: str, avoid: set[str]) -> ComposeOut | None:
    extra = (
        f"\nDo NOT include these numbers; they are not in the notes: {sorted(avoid)}"
        if avoid
        else ""
    )
    result = llm.call_json(
        prompt_name="compose_request",
        system=prompts.COMPOSE_REQUEST + extra,
        user=f"SENDER: {sender}\n" + guard.wrap_untrusted(notes),
        schema=ComposeOut,
        temperature=0.3,
    )
    return result.data


class ReplyOut(BaseModel):
    body: str = Field(min_length=3, max_length=4000)


def _ask_reply(
    llm: LLMClient, sender: str, question: str, notes: str, avoid: set[str]
) -> ReplyOut | None:
    extra = f"\nDo NOT include these numbers; they are not in the answer: {sorted(avoid)}"
    result = llm.call_json(
        prompt_name="compose_reply",
        system=prompts.COMPOSE_REPLY + (extra if avoid else ""),
        user=f"SENDER: {sender}\nQUESTION:\n{question[:2000]}\n" + guard.wrap_untrusted(notes),
        schema=ReplyOut,
        temperature=0.3,
    )
    return result.data


def compose_reply(question: str, text: str, sender: str, llm: LLMClient) -> ComposedEmail:
    """AI-written reply to the team's question from the requester's rough answer. Numbers may
    only come from the answer or the question (e.g. "the 300 racks"); otherwise a template."""
    source = f"{question}\n{text}"
    template = ComposedEmail(
        subject="",
        body=f"Hi Operations Team,\n\n{text.strip()}\n\nRegards,\n{sender}",
        model="template",
    )
    out = _ask_reply(llm, sender, question, text, set())
    if out is None:
        return ComposedEmail(
            **{**template.__dict__, "note": "AI unavailable; tidied with a template"}
        )
    bad = unsupported_numbers(source, out.body)
    if bad:
        out = _ask_reply(llm, sender, question, text, bad)
        if out is None or unsupported_numbers(source, out.body):
            return ComposedEmail(
                **{
                    **template.__dict__,
                    "note": "AI added facts not in your text, so a template was used",
                }
            )
    return ComposedEmail("", out.body.strip(), llm.model)


def compose(subject: str | None, text: str, sender: str, llm: LLMClient) -> ComposedEmail:
    notes = f"Subject: {subject or '(none)'}\n\n{text}"
    out = _ask(llm, sender, notes, set())
    if out is None:
        return _template(subject, text, sender, "AI unavailable; tidied with a template")
    bad = unsupported_numbers(notes, f"{out.subject} {out.body}")
    if bad:  # one repair retry, telling the model exactly what it invented
        out = _ask(llm, sender, notes, bad)
        if out is None or unsupported_numbers(notes, f"{out.subject} {out.body}"):
            return _template(
                subject, text, sender, "AI added facts not in your text, so a template was used"
            )
    return ComposedEmail(out.subject.strip()[:SUBJECT_MAX], out.body.strip(), llm.model)
