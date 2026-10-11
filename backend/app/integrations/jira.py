"""Narrow, read-only Jira Cloud client with injectable transport for tests.

Mirrors ``app/integrations/graph.py`` in shape: an injectable transport, a
GET-only guard, and stdlib ``urllib.request`` rather than a runtime ``httpx``
dependency (``httpx`` stays dev-only, per ``backend/pyproject.toml``; nothing
here needs more than ``urlopen`` gives a fixed, single-host connector).

Jira differs from Graph in how a client comes to be constructed: Graph gets a
bearer token from an OAuth exchange (``app/services/oauth.py``) and this
client's counterpart never touches ``Settings`` directly. Jira has no such
intermediary -- a classic API token authenticates straight off ``Settings``
as Basic auth over ``email:token`` against ``https://<site>.atlassian.net``
(never the scoped-token host, which would 401). That makes ``JiraClient``
construction itself the natural fail-closed point, so ``from_settings()``
below calls ``Settings.jira_configuration_errors()`` rather than a caller
re-deriving the same presence check.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from ..config import Settings

JIRA_API_ROOT = "/rest/api/3"
Transport = Callable[[str, str, dict[str, str], dict[str, Any] | None], dict[str, Any]]

# AC8: the participation query -- every issue the token owner is assigned,
# reported, created, watches or voted on, bounded to a 15-minute relative
# window. The search index is eventually consistent (seconds to minutes) and
# ``updated`` is relative to the token owner's Jira profile timezone rather
# than UTC, so a relative window is safe where an absolute watermark would
# need a timezone conversion this connector does not do.
JIRA_PARTICIPATION_JQL = (
    "(assignee = currentUser() OR reporter = currentUser() OR creator = currentUser() "
    "OR watcher = currentUser() OR voter = currentUser()) AND updated >= -15m "
    "ORDER BY updated DESC"
)

# ``GET /rest/api/3/search/jql`` defaults ``fields`` to ``id`` alone; everything
# the queue needs to render a Jira issue must be named here explicitly.
JIRA_SEARCH_FIELDS = ("summary", "status", "priority", "assignee", "reporter", "updated", "project")

JIRA_SEARCH_PAGE_SIZE = 100
# Cap on how many ``nextPageToken`` pages a single call follows. This endpoint
# returns no ``total``, so nothing else stops a server that always returns a
# token (buggy, or worse) from paging forever; 20 pages of 100 issues each is
# far beyond what one account's 15-minute participation window will ever hold.
JIRA_SEARCH_MAX_PAGES = 20


class JiraError(RuntimeError):
    pass


class JiraConfigurationError(JiraError):
    """Raised when the configured Jira connection cannot be used as given --
    missing settings, or a site URL that is not a full ``https://<host>`` URL.
    Host identity is not checked: a well-formed https URL pointing somewhere
    other than the site is accepted here and fails at the request."""


class JiraRateLimitError(JiraError):
    def __init__(self, retry_after: str | None) -> None:
        message = "Jira rate limit exceeded" if retry_after is None else f"Jira rate limit exceeded, retry after {retry_after}"
        super().__init__(message)
        self.retry_after = retry_after


def default_transport(method: str, url: str, headers: dict[str, str], payload: dict[str, Any] | None) -> dict[str, Any]:
    if method != "GET":
        raise JiraError("Jira connector permits read-only GET requests")
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=15) as response:  # nosec B310: fixed Atlassian Cloud host
            return json.loads(response.read())
    except HTTPError as error:
        if error.code == 429:
            retry_after = error.headers.get("Retry-After") if error.headers is not None else None
            raise JiraRateLimitError(retry_after) from error
        raise JiraError(f"Jira request failed with status {error.code}") from error
    except Exception as error:  # transport details can contain sensitive request metadata
        raise JiraError("Jira request failed") from error


def _validated_base_url(site_url: str) -> str:
    """Reject anything that is not a full ``https://<host>`` URL up front.

    Without this, a schemeless ``JIRA_SITE_URL`` (``example.atlassian.net``)
    would reach ``urlopen`` and fail with an opaque ``URLError`` instead of a
    clear, fail-closed configuration error -- and a URL with a trailing path
    would double up once a request path is appended to it.
    """
    parsed = urlparse(site_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise JiraConfigurationError(f"JIRA_SITE_URL must be a full https URL like https://<site>.atlassian.net, got {site_url!r}")
    return f"{parsed.scheme}://{parsed.netloc}"


class JiraClient:
    def __init__(self, site_url: str, account_email: str, api_token: str, transport: Transport = default_transport) -> None:
        self._base_url = _validated_base_url(site_url)
        credentials = base64.b64encode(f"{account_email}:{api_token}".encode()).decode()
        self._headers = {"Authorization": f"Basic {credentials}", "Accept": "application/json"}
        self._transport = transport

    @classmethod
    def from_settings(cls, settings: "Settings", transport: Transport = default_transport) -> "JiraClient":
        """The one construction path every caller goes through -- reuses the same
        fail-closed check AC12 exercises rather than re-deriving it."""
        errors = settings.jira_configuration_errors()
        if errors:
            raise JiraConfigurationError(f"Jira is not configured: missing {', '.join(errors)}")
        site_url = settings.jira_site_url
        account_email = settings.jira_account_email
        api_token = settings.jira_api_token
        assert site_url is not None and account_email is not None and api_token is not None
        return cls(site_url, account_email, api_token.get_secret_value(), transport=transport)

    @property
    def base_url(self) -> str:
        """The validated ``https://<site>.atlassian.net`` root, for a caller (the
        sync handler) that needs to build a browse link rather than an API path."""
        return self._base_url

    def _get(self, path: str) -> dict[str, Any]:
        return self._transport("GET", f"{self._base_url}{path}", self._headers, None)

    def myself(self) -> dict[str, Any]:
        return self._get(f"{JIRA_API_ROOT}/myself")

    def _search(self, jql: str) -> list[dict[str, Any]]:
        """Fetch up to ``JIRA_SEARCH_MAX_PAGES`` pages of ``jql`` via
        ``GET /rest/api/3/search/jql`` -- the old ``/rest/api/3/search`` is removed
        (CHANGE-2046) and stays removed. Requests ``JIRA_SEARCH_FIELDS`` explicitly, since this
        endpoint otherwise returns only ``id``. Follows ``nextPageToken`` cursor pagination:
        there is no ``total``/``startAt`` on this endpoint, so an absent token is the only
        signal that the last page was reached, and paging is capped at ``JIRA_SEARCH_MAX_PAGES``
        so a server that always returns a token cannot loop forever.

        Shared by :meth:`search_participation_issues` and
        :meth:`search_project_issues` (T09) -- the two differ only in which JQL
        they hand this method, and every pagination rule ``test_jira_query.py``
        pins applies identically to both.
        """
        issues: list[dict[str, Any]] = []
        next_page_token: str | None = None
        for _ in range(JIRA_SEARCH_MAX_PAGES):
            params: dict[str, str] = {
                "jql": jql,
                "fields": ",".join(JIRA_SEARCH_FIELDS),
                "maxResults": str(JIRA_SEARCH_PAGE_SIZE),
            }
            if next_page_token is not None:
                params["nextPageToken"] = next_page_token
            response = self._get(f"{JIRA_API_ROOT}/search/jql?{urlencode(params)}")
            # ``or []``, not a bare ``.get(..., [])`` default: a malformed
            # ``{"issues": null}`` response returns ``None`` for a present key, so
            # the default alone never fires and ``.extend(None)`` raises
            # ``TypeError`` instead of the ``JiraError`` a sync's caller catches.
            issues.extend(response.get("issues") or [])
            next_page_token = response.get("nextPageToken")
            if not next_page_token:
                break
        return issues

    def search_participation_issues(self) -> list[dict[str, Any]]:
        """Every issue in the caller's participation window
        (``JIRA_PARTICIPATION_JQL``); see :meth:`_search`."""
        return self._search(JIRA_PARTICIPATION_JQL)

    def search_project_issues(self, project_key: str) -> list[dict[str, Any]]:
        """The most recently updated issues in one named project (T09, AC10) --
        the management visibility sync, unbounded by participation.

        **Capped, and the truncation is silent.** The clause orders by ``updated
        DESC`` and :meth:`_search` follows at most ``JIRA_SEARCH_MAX_PAGES`` pages
        of ``JIRA_SEARCH_PAGE_SIZE``, so this returns at most the 2000 most
        recently updated issues in the project; anything past that is dropped with
        no error and no marker on the result. Measured against a stub that always
        returns a ``nextPageToken``: 2000 issues, 20 pages, no raise. The cap's
        justification where it is defined is about one account's 15-minute
        participation window, and that reasoning does not carry here -- a
        management project holding more than 2000 issues is ordinary, so this
        call's callers get a recent-issues view of a project, not the whole of it.

        Its issues are stored and browsable, and never promoted on that ground
        alone: ``promotion.should_promote``'s Jira rule (rule A) decides Jira
        signals by assignee, not by which query found them, so an issue this call
        returns promotes only when it is also assigned to the owner.

        ``project_key`` is quoted in the JQL, with backslashes doubled before
        quotes are escaped (JQL's string escapes are ``\\\\`` and ``\\"``; escaping
        quotes first would let the second pass double the escaper's own
        backslash, so an embedded quote reopens the literal, and escaping quotes
        alone would let a trailing backslash consume the closing quote). This
        matters because -- unlike
        ``JIRA_PARTICIPATION_JQL`` -- the clause is built from
        ``JIRA_MANAGEMENT_PROJECT_KEY``, a configured value rather than a fixed
        literal; ``test_jira_project_visibility.py`` pins both replacements with
        keys that carry a backslash and a quote.
        """
        escaped_key = project_key.replace("\\", "\\\\").replace('"', '\\"')
        return self._search(f'project = "{escaped_key}" ORDER BY updated DESC')


def extract_adf_plain_text(document: dict[str, Any] | None) -> str | None:
    """Extract plain text from an Atlassian Document Format issue description.

    No formatting fidelity: headings, lists and marks all collapse to their
    words, joined by single spaces -- this is not a non-goal Markdown renderer,
    just enough to show a description as readable text. ``None`` in, ``None``
    out: an issue with no description carries no ADF document at all.
    """
    if document is None:
        return None
    return " ".join(_adf_text_nodes(document))


def _adf_text_nodes(node: Any) -> list[str]:
    if not isinstance(node, dict):
        return []
    if node.get("type") == "text":
        text = node.get("text", "")
        return [text] if text else []
    texts: list[str] = []
    for child in node.get("content") or []:
        texts.extend(_adf_text_nodes(child))
    return texts
