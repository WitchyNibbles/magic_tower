"""Narrow, read-only Freshservice client with injectable transport for tests.

Shaped like ``app/integrations/jira.py``: an injectable transport, a GET-only guard,
stdlib ``urllib.request`` rather than a runtime ``httpx`` dependency, and one
``from_settings()`` construction path that reuses
``Settings.freshservice_configuration_errors()`` so the fail-closed check lives in
one place.

Freshservice authenticates with HTTP Basic auth, the API key as the username and
the literal ``X`` as the password. Its ticket filter (``GET /api/v2/tickets/filter``)
takes the query wrapped in double quotes, returns 30 tickets a page with no
``per_page``, and reports a ``total`` the client uses to stop early.

Nothing here writes: ``default_transport`` refuses any method but ``GET``, and no
client method issues anything else.
"""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

if TYPE_CHECKING:
    from ..config import Settings

logger = logging.getLogger(__name__)

FRESHSERVICE_API_ROOT = "/api/v2"
Transport = Callable[[str, str, dict[str, str], dict[str, Any] | None], dict[str, Any]]

# The filter endpoint's fixed page size (it takes no ``per_page``), and the most pages
# one search follows. Deep paging is discouraged by Freshservice and the owner's own
# assigned tickets never come near it; 10 pages is 300 tickets, and past that the
# result says it was cut short rather than looping on.
FRESHSERVICE_PAGE_SIZE = 30
FRESHSERVICE_FILTER_MAX_PAGES = 10
# Freshservice ticket statuses 2 (Open) and 3 (Pending): the ones still owed work.
_OPEN_STATUS = 2
_PENDING_STATUS = 3


class SearchResult(list[dict[str, Any]]):
    """The tickets a search returned, plus whether the page cap cut it short.

    A ``list`` so every caller that only iterates keeps working. ``truncated`` is
    true when the last page allowed was full and there may be more. ``total`` is the
    count Freshservice reported for the whole query, or ``None`` when it gave none
    that can be trusted as a number.
    """

    truncated: bool = False
    total: int | None = None


class FreshserviceError(RuntimeError):
    """A failure with a message written to be shown: it never names a URL, header,
    key or address."""


class FreshserviceConfigurationError(FreshserviceError):
    """Raised when the configured connection cannot be used as given -- missing
    settings, or a URL that is not a full ``https://<host>`` URL."""


class FreshserviceRateLimitError(FreshserviceError):
    def __init__(self, retry_after: str | None) -> None:
        message = "Freshservice rate limit exceeded" if retry_after is None else f"Freshservice rate limit exceeded, retry after {retry_after}"
        super().__init__(message)
        self.retry_after = retry_after


@dataclass(frozen=True)
class FreshserviceAgent:
    """An agent as the lookups report one: the id tickets are assigned by, and a
    display name (possibly empty) for the check tool."""

    id: int
    name: str


class _RefuseRedirects(HTTPRedirectHandler):
    """``urlopen`` follows a 3xx and copies the request's headers, Authorization
    included, to wherever it points -- any host, even plain http. The API key must
    only ever go to the configured site, so a redirect is an error, not a hop."""

    def redirect_request(self, *_: object, **__: object) -> None:
        raise FreshserviceError("Freshservice request was redirected")


_opener = build_opener(_RefuseRedirects)


def default_transport(method: str, url: str, headers: dict[str, str], payload: dict[str, Any] | None) -> dict[str, Any]:
    if method != "GET":
        raise FreshserviceError("Freshservice connector permits read-only GET requests")
    request = Request(url, headers=headers, method="GET")
    try:
        with _opener.open(request, timeout=15) as response:
            return json.loads(response.read())
    except FreshserviceError:
        raise
    except HTTPError as error:
        if error.code == 429:
            retry_after = error.headers.get("Retry-After") if error.headers is not None else None
            raise FreshserviceRateLimitError(retry_after) from error
        raise FreshserviceError(f"Freshservice request failed with status {error.code}") from error
    except Exception as error:  # transport details can contain sensitive request metadata
        raise FreshserviceError("Freshservice request failed") from error


def _is_int(value: object) -> bool:
    """An ``int`` that is not a ``bool`` -- ``True`` is never an id or a count anyone meant."""
    return isinstance(value, int) and not isinstance(value, bool)


def assigned_tickets_query(agent_id: int, since: date) -> str:
    """The filter query for the owner's tickets: every Open or Pending ticket assigned
    to ``agent_id`` whatever its age, plus every assigned ticket (any status) updated
    after ``since``.

    The status clause catches custom statuses and resolutions through the date, and
    keeps an old, still-open ticket from falling out of the window. The filter's date
    comparison takes ``yyyy-mm-dd`` only, so ``since`` is a date, not a time.

    Both values are spliced into the query text, so each is refused unless it is
    exactly the type that cannot carry more query: an ``int`` for the id (not a
    ``bool``) and a ``date`` for the cut-off.
    """
    if not _is_int(agent_id):
        raise ValueError(f"agent_id must be an int, got {agent_id!r}")
    if not isinstance(since, date):
        raise ValueError(f"since must be a date, got {since!r}")
    return (
        f"agent_id:{agent_id} AND "
        f"(status:{_OPEN_STATUS} OR status:{_PENDING_STATUS} OR updated_at:>'{since:%Y-%m-%d}')"
    )


def _validated_base_url(url: str) -> str:
    """Reject anything that is not a full ``https://<host>`` URL up front.

    A schemeless value would reach ``urlopen`` and fail with an opaque ``URLError``,
    and a trailing path would double up once a request path is appended. The message
    names the setting and never echoes the value.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise FreshserviceConfigurationError("FRESHSERVICE_URL must be a full https URL like https://<domain>.freshservice.com")
    return f"{parsed.scheme}://{parsed.netloc}"


def _agent_from(record: object) -> FreshserviceAgent | None:
    """An agent from one JSON object, or ``None`` when it has no usable ``id``.

    Tolerant on purpose: the agent endpoints' shapes were not verified against a real
    site, and an unrecognised one means "unknown owner" (which the sync reports and
    fails closed on), never a crash.
    """
    if not isinstance(record, dict) or not _is_int(record.get("id")):
        return None
    parts = [record.get("first_name"), record.get("last_name")]
    name = " ".join(part.strip() for part in parts if isinstance(part, str) and part.strip())
    return FreshserviceAgent(id=record["id"], name=name)


class FreshserviceClient:
    def __init__(self, base_url: str, api_key: str, transport: Transport = default_transport) -> None:
        self._base_url = _validated_base_url(base_url)
        credentials = base64.b64encode(f"{api_key}:X".encode()).decode()
        self._headers = {"Authorization": f"Basic {credentials}", "Accept": "application/json"}
        self._transport = transport

    @classmethod
    def from_settings(cls, settings: "Settings", transport: Transport = default_transport) -> "FreshserviceClient":
        """The one construction path every caller goes through."""
        errors = settings.freshservice_configuration_errors()
        if errors:
            raise FreshserviceConfigurationError(f"Freshservice is not configured: missing {', '.join(errors)}")
        url = settings.freshservice_url
        api_key = settings.freshservice_api_key
        assert url is not None and api_key is not None
        return cls(url, api_key.get_secret_value(), transport=transport)

    @property
    def base_url(self) -> str:
        """The validated ``https://<domain>.freshservice.com`` root, for a caller that
        builds a ticket link rather than an API path."""
        return self._base_url

    def _get(self, path: str) -> dict[str, Any]:
        response = self._transport("GET", f"{self._base_url}{path}", self._headers, None)
        if not isinstance(response, dict):
            raise FreshserviceError("Freshservice returned an unexpected response")
        return response

    def current_agent(self) -> FreshserviceAgent | None:
        """The agent the API key belongs to (``GET /api/v2/agents/me``), or ``None``
        when the response does not name one."""
        return _agent_from(self._get(f"{FRESHSERVICE_API_ROOT}/agents/me").get("agent"))

    def find_agent_by_email(self, email: str) -> FreshserviceAgent | None:
        """The agent with this address (``GET /api/v2/agents?email=...``), or ``None``.

        The address is matched again on the way back, case-insensitively: if the API
        did not honour the filter, taking the first agent it listed would make
        somebody else the owner.
        """
        response = self._get(f"{FRESHSERVICE_API_ROOT}/agents?{urlencode({'email': email}, quote_via=quote)}")
        agents = response.get("agents")
        if not isinstance(agents, list):
            return None
        wanted = email.strip().lower()
        for record in agents:
            if isinstance(record, dict) and isinstance(record.get("email"), str) and record["email"].strip().lower() == wanted:
                agent = _agent_from(record)
                if agent is not None:
                    return agent
        return None

    def search_assigned_tickets(self, agent_id: int, since: date) -> SearchResult:
        """Up to ``FRESHSERVICE_FILTER_MAX_PAGES`` pages of :func:`assigned_tickets_query`.

        Stops at the first page that is short or empty, or once the collected count
        reaches the ``total`` Freshservice reports. Running out of allowed pages with
        more still on offer is truncation: the result says so (``truncated``) and a
        WARNING names the query kind, never the query.

        The query is wrapped in double quotes, as the filter endpoint requires, and
        percent-encoded (spaces as ``%20``, not ``+``).
        """
        query = f'"{assigned_tickets_query(agent_id, since)}"'
        tickets = SearchResult()
        for page in range(1, FRESHSERVICE_FILTER_MAX_PAGES + 1):
            params = urlencode({"query": query, "page": page}, quote_via=quote)
            response = self._get(f"{FRESHSERVICE_API_ROOT}/tickets/filter?{params}")
            # ``or []``, not a bare ``.get(..., [])`` default: ``{"tickets": null}``
            # returns ``None`` for a present key, so the default alone never fires.
            page_tickets = response.get("tickets") or []
            tickets.extend(page_tickets)
            total = response.get("total")
            tickets.total = total if _is_int(total) else None
            if len(page_tickets) < FRESHSERVICE_PAGE_SIZE or (tickets.total is not None and len(tickets) >= tickets.total):
                break
        else:
            tickets.truncated = True
            logger.warning(
                "Freshservice assigned-tickets search stopped after %s pages; older tickets were not fetched",
                FRESHSERVICE_FILTER_MAX_PAGES,
            )
        return tickets
