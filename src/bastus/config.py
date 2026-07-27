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

    # Target selection: "openai" (OpenAI-compatible endpoint) or "smartai" (Smart AI api-test)
    target_kind: str = "openai"

    # Target model+harness under test (openai kind)
    target_endpoint: str | None = None
    target_api_key: str | None = None
    target_model: str | None = None

    # Smart AI api-test target (smartai kind)
    smartai_base: str | None = None            # e.g. https://nmblr.xyz/base-smart/api-test
    smartai_login_url: str | None = None       # e.g. https://nmblr.xyz/login/login.php
    smartai_web_user: str | None = None
    smartai_web_pass: str | None = None
    smartai_msisdn: str | None = None
    smartai_otp: str = "123456"

    # Attacker model (abliterated, OpenAI-compatible)
    attacker_endpoint: str | None = None
    attacker_api_key: str = "EMPTY"
    attacker_model: str | None = None
    attacker_force_temperature: float | None = None

    # Judge model
    judge_endpoint: str | None = None
    judge_api_key: str | None = None
    judge_model: str | None = None
    # Some endpoints pin temperature (e.g. Kimi Code k3 requires 1).
    judge_force_temperature: float | None = None

    # Target overrides
    target_force_temperature: float | None = None

    # Infrastructure
    runpod_api_key: str | None = None
    hf_token: str | None = Field(default=None, alias="HF_TOKEN")


def load_settings() -> Settings:
    return Settings()
