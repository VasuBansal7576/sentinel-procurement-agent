from sentinel_api.config import Settings


def test_settings_default_to_credential_free_providers() -> None:
    settings = Settings(_env_file=None)

    assert settings.model_provider == "fake"
    assert settings.email_provider == "fake"
    assert settings.controlled_recipient is None
