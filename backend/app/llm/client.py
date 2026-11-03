"""LLMClient — the ONLY place that talks to an LLM provider (DEVELOPMENT_RULES §4, §9).

call_json() = timeout + retries with exponential backoff + JSON mode + Pydantic validation +
one repair retry. It never raises: callers get an LLMResult and use the fallback engine when
`result.data is None`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

import openai
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.llm.prompts import prompt_hash

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

# ok = validated LLM output; mock = LLM intentionally not used (LLM_MODE=mock / no key);
# unavailable = provider down/timeouts; invalid = bad output after repair; budget = cap hit.
CallStatus = Literal["ok", "mock", "unavailable", "invalid", "budget"]
FALLBACK_MODEL = "fallback"
OUTAGE_FLAG_ERROR = "LLM flagged down"  # simulated outage (Scenario Lab), not a provider error


@dataclass
class LLMResult(Generic[T]):
    data: T | None
    status: CallStatus
    model: str
    prompt_hash: str
    latency_ms: int = 0
    tokens: int | None = None
    error: str | None = None

    @property
    def failed(self) -> bool:
        """True when the LLM should have answered but couldn't (marks the case degraded)."""
        return self.status in {"unavailable", "invalid"}


class LLMClient:
    """One instance per case analysis: carries the call budget and the prompt cache."""

    def __init__(self, settings: Settings, *, llm_down: bool = False) -> None:
        self._settings = settings
        self._llm_down = llm_down
        self._calls = 0
        self._circuit_open = False  # set after a provider outage: skip further calls this run
        self._lock = threading.Lock()
        self._cache: dict[str, LLMResult[BaseModel]] = {}
        self._client: openai.OpenAI | None = None
        if settings.llm_configured:
            self._client = openai.OpenAI(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
                timeout=settings.llm_timeout_seconds,
                max_retries=0,
            )

    @property
    def model(self) -> str:
        return self._settings.llm_model

    def call_json(
        self,
        *,
        prompt_name: str,
        system: str,
        user: str,
        schema: type[T],
        temperature: float = 0.0,
    ) -> LLMResult[T]:
        p_hash = prompt_hash(prompt_name)
        if self._llm_down:  # checked first so the outage drill also works in mock mode
            return LLMResult(None, "unavailable", FALLBACK_MODEL, p_hash, error=OUTAGE_FLAG_ERROR)
        if self._client is None:
            return LLMResult(None, "mock", FALLBACK_MODEL, p_hash)

        cache_key = hashlib.sha256(f"{schema.__name__}|{system}|{user}".encode()).hexdigest()
        with self._lock:
            if cache_key in self._cache:
                return self._cache[cache_key]  # type: ignore[return-value]
            if self._circuit_open:
                return LLMResult(
                    None,
                    "unavailable",
                    FALLBACK_MODEL,
                    p_hash,
                    error="circuit open after provider failure",
                )
            if self._calls >= self._settings.llm_max_calls_per_run:
                return LLMResult(None, "budget", FALLBACK_MODEL, p_hash, error="call budget hit")
            self._calls += 1

        result = self._call(p_hash, system, user, schema, temperature)
        with self._lock:
            if result.status == "ok":
                self._cache[cache_key] = result  # type: ignore[assignment]
            elif result.status == "unavailable":
                self._circuit_open = True
        return result

    def _call(
        self, p_hash: str, system: str, user: str, schema: type[T], temperature: float
    ) -> LLMResult[T]:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        started = time.perf_counter()
        tokens = 0
        for attempt in range(2):  # first answer + one repair retry
            response = self._complete_with_retries(messages, temperature)
            if response is None:
                return self._result(None, "unavailable", p_hash, started, tokens, "provider error")
            content, used = response
            tokens += used
            try:
                data = schema.model_validate(json.loads(_strip_fences(content)))
                return self._result(data, "ok", p_hash, started, tokens)
            except (json.JSONDecodeError, ValidationError) as exc:
                log.warning(
                    "llm.invalid_output", extra={"attempt": attempt, "error": str(exc)[:300]}
                )
                messages += [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": f"Invalid: {str(exc)[:500]}. "
                        "Return valid JSON only, matching the schema.",
                    },
                ]
        return self._result(None, "invalid", p_hash, started, tokens, "schema validation failed")

    def _extra_params(self) -> dict[str, str]:
        effort = self._settings.llm_reasoning_effort
        return {"reasoning_effort": effort} if effort else {}

    def _complete_with_retries(
        self, messages: list[dict[str, str]], temperature: float
    ) -> tuple[str, int] | None:
        assert self._client is not None
        for attempt in range(self._settings.llm_max_retries + 1):
            try:
                completion = self._client.chat.completions.create(
                    model=self._settings.llm_model,
                    messages=messages,  # type: ignore[arg-type]
                    temperature=temperature,
                    response_format={"type": "json_object"},
                    **self._extra_params(),
                )
                usage = completion.usage.total_tokens if completion.usage else 0
                return completion.choices[0].message.content or "", usage
            except (
                openai.APIConnectionError,
                openai.APITimeoutError,
                openai.RateLimitError,
                openai.InternalServerError,
            ) as exc:
                log.warning("llm.retry", extra={"attempt": attempt, "error": type(exc).__name__})
                if attempt < self._settings.llm_max_retries:
                    time.sleep(2**attempt)
            except openai.APIError as exc:
                log.error("llm.error", extra={"error": type(exc).__name__})
                return None
        return None

    def _result(
        self,
        data: T | None,
        status: CallStatus,
        p_hash: str,
        started: float,
        tokens: int,
        error: str | None = None,
    ) -> LLMResult[T]:
        model = self._settings.llm_model if status == "ok" else FALLBACK_MODEL
        return LLMResult(
            data=data,
            status=status,
            model=model,
            prompt_hash=p_hash,
            latency_ms=int((time.perf_counter() - started) * 1000),
            tokens=tokens or None,
            error=error,
        )


def _strip_fences(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    return text
