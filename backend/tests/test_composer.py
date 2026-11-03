"""AI email composer: draft-only, and output that invents facts is rejected."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.agents import composer
from app.config import Settings
from app.llm.client import LLMClient
from tests.conftest import REQUESTER, Api, audit_actions

NOTES = "500 display units for pune launch late by 10 days, only 120 in stock, need by 4 PM"


def _llm_returning(content: str) -> LLMClient:
    client = LLMClient(Settings(llm_mode="live", llm_api_key="test"))
    reply = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))], usage=None
    )
    fake = SimpleNamespace(create=lambda **_: reply)
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=fake))  # type: ignore[assignment]
    return client


def test_compose_endpoint_returns_subject_and_body(api: Api) -> None:
    before = len(audit_actions())
    res = api.post(
        "/requests/compose",
        {"text": NOTES, "sender_name": "Regional Operations Manager"},
        as_=REQUESTER,
    )
    assert res.status_code == 200, res.text
    body: dict[str, Any] = res.json()
    assert body["subject"] and NOTES in body["body"]  # mock mode: template keeps the text
    assert body["body"].startswith("Hi Operations Team") and body["body"].endswith(
        "Regional Operations Manager"
    )
    assert len(audit_actions()) == before  # draft only: nothing saved


def test_compose_requires_login(api: Api) -> None:
    assert api.client.post("/api/requests/compose", json={"text": NOTES}).status_code == 401


def test_llm_rewrite_is_used_when_facts_are_kept() -> None:
    llm = _llm_returning(
        '{"subject": "Pune launch: 500 display units delayed 10 days", '
        '"body": "Hi team, 500 display units are 10 days late; 120 in stock. Need a decision by '
        '4:00 PM. Regards, Riya"}'
    )
    out = composer.compose(None, NOTES, "Riya", llm)
    assert out.model != "template" and out.note is None
    assert out.subject.startswith("Pune launch")


def test_llm_output_with_invented_numbers_falls_back() -> None:
    llm = _llm_returning('{"subject": "Delay", "body": "We need 750 units at a cost of 90,000."}')
    out = composer.compose(None, NOTES, "Riya", llm)
    assert out.model == "template" and out.note and "not in your text" in out.note
    assert composer.introduces_new_numbers(NOTES, "need 750 units")
    assert not composer.introduces_new_numbers(NOTES, "500 units by 4:00 PM")


def test_verifiable_calculations_are_allowed() -> None:
    notes = "need 500, have 120 in warehouse"
    assert not composer.introduces_new_numbers(notes, "a shortfall of 380 units")  # 500 - 120
    assert composer.introduces_new_numbers(notes, "a shortfall of 400 units")
