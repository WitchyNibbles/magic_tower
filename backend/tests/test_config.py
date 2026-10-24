"""``Settings`` against the shape the owner's real root ``.env`` actually takes.

The owner's ``.env`` documents every Microsoft Graph key with an empty value
(``MICROSOFT_TENANT_ID=``) rather than omitting the line, so a developer who has
not connected Graph yet can see which variables exist without leaking one. Pydantic
reads an empty ``.env`` value as the literal string ``""``, not as an absent
variable, which used to trip ``graph_identifiers_are_not_urls`` and abort
``Settings()`` construction with a ``ValidationError`` -- the api container's exact
startup failure. An empty string has to mean "unset" for every optional setting,
while a present, malformed value still has to fail loudly.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings

# Every optional setting that can arrive as an empty string from a documented,
# gitignored ``.env`` -- not just the three the failing container happened to hit.
OPTIONAL_SETTINGS = (
    "microsoft_tenant_id",
    "microsoft_client_id",
    "microsoft_client_secret",
    "microsoft_target_user_id",
    "app_encryption_key",
    "local_api_token",
    "jira_site_url",
    "jira_account_email",
    "jira_api_token",
    "jira_management_project_key",
)


@pytest.mark.parametrize("field_name", OPTIONAL_SETTINGS)
@pytest.mark.parametrize("blank_value", ["", "   "])
def test_blank_optional_setting_is_treated_as_absent(field_name: str, blank_value: str) -> None:
    settings = Settings(**{field_name: blank_value})

    value = getattr(settings, field_name)
    assert value is None, f"{field_name}={blank_value!r} should read back as None, got {value!r}"


def test_all_optional_settings_blank_together_still_validates() -> None:
    """The owner's actual root ``.env`` blanks every Graph and secret field at once."""
    settings = Settings(**{name: "" for name in OPTIONAL_SETTINGS})

    for field_name in OPTIONAL_SETTINGS:
        assert getattr(settings, field_name) is None


def test_present_malformed_graph_identifier_still_rejected() -> None:
    """A non-empty, non-blank identifier containing URL punctuation is still a bug,
    not an absent setting, so the validator must keep rejecting it."""
    with pytest.raises(ValidationError):
        Settings(microsoft_tenant_id="tenant/with-a-slash")


def test_blank_graph_settings_are_reported_as_missing() -> None:
    """The fail-closed 503 path depends on blank settings counting as missing,
    exactly like an unset variable -- not as a value that happens to validate."""
    settings = Settings(
        microsoft_tenant_id="",
        microsoft_client_id="",
        microsoft_client_secret="",
        microsoft_target_user_id="",
        app_encryption_key="",
    )

    errors = settings.graph_configuration_errors()
    assert set(errors) == {
        "MICROSOFT_TENANT_ID",
        "MICROSOFT_CLIENT_ID",
        "MICROSOFT_CLIENT_SECRET",
        "MICROSOFT_TARGET_USER_ID",
        "APP_ENCRYPTION_KEY",
    }


def test_jira_sync_lookback_defaults_to_two_weeks() -> None:
    assert Settings().jira_sync_lookback_days == 14


def test_jira_sync_lookback_is_read_from_its_environment_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_SYNC_LOOKBACK_DAYS", "30")

    assert Settings().jira_sync_lookback_days == 30


@pytest.mark.parametrize("bad_value", [0, -3])
def test_jira_sync_lookback_below_one_day_is_refused(bad_value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(jira_sync_lookback_days=bad_value)


def test_sync_interval_defaults_to_ten_minutes(monkeypatch: pytest.MonkeyPatch) -> None:
    # The suite pins SYNC_INTERVAL_MINUTES=0 (tests/conftest.py); the default is what a deployment gets.
    monkeypatch.delenv("SYNC_INTERVAL_MINUTES")

    assert Settings().sync_interval_minutes == 10


def test_sync_interval_is_read_from_its_environment_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYNC_INTERVAL_MINUTES", "30")

    assert Settings().sync_interval_minutes == 30


def test_sync_interval_zero_turns_the_scheduler_off() -> None:
    assert Settings(sync_interval_minutes=0).sync_interval_minutes == 0


def test_sync_interval_below_zero_is_refused() -> None:
    with pytest.raises(ValidationError):
        Settings(sync_interval_minutes=-1)
