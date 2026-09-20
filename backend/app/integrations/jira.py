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
from urllib.parse import urlparse
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from ..config import Settings

JIRA_API_ROOT = "/rest/api/3"
Transport = Callable[[str, str, dict[str, str], dict[str, Any] | None], dict[str, Any]]


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

    def _get(self, path: str) -> dict[str, Any]:
        return self._transport("GET", f"{self._base_url}{path}", self._headers, None)

    def myself(self) -> dict[str, Any]:
        return self._get(f"{JIRA_API_ROOT}/myself")
