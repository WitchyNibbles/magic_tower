"""``Settings`` fails closed on missing or blank Jira configuration.

Mirrors ``test_config.py``'s Graph coverage: a documented, gitignored ``.env`` may
list a Jira key with an empty value (``JIRA_API_TOKEN=``) to show the setting
exists without committing a secret. Pydantic reads that as the literal string
``""``, not as an absent variable, so every Jira optional field has to be
normalized to ``None`` before anything downstream treats it as configured.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from app.config import Settings

# Every Jira optional setting that can arrive as an empty string from a
# documented, gitignored ``.env``.
JIRA_OPTIONAL_SETTINGS = (
    "jira_site_url",
    "jira_account_email",
    "jira_api_token",
    "jira_management_project_key",
)


@pytest.mark.parametrize("field_name", JIRA_OPTIONAL_SETTINGS)
@pytest.mark.parametrize("blank_value", ["", "   "])
def test_jira_configuration_blank_optional_setting_is_treated_as_absent(field_name: str, blank_value: str) -> None:
    settings = Settings(**{field_name: blank_value})

    value = getattr(settings, field_name)
    assert value is None, f"{field_name}={blank_value!r} should read back as None, got {value!r}"


def test_jira_configuration_all_optional_settings_blank_together_still_validates() -> None:
    settings = Settings(**{name: "" for name in JIRA_OPTIONAL_SETTINGS})

    for field_name in JIRA_OPTIONAL_SETTINGS:
        assert getattr(settings, field_name) is None


def test_jira_configuration_errors_reports_missing_by_name_when_all_unset() -> None:
    """The fail-closed path depends on unset Jira settings being reported by their
    env-var names, never a stack trace, exactly like the Graph errors list."""
    settings = Settings()

    errors = settings.jira_configuration_errors()
    assert set(errors) == {"JIRA_SITE_URL", "JIRA_ACCOUNT_EMAIL", "JIRA_API_TOKEN"}


def test_jira_configuration_errors_reports_blank_settings_as_missing() -> None:
    """A blank ``.env`` line must count as missing, exactly like an unset variable,
    not as a value that happens to validate."""
    settings = Settings(jira_site_url="", jira_account_email="", jira_api_token="")

    errors = settings.jira_configuration_errors()
    assert set(errors) == {"JIRA_SITE_URL", "JIRA_ACCOUNT_EMAIL", "JIRA_API_TOKEN"}


def test_jira_configuration_errors_empty_when_all_three_present() -> None:
    settings = Settings(
        jira_site_url="https://example.atlassian.net",
        jira_account_email="owner@example.com",
        jira_api_token="a-token",
    )

    assert settings.jira_configuration_errors() == []


def test_jira_configuration_api_token_is_a_secret() -> None:
    """The token must never render in plain text -- a stack trace or a stray
    ``repr()`` in a log must not leak it."""
    settings = Settings(jira_api_token="a-real-token")

    assert isinstance(settings.jira_api_token, SecretStr)
    assert "a-real-token" not in repr(settings.jira_api_token)
    assert settings.jira_api_token.get_secret_value() == "a-real-token"


def test_jira_configuration_management_project_key_is_optional_and_not_required() -> None:
    """The management-project key is a visibility setting (T09), not part of the
    core connection -- it must not appear in ``jira_configuration_errors()``."""
    settings = Settings(
        jira_site_url="https://example.atlassian.net",
        jira_account_email="owner@example.com",
        jira_api_token="a-token",
    )

    assert settings.jira_management_project_key is None
    assert settings.jira_configuration_errors() == []
