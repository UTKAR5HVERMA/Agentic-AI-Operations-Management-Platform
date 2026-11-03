"""Application settings. The ONLY place environment variables are read."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./opspilot.db"
    jwt_secret: str = "change-me"
    jwt_expire_minutes: int = 720

    llm_mode: Literal["live", "mock"] = "live"
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    llm_api_key: str = ""
    llm_model: str = "gemini-3.5-flash"
    llm_timeout_seconds: float = 20
    llm_max_retries: int = 2
    # For reasoning models (e.g. gpt-oss on Groq): low/medium/high. Empty = provider default.
    llm_reasoning_effort: str = ""
    llm_max_calls_per_run: int = 8

    confidence_auto_threshold: float = 0.80
    confidence_block_threshold: float = 0.50
    approval_default_timeout_minutes: int = 60
    scheduler_interval_seconds: int = 30
    scheduler_enabled: bool = True
    seed_on_startup: bool = True

    cors_origins: str = "http://localhost:5173"
    webhook_secret: str = "change-me-webhook-secret"
    log_level: str = "INFO"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def llm_configured(self) -> bool:
        """True when live LLM calls are possible (live mode and a key is present)."""
        return self.llm_mode == "live" and bool(self.llm_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
