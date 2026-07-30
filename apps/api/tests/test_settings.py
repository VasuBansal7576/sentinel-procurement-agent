import pytest
from pydantic import ValidationError

from sentinel_api.config import Settings
from sentinel_api.integration.demo import DemoProfile


def test_settings_default_to_credential_free_providers() -> None:
    settings = Settings(_env_file=None)

    assert settings.model_provider == "fake"
    assert settings.email_provider == "fake"
    assert settings.controlled_recipient is None
    assert settings.credential_gate == "fake-only"
    assert DemoProfile.from_settings(settings).enabled is False


def test_blank_optional_environment_value_uses_fail_closed_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SENTINEL_DEMO_FAILURE_STEP", "")

    assert Settings(_env_file=None).demo_failure_step is None


def test_demo_controls_are_explicit_and_impossible_in_production() -> None:
    with pytest.raises(ValidationError, match="require SENTINEL_DEMO_MODE"):
        Settings(_env_file=None, demo_step_delay_ms=250)
    with pytest.raises(ValidationError, match="forbidden in production"):
        Settings(_env_file=None, environment="production", demo_mode=True)

    settings = Settings(
        _env_file=None,
        demo_mode=True,
        demo_step_delay_ms=250,
        demo_failure_step="candidate.2.snapshot",
    )
    profile = DemoProfile.from_settings(settings)
    assert profile.step_delay_seconds == 0.25
    assert profile.failure_step == "candidate.2.snapshot"
    assert profile.disclosure.startswith("DEMO MODE:")


def test_live_providers_fail_closed_before_the_final_credential_gate() -> None:
    with pytest.raises(ValidationError, match="post-acceptance credential gate"):
        Settings(_env_file=None, email_provider="resend")
    with pytest.raises(ValidationError, match="controlled recipient"):
        Settings(
            _env_file=None,
            email_provider="resend",
            credential_gate="live-approved",
        )

    with pytest.raises(ValidationError, match="RESEND_API_KEY"):
        Settings(
            _env_file=None,
            email_provider="resend",
            credential_gate="live-approved",
            controlled_recipient="owner@example.test",
        )

    settings = Settings(
        _env_file=None,
        email_provider="resend",
        credential_gate="live-approved",
        controlled_recipient="owner@example.test",
        resend_api_key="re_test_key",
    )
    assert settings.email_provider == "resend"
    assert settings.resend_api_key == "re_test_key"
