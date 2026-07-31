"""Credential-free defaults for the API suite.

Pins fail-closed providers so a developer machine `.env` cannot leak into tests.
"""

from __future__ import annotations

import pytest

from sentinel_api.config import get_settings


@pytest.fixture(autouse=True)
def credential_free_test_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENTINEL_PERSISTENCE_MODE", "memory")
    monkeypatch.setenv("SENTINEL_MODEL_PROVIDER", "fake")
    monkeypatch.setenv("SENTINEL_RESEARCH_PROVIDER", "fake")
    monkeypatch.setenv("SENTINEL_EMAIL_PROVIDER", "fake")
    monkeypatch.setenv("SENTINEL_EMAIL_SENDER", "onboarding@resend.dev")
    monkeypatch.setenv(
        "SENTINEL_CONTROLLED_RECIPIENT",
        "procurement-demo@example.test",
    )
    monkeypatch.setenv("SENTINEL_CREDENTIAL_GATE", "fake-only")
    monkeypatch.setenv("SENTINEL_DEMO_MODE", "false")
    monkeypatch.setenv("SENTINEL_DEMO_STEP_DELAY_MS", "0")
    monkeypatch.delenv("SENTINEL_DEMO_FAILURE_STEP", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("SENTINEL_RESEND_API_KEY", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
