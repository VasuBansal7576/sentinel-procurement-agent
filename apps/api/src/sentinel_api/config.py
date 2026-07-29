"""Typed application configuration."""

from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment contract shared by local, CI, and production deployments."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SENTINEL_",
        env_ignore_empty=True,
        extra="ignore",
        case_sensitive=False,
    )

    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8000, ge=1, le=65535)
    web_origin: AnyHttpUrl = AnyHttpUrl("http://localhost:5173")
    persistence_mode: Literal["memory", "postgres"] = "memory"
    auto_migrate: bool = False
    database_url: str = "postgresql+psycopg://sentinel:sentinel@localhost:5432/sentinel"
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    object_store_endpoint: AnyHttpUrl = AnyHttpUrl("http://localhost:9000")
    object_store_bucket: str = "sentinel"
    object_store_access_key: str = "sentinel"
    object_store_secret_key: str = "sentinel-local-only"
    model_provider: Literal["fake", "openai"] = "fake"
    email_provider: Literal["fake", "resend", "gmail"] = "fake"
    controlled_recipient: str | None = None
    credential_gate: Literal["fake-only", "live-approved"] = "fake-only"
    demo_mode: bool = False
    demo_step_delay_ms: int = Field(default=0, ge=0, le=5_000)
    demo_failure_step: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9][a-z0-9_.-]{1,119}$",
    )

    @model_validator(mode="after")
    def enforce_release_gates(self) -> "Settings":
        """Fail closed around demo controls and credentialed providers."""

        demo_controls_requested = self.demo_step_delay_ms > 0 or self.demo_failure_step is not None
        if demo_controls_requested and not self.demo_mode:
            raise ValueError("demo pacing/failure controls require SENTINEL_DEMO_MODE=true")
        if self.environment == "production" and self.demo_mode:
            raise ValueError("demo mode is forbidden in production")

        live_provider_requested = self.model_provider != "fake" or self.email_provider != "fake"
        if live_provider_requested and self.credential_gate != "live-approved":
            raise ValueError("live providers require the explicit post-acceptance credential gate")
        if self.email_provider != "fake" and not self.controlled_recipient:
            raise ValueError("live email requires one controlled recipient")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
