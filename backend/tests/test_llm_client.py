"""LLMClient (§7.5): schema validation, one repair retry, timeouts → unavailable, budget, cache."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import openai
from pydantic import BaseModel

from app.config import Settings
from app.llm.client import LLMClient


class Answer(BaseModel):
    value: int


class FakeCompletions:
    def __init__(self, replies: list[Any]) -> None:
        self.replies = replies
        self.calls = 0

    def create(self, **_: Any) -> Any:
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        if isinstance(reply, Exception):
            raise reply
        message = SimpleNamespace(content=reply)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)], usage=SimpleNamespace(total_tokens=10)
        )


def _client(replies: list[Any], **settings: Any) -> tuple[LLMClient, FakeCompletions]:
    client = LLMClient(Settings(llm_mode="live", llm_api_key="test", llm_max_retries=1, **settings))
    fake = FakeCompletions(replies)
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=fake))  # type: ignore[assignment]
    return client, fake


def _call(client: LLMClient, user: str = "q") -> Any:
    return client.call_json(prompt_name="extraction", system="s", user=user, schema=Answer)


def test_valid_json_ok() -> None:
    client, _ = _client(['{"value": 3}'])
    result = _call(client)
    assert result.status == "ok" and result.data.value == 3 and result.tokens == 10


def test_invalid_json_repaired_once() -> None:
    client, fake = _client(["not json", '```json\n{"value": 4}\n```'])
    result = _call(client)
    assert result.status == "ok" and result.data.value == 4 and fake.calls == 2


def test_invalid_twice_falls_back() -> None:
    client, fake = _client(['{"value": "x"}'])
    result = _call(client)
    assert result.data is None and result.status == "invalid" and result.failed
    assert fake.calls == 2


def test_timeouts_mark_unavailable(monkeypatch: Any) -> None:
    monkeypatch.setattr("app.llm.client.time.sleep", lambda _: None)
    timeout = openai.APITimeoutError(request=SimpleNamespace())  # type: ignore[arg-type]
    client, fake = _client([timeout])
    result = _call(client)
    assert result.status == "unavailable" and result.failed and fake.calls == 2


def test_circuit_opens_after_outage(monkeypatch: Any) -> None:
    monkeypatch.setattr("app.llm.client.time.sleep", lambda _: None)
    client, fake = _client([openai.APITimeoutError(request=SimpleNamespace())])  # type: ignore[arg-type]
    assert _call(client, "a").status == "unavailable"
    calls = fake.calls
    second = _call(client, "b")
    assert second.status == "unavailable" and fake.calls == calls  # no further provider calls


def test_budget_and_cache() -> None:
    client, fake = _client(['{"value": 1}'], llm_max_calls_per_run=2)
    assert _call(client, "a").status == "ok"
    assert _call(client, "a").status == "ok" and fake.calls == 1  # cached
    assert _call(client, "b").status == "ok"
    assert _call(client, "c").status == "budget"


def test_mock_mode_and_outage_flag() -> None:
    assert _call(LLMClient(Settings(llm_mode="mock"))).status == "mock"
    down = LLMClient(Settings(llm_mode="mock"), llm_down=True)
    assert _call(down).status == "unavailable"
