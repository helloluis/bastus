"""Runtime configuration, loaded from environment / .env.local.

None of these are required for Phase 1 offline (mock) runs; they configure the
real attacker / target / judge endpoints and infrastructure for live runs.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Target model+harness under test
    target_endpoint: str | None = None
    target_api_key: str | None = None
    target_model: str | None = None

    # Attacker model (abliterated, OpenAI-compatible)
    attacker_endpoint: str | None = None
    attacker_api_key: str = "EMPTY"
    attacker_model: str | None = None

    # Judge model
    judge_endpoint: str | None = None
    judge_api_key: str | None = None
    judge_model: str | None = None

    # Infrastructure
    runpod_api_key: str | None = None
    hf_token: str | None = Field(default=None, alias="HF_TOKEN")


def load_settings() -> Settings:
    return Settings()
