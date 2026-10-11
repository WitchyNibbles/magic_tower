"""Standalone health check against the owner's real Jira (AC16).

Usage::

    cd backend
    uv run --env-file ../.env python -m app.tools.jira_check

``--env-file`` is load-bearing, not decoration: ``Settings`` resolves its
``env_file=".env"`` against the current working directory (``app/config.py``),
so the repository-root ``.env`` this project keeps its settings in is invisible
from ``backend/`` unless it is named. Without the flag this command reports
every required Jira setting as missing while correct ones sit on disk.

Reads ``JIRA_SITE_URL``, ``JIRA_ACCOUNT_EMAIL``, ``JIRA_API_TOKEN`` and,
optionally, ``JIRA_MANAGEMENT_PROJECT_KEY`` the same way the sync handler
does (``Settings.jira_configuration_errors()``, ``JiraClient.from_settings``
-- ``app/services/jira_sync.py``), and reports what Jira sent back for the
token owner: their identity, how many issues fall in the participation
window (``app/integrations/jira.py:JIRA_PARTICIPATION_JQL``), and, when
configured, how many issues the management project fetch found. See
``docs/jira-setup.md`` for how to obtain a token and what a healthy result
looks like.

This never writes to the database and never promotes anything -- it is a
read of the same two endpoints ``app/services/jira_sync.py`` calls
(``GET /rest/api/3/myself`` and ``GET /rest/api/3/search/jql``), through the
same injectable transport, so ``backend/tests/test_jira_check.py`` pins its
report against a stub with no network.

**The token never reaches this module.** ``JiraClient.from_settings`` is the
only place that reads ``Settings.jira_api_token``, to build the Basic auth
header; nothing here holds or forwards that value, so there is no line here
that could print it. What :func:`run_check` returns and :func:`main` prints
is built entirely from what Jira's *responses* contain (an ``accountId``, a
``displayName``, issue counts) -- never from the settings that authenticated
the request.
"""

from __future__ import annotations

import sys

from ..config import Settings, get_settings
from ..integrations.jira import JiraClient, JiraError, Transport, default_transport


def run_check(settings: Settings, transport: Transport = default_transport) -> dict[str, object]:
    """Everything :func:`main` prints, as data, so a test can assert on the
    report without capturing stdout. Raises ``JiraConfigurationError`` or
    ``JiraError`` rather than swallowing either -- :func:`main` is the one
    place that turns them into an exit code and a message, the same split
    ``app/tools/heuristic_export.py`` keeps around ``export_rows``.
    """
    client = JiraClient.from_settings(settings, transport=transport)
    me = client.myself()
    participation = client.search_participation_issues()
    report: dict[str, object] = {
        "site": client.base_url,
        "account_id": me.get("accountId"),
        "display_name": me.get("displayName"),
        "participation_issue_count": len(participation),
    }
    if settings.jira_management_project_key:
        project_issues = client.search_project_issues(settings.jira_management_project_key)
        report["management_project_key"] = settings.jira_management_project_key
        report["management_project_issue_count"] = len(project_issues)
    return report


def _print_report(report: dict[str, object]) -> None:
    print(f"connected to {report['site']} as {report['display_name']!r} (accountId {report['account_id']})")
    print(f"participation window: {report['participation_issue_count']} issue(s)")
    if "management_project_key" in report:
        print(f"management project {report['management_project_key']!r}: "
              f"{report['management_project_issue_count']} issue(s)")


def main() -> int:
    settings = get_settings()
    try:
        report = run_check(settings, transport=default_transport)
    except JiraError as error:
        # One branch, no prefix: every ``JiraError`` ``app/integrations/jira.py``
        # raises already names itself ("Jira is not configured: missing ...",
        # "Jira request failed with status 401", "Jira request failed", "Jira
        # rate limit exceeded"). Prefixing any of them prints the subject twice
        # -- "Jira request failed: Jira request failed" for the transport's
        # generic branch (``jira.py``'s ``except Exception``), which is the one
        # a DNS failure, a TLS failure, a timeout or unparseable JSON takes.
        # ``JiraConfigurationError`` is a ``JiraError``, so it lands here too.
        print(str(error), file=sys.stderr)
        return 1
    _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
