"""``app/tools/jira_check.py``: the standalone health check AC16's documented
command runs against the owner's real Jira. No test here reaches the network --
every stub goes through the same injectable transport
``app/integrations/jira.py`` offers, the pattern ``test_jira_client.py`` and
``test_jira_sync.py`` already use.

The redaction tests below are the point of this file: a report or a printed
line that ever carried the configured API token would defeat the one property
AC16 asks of the documented command (report what came back, never the token).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from app.config import Settings, get_settings
from app.integrations.jira import JiraConfigurationError, JiraError
from app.tools import jira_check

SECRET_TOKEN = "super-secret-jira-token-8f2c91"
OWNER_ACCOUNT_ID = "5b10a2844c20165700ede21g"


def _configured_settings(**overrides: Any) -> Settings:
    values = {
        "jira_site_url": "https://example.atlassian.net",
        "jira_account_email": "owner@example.com",
        "jira_api_token": SECRET_TOKEN,
    }
    values.update(overrides)
    return Settings(**values)


def _transport(issues: list[dict[str, Any]], project_issues: list[dict[str, Any]] | None = None):
    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        assert method == "GET"
        if url.endswith("/myself"):
            return {"accountId": OWNER_ACCOUNT_ID, "displayName": "Owner Example"}
        query = parse_qs(urlparse(url).query)
        jql = query.get("jql", [""])[0]
        if project_issues is not None and jql.startswith("project ="):
            return {"issues": project_issues}
        return {"issues": issues}

    return transport


ISSUE = {"id": "10001", "key": "OPS-1", "fields": {"summary": "Fix the thing", "updated": "2026-09-18T08:30:00.000+0000"}}


def test_run_check_reports_the_owner_identity_and_participation_count() -> None:
    settings = _configured_settings()

    report = jira_check.run_check(settings, transport=_transport([ISSUE, ISSUE]))

    assert report["site"] == "https://example.atlassian.net"
    assert report["account_id"] == OWNER_ACCOUNT_ID
    assert report["display_name"] == "Owner Example"
    assert report["participation_issue_count"] == 2
    assert "management_project_key" not in report


def test_run_check_reports_the_management_project_count_when_configured() -> None:
    settings = _configured_settings(jira_management_project_key="OPS")

    report = jira_check.run_check(settings, transport=_transport([ISSUE], project_issues=[ISSUE, ISSUE, ISSUE]))

    assert report["management_project_key"] == "OPS"
    assert report["management_project_issue_count"] == 3


def test_run_check_omits_the_management_project_fields_when_unset() -> None:
    settings = _configured_settings()

    report = jira_check.run_check(settings, transport=_transport([]))

    assert "management_project_key" not in report
    assert "management_project_issue_count" not in report


def test_run_check_raises_the_configuration_error_when_jira_is_not_set_up() -> None:
    settings = Settings()

    with pytest.raises(JiraConfigurationError):
        jira_check.run_check(settings, transport=_transport([]))


def test_run_check_report_never_carries_the_configured_token() -> None:
    settings = _configured_settings(jira_management_project_key="OPS")

    report = jira_check.run_check(settings, transport=_transport([ISSUE], project_issues=[ISSUE]))

    assert SECRET_TOKEN not in repr(report)


def test_run_check_lets_a_jira_error_propagate() -> None:
    settings = _configured_settings()

    def failing_transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        raise JiraError("Jira request failed with status 500")

    with pytest.raises(JiraError):
        jira_check.run_check(settings, transport=failing_transport)


# --- main(): exit codes, remedy messages, and never printing the token ------


def test_main_prints_a_healthy_report_and_exits_zero(monkeypatch, capsys) -> None:
    monkeypatch.setenv("JIRA_SITE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_ACCOUNT_EMAIL", "owner@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", SECRET_TOKEN)
    get_settings.cache_clear()
    monkeypatch.setattr(jira_check, "default_transport", _transport([ISSUE]))

    exit_code = jira_check.main()

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Owner Example" in out
    assert "1 issue(s)" in out


def test_main_names_the_missing_settings_and_exits_nonzero_when_unconfigured(monkeypatch, capsys) -> None:
    for name in ("JIRA_SITE_URL", "JIRA_ACCOUNT_EMAIL", "JIRA_API_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()

    exit_code = jira_check.main()

    err = capsys.readouterr().err
    assert exit_code == 1
    assert "JIRA_SITE_URL" in err


def test_main_never_prints_the_configured_token_on_success(monkeypatch, capsys) -> None:
    monkeypatch.setenv("JIRA_SITE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_ACCOUNT_EMAIL", "owner@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", SECRET_TOKEN)
    monkeypatch.setenv("JIRA_MANAGEMENT_PROJECT_KEY", "OPS")
    get_settings.cache_clear()
    monkeypatch.setattr(jira_check, "default_transport", _transport([ISSUE], project_issues=[ISSUE]))

    jira_check.main()

    captured = capsys.readouterr()
    assert SECRET_TOKEN not in captured.out
    assert SECRET_TOKEN not in captured.err


def test_main_never_prints_the_configured_token_on_a_jira_error(monkeypatch, capsys) -> None:
    """A failing request (bad credentials, a 500, ...) is exactly when an
    over-eager error handler is tempted to name what it sent -- the transport's
    own errors never carry the token (``app/integrations/jira.py``), so this
    pins that ``main`` does not add it back in while reporting the failure."""
    monkeypatch.setenv("JIRA_SITE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_ACCOUNT_EMAIL", "owner@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", SECRET_TOKEN)
    get_settings.cache_clear()

    def failing_transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        raise JiraError("Jira request failed with status 401")

    monkeypatch.setattr(jira_check, "default_transport", failing_transport)

    exit_code = jira_check.main()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert SECRET_TOKEN not in captured.out
    assert SECRET_TOKEN not in captured.err
