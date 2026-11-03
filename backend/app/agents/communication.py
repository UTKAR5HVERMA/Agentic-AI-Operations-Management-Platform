"""CommsAgent: drafts only — a human approves & sends customer-facing messages.

Drafts are built from FACTS derived from the sanitized text, so quarantined content never
reaches a draft. Template drafts are the fallback (and are used for system notices).
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from app.agents.common import Timer, agent_output, ctx
from app.agents.composer import unsupported_numbers
from app.agents.state import CaseState
from app.agents.validation import FIELD_LABELS
from app.enums import CommType
from app.llm import prompts
from app.llm.client import LLMClient
from app.normalize import ist_label

AGENT = "communication"
SIGNATURE = "\n\nRegards,\nOperations Team (OpsPilot)"
LLM_TYPES = {
    CommType.STAKEHOLDER_UPDATE,
    CommType.CLARIFICATION,
    CommType.CLOSURE,
    CommType.APPROVAL_REQUEST,
    CommType.ESCALATION,
    CommType.REMINDER,
}
AUDIENCE = {
    CommType.APPROVAL_REQUEST: "the Regional Manager who must decide this approval",
    CommType.ESCALATION: "the person who must now decide this approval",
    CommType.REMINDER: "the approver",
}
# Never given to the LLM: the forwarded original email is untrusted text, and the Operations
# Team's note is a human's words. Both are appended verbatim after the AI-written part.
_VERBATIM_KEYS = {"original_text", "original_from", "original_channel", "original_received_at"}
_TIME_KEYS = {"due_at", "previous_due", "deadline_at", "required_by"}


class DraftOut(BaseModel):
    subject: str = Field(max_length=300)
    body: str = Field(max_length=5000)


# "[Your Name]", "[Date]"… — an LLM draft must never go out with template holes.
_PLACEHOLDER = re.compile(
    r"^[ \t]*\[[^\]\n]{1,40}\][ \t]*\n?|\[(?:your )?(?:name|date)\]", re.I | re.M
)


CLARIFY_TYPES = {"missing_info", "ambiguity", "conflict"}


def _short_date(iso: Any) -> str:
    try:
        return datetime.fromisoformat(str(iso)).strftime("%d %b")
    except ValueError:
        return "the required date"


def _question(i: dict[str, Any]) -> str:
    """One requester-facing question that says why we ask (not the internal issue text)."""
    d, f = i.get("details") or {}, i["field"]
    label = FIELD_LABELS.get(f, f.replace("_", " "))
    if i["type"] == "conflict":
        return (
            f"{label.capitalize()}: your message says {d.get('email_value')}, but our inventory "
            f"shows {d.get('inventory_value')} at {d.get('location')}. Which figure is correct?"
        )
    if d.get("assumption") == "inventory_stock_usable":
        return (
            f"Stock on hand: our inventory shows {d.get('inventory_value')} free at "
            f"{d.get('location')}. How many of these can be used for this request?"
        )
    if f == "original_delivery_date":
        return (
            "Original delivery date: when was the delivery due before the delay? We need it to "
            f"check whether it still arrives by {_short_date(d.get('required_by'))}."
        )
    if i["type"] == "ambiguity":
        return f"{label.capitalize()}: please confirm the exact {label}."
    return f"{label.capitalize()}: this was not in your message — please provide it."


def clarify_questions(issues: list[dict[str, Any]]) -> list[str]:
    """Every open question for the requester, one per field, with its context."""
    seen: set[str] = set()
    out = []
    for i in issues:
        field = i.get("field")
        if i.get("type") not in CLARIFY_TYPES or not field or field in seen:
            continue
        if i.get("status", "open") != "open":
            continue
        seen.add(field)
        out.append(_question(i))
    return out


def _inr(amount: Any) -> str:
    return f"₹{int(amount):,}" if amount is not None else "n/a"


def _original_block(f: dict[str, Any]) -> str:
    """The requester's original message, quoted under a forwarded approval request."""
    if not f.get("original_text"):
        return ""
    quoted = "\n".join(f"> {line}" for line in str(f["original_text"]).splitlines())
    return (
        f"\n\n---------- Original request ----------\nFrom: {f.get('original_from') or 'unknown'}"
        f" ({f.get('original_channel')})\nReceived: {ist_label(f.get('original_received_at'))}\n"
        f"Subject: {f.get('subject')}\n\n{quoted}"
    )


def _note_block(f: dict[str, Any]) -> str:
    note = f.get("routing_note")
    return f"\n\nNote from the Operations Team:\n{note}" if note else ""


def _advice_line(f: dict[str, Any]) -> str:
    advice = f.get("ai_suggestion")
    return f"\nAI suggestion (advice only, the decision is yours): {advice}" if advice else ""


def _template(comm_type: CommType, f: dict[str, Any]) -> tuple[str, str]:
    ref, subject = f.get("ref", ""), f.get("subject", "")
    greeting = f"Hi {f.get('recipient_name') or 'team'},\n\n"
    what = " ".join(
        str(x)
        for x in (
            f.get("quantity_required"),
            f.get("item"),
            f"for {f['location']}" if f.get("location") else None,
        )
        if x
    )
    if comm_type == CommType.CLARIFICATION:
        if subs := f.get("sub_issues"):  # edge 4: one request, several issues
            listed = "\n".join(f"{n}. {title}" for n, title in enumerate(subs, start=1))
            return (
                f"[{ref}] Please confirm priorities: {subject}",
                greeting + f'Your message "{subject}" raises {len(subs)} separate issues:\n'
                f"{listed}\n\nWe are handling all of them under {ref}. Please tell us which is "
                "most urgent and the action you expect for each." + SIGNATURE,
            )
        if questions := f.get("questions"):
            listed = "\n".join(f"{n}. {q}" for n, q in enumerate(questions, start=1))
            return (
                f"[{ref}] A few questions about: {subject}",
                greeting + f'Thanks for your message about "{subject}". Before we decide on '
                f"the next step we need to check:\n{listed}\n\nPlease reply to each point; a "
                "short answer is fine." + SIGNATURE,
            )
        missing = (
            ", ".join(FIELD_LABELS.get(m, m) for m in f.get("missing", []))
            or "the details of the issue"
        )
        return (
            f"[{ref}] More information needed: {subject}",
            greeting + f'Thanks for your message about "{subject}". To assess it safely we '
            f"need: {missing}. Please reply with these details so we can act on it." + SIGNATURE,
        )
    if comm_type == CommType.APPROVAL_REQUEST:
        return (
            f"[{ref}] Approval needed: {f.get('recommendation')}",
            greeting + f"Please review {ref} ({subject}).\nProposed action: "
            f"{f.get('recommendation')}\nAmount: {_inr(f.get('amount_inr'))}\nWhy approval is "
            f"required: {'; '.join(f.get('reasons', []))}\nDecision needed by: "
            f"{ist_label(f.get('due_at'))}." + _advice_line(f) + SIGNATURE,
        )
    if comm_type == CommType.ESCALATION:
        why = (
            f"was forwarded to you by the Regional Manager: {f.get('escalation_reason')}"
            if f.get("forwarded_by_manager")
            else f"was not decided by {ist_label(f.get('previous_due'))}, so it has been "
            f"escalated to you (level {f.get('level')})"
        )
        return (
            f"[{ref}] ESCALATION: decision needed — {subject}",
            greeting + f'The approval for "{f.get("recommendation")}" '
            f"({_inr(f.get('amount_inr'))}) {why}. Please decide by "
            f"{ist_label(f.get('due_at'))}." + _advice_line(f) + SIGNATURE,
        )
    if comm_type == CommType.REMINDER:
        return (
            f"[{ref}] Reminder: approval due {ist_label(f.get('due_at'))}",
            greeting + f'Reminder: "{f.get("recommendation")}" ({_inr(f.get("amount_inr"))}) '
            f"awaits your decision by {ist_label(f.get('due_at'))}." + SIGNATURE,
        )
    if comm_type == CommType.CANCELLATION:
        return (
            f"[{ref}] Cancelled: {subject}",
            greeting
            + f"Request {ref} has been cancelled. Reason: {f.get('reason')}. "
            f"{f.get('cancelled_summary', '')}".strip()
            + SIGNATURE,
        )
    if comm_type == CommType.DUPLICATE_NOTICE:
        return (
            f"[{ref}] Already being handled under {f.get('master_ref')}",
            greeting + f"Thanks for reporting this. The same issue is already being handled "
            f"under {f.get('master_ref')}; we have linked your report to it and will keep you "
            f"updated there." + SIGNATURE,
        )
    if comm_type == CommType.CLOSURE:
        return (
            f"[{ref}] Resolved: {subject}",
            greeting + f"Request {ref} ({what}) has been resolved and closed. Action taken: "
            f"{f.get('recommendation') or 'see case notes'}." + SIGNATURE,
        )
    risk = f.get("risk_level")
    return (
        f"[{ref}] Update: {subject}",
        greeting
        + f"We are working on your request{f' ({what})' if what else ''}. "
        + (f"Current assessment: {risk} risk. " if risk else "")
        + (f"Shortfall: {f['shortfall']} units. " if f.get("shortfall") else "")
        + (
            f"Proposed next step (pending internal review): {f['recommendation']}. "
            if f.get("recommendation")
            else ""
        )
        + "We will keep you posted."
        + SIGNATURE,
    )


def _llm_facts(facts: dict[str, Any]) -> dict[str, Any]:
    """Facts for the LLM: no verbatim parts, times already written out in IST."""
    return {
        k: ist_label(v) if k in _TIME_KEYS else v
        for k, v in facts.items()
        if k not in _VERBATIM_KEYS and k != "routing_note" and v not in (None, "", [])
    }


def _ask_llm(
    comm_type: CommType, facts: dict[str, Any], llm: LLMClient, audience: str
) -> tuple[tuple[str, str] | None, Any]:
    """LLM draft, or None when it failed or cites numbers that are not in the facts."""
    source = json.dumps(_llm_facts(facts), default=str)
    result = llm.call_json(
        prompt_name="comms",
        system=prompts.COMMS.format(
            comm_type=str(comm_type).replace("_", " "),
            audience=AUDIENCE.get(comm_type, audience),
        ),
        user="FACTS:\n" + source,
        schema=DraftOut,
        temperature=0.3,
    )
    if result.data is None:
        return None, result
    subject, body = result.data.subject, _PLACEHOLDER.sub("", result.data.body).strip()
    if unsupported_numbers(source, f"{subject}\n{body}"):
        return None, result  # grounding check failed: use the template
    return (subject, body), result


def draft(
    comm_type: CommType,
    facts: dict[str, Any],
    to: list[str],
    llm: LLMClient | None = None,
    audience: str = "the requester",
) -> tuple[dict[str, Any], Any]:
    """Return (draft dict, LLMResult | None)."""
    written, result = (None, None)
    if llm is not None and comm_type in LLM_TYPES:
        written, result = _ask_llm(comm_type, facts, llm, audience)
    if written is not None:
        (subject, body), model = written, result.model
    else:
        (subject, body), model = _template(comm_type, facts), "template"
    if comm_type == CommType.APPROVAL_REQUEST:  # human and untrusted text stay verbatim
        body = body.removesuffix(SIGNATURE) + _note_block(facts) + _original_block(facts)
        body += SIGNATURE if model == "template" else ""
    return {
        "type": str(comm_type),
        "to": to,
        "subject": subject[:300],
        "body": body,
        "model": model,
        "created_by": "agent",
    }, result


def comm_facts(state: CaseState, **extra: Any) -> dict[str, Any]:
    facts = state.get("facts", {})
    top = next(iter(state.get("recommendations") or []), None)
    return {
        "ref": state.get("ref"),
        "subject": state.get("subject"),
        "recipient_name": state.get("sender_name"),
        "item": facts.get("item"),
        "quantity_required": facts.get("quantity_required"),
        "location": facts.get("city"),
        "shortfall": facts.get("shortfall"),
        "risk_level": (state.get("risk", {}).get("reconciled") or {}).get("risk_level"),
        "recommendation": top["title"] if top else None,
        **extra,
    }


def communication_node(state: CaseState, config: RunnableConfig) -> dict[str, Any]:
    timer = Timer()
    to = [state["sender_email"]] if state.get("sender_email") else []
    outcome = state.get("outcome")
    if outcome == "needs_info":
        missing = [
            i["field"]
            for i in state.get("issues", [])
            if i["type"] == "missing_info" and i["field"]
        ]
        subs = [s["title"] for s in state.get("sub_requests") or []]
        comm_type = CommType.CLARIFICATION
        facts = comm_facts(
            state,
            missing=missing,
            sub_issues=subs,
            questions=clarify_questions(state.get("issues", [])),
        )
    elif outcome == "duplicate":
        master = state["duplicates"][0]["ref"]
        comm_type, facts = CommType.DUPLICATE_NOTICE, comm_facts(state, master_ref=master)
    else:
        comm_type, facts = CommType.STAKEHOLDER_UPDATE, comm_facts(state)
    llm = ctx(config).llm if comm_type in LLM_TYPES else None
    d, result = draft(comm_type, facts, to, llm)
    return {
        "drafts": [d],
        **agent_output(
            AGENT,
            timer,
            action="communication.drafted",
            after={"type": d["type"], "to": to, "subject": d["subject"]},
            result=result,
        ),
    }
