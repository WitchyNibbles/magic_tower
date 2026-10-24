"""``Settings`` fails closed on missing or blank Freshservice configuration.

Mirrors ``test_jira_configuration.py``: a documented, gitignored dotenv file may list
a Freshservice key with an empty value (``FRESHSERVICE_API_KEY=``) to show the
setting exists without committing a secret. Pydantic reads that as the literal
string ``""``, so every optional field has to be normalized to ``None`` before
anything downstream treats it as configured.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings

# Every Freshservice optional setting that can arrive as an empty string from a
# documented, gitignored dotenv file.
FRESHSERVICE_OPTIONAL_SETTINGS = (
    "freshservice_url",
    "freshservice_api_key",
    "freshservice_agent_email",
)


@pytest.mark.parametrize("field_name", FRESHSERVICE_OPTIONAL_SETTINGS)
@pytest.mark.parametrize("blank_value", ["", "   "])
def test_freshservice_configuration_blank_optional_setting_is_treated_as_absent(field_name: str, blank_value: str) -> None:
    settings = Settings(**{field_name: blank_value})

    value = getattr(settings, field_name)
    assert value is None, f"{field_name}={blank_value!r} should read back as None, got {value!r}"


def test_freshservice_configuration_errors_reports_missing_by_name_when_all_unset() -> None:
    errors = Settings().freshservice_configuration_errors()

    assert set(errors) == {"FRESHSERVICE_URL", "FRESHSERVICE_API_KEY"}


def test_freshservice_configuration_errors_reports_blank_settings_as_missing() -> None:
    """A blank line in the dotenv file must count as missing, exactly like an unset variable."""
    settings = Settings(freshservice_url="", freshservice_api_key="", freshservice_agent_email="")

    assert set(settings.freshservice_configuration_errors()) == {"FRESHSERVICE_URL", "FRESHSERVICE_API_KEY"}


def test_freshservice_configuration_errors_reports_a_whitespace_only_key_as_missing() -> None:
    settings = Settings(freshservice_url="https://example.freshservice.com", freshservice_api_key="   ")

    assert settings.freshservice_configuration_errors() == ["FRESHSERVICE_API_KEY"]


def test_freshservice_configuration_errors_empty_when_url_and_key_present() -> None:
    settings = Settings(freshservice_url="https://example.freshservice.com", freshservice_api_key="a-key")

    assert settings.freshservice_configuration_errors() == []


def test_freshservice_configuration_agent_email_is_optional_and_not_required() -> None:
    """Without it the owner is whoever the key belongs to (``/agents/me``), so it is
    not part of the core connection."""
    settings = Settings(freshservice_url="https://example.freshservice.com", freshservice_api_key="a-key")

    assert settings.freshservice_agent_email is None
    assert settings.freshservice_configuration_errors() == []


def test_freshservice_configuration_api_key_is_a_secret() -> None:
    """A stray ``repr()`` in a log must not leak the key."""
    settings = Settings(freshservice_api_key="a-real-key")

    assert isinstance(settings.freshservice_api_key, SecretStr)
    assert "a-real-key" not in repr(settings.freshservice_api_key)
    assert "a-real-key" not in repr(settings)
    assert settings.freshservice_api_key.get_secret_value() == "a-real-key"


def test_freshservice_configuration_lookback_defaults_to_fourteen_days() -> None:
    assert Settings().freshservice_sync_lookback_days == 14


@pytest.mark.parametrize("days", [0, -1])
def test_freshservice_configuration_lookback_below_one_day_is_rejected(days: int) -> None:
    with pytest.raises(ValidationError):
        Settings(freshservice_sync_lookback_days=days)
