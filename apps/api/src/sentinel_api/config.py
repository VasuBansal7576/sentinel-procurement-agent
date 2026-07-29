"""Typed application configuration."""

from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment contract shared by local, CI, and production deployments."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SENTINEL_",
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
