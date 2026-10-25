"""Narrow, read-only Microsoft Graph client with injectable transport for tests."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
Transport = Callable[[str, str, dict[str, str], dict[str, Any] | None], dict[str, Any]]


class GraphError(RuntimeError):
    pass


class GraphAuthError(GraphError):
    """Graph answered 401: the access token is expired or revoked."""


# A throttled request is retried this many times. The wait is Graph's own
# ``Retry-After`` when it sends one, capped so one sync cannot hang for minutes, and
# otherwise doubles from one second.
MAX_RETRIES = 3
MAX_RETRY_AFTER_SECONDS = 30
# Graph signals throttling with 429, and with 503 when the service itself is busy.
THROTTLE_STATUSES = frozenset({429, 503})


class GraphThrottledError(GraphError):
    """Graph answered 429 or 503; ``retry_after`` is its requested wait in seconds, if it sent one."""

    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__("Microsoft Graph is throttling requests")
        self.retry_after = retry_after


def _retry_after(value: str | None) -> float | None:
    """Graph sends ``Retry-After`` as a number of seconds; anything else is ignored."""
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if 0 <= seconds < float("inf") else None


class _RefuseRedirects(HTTPRedirectHandler):
    """``urlopen`` follows a 3xx and copies the request's headers, Authorization
    included, to wherever it points -- any host, even plain http. The bearer token
    must only ever go to Graph, so a redirect is an error, not a hop."""

    def redirect_request(self, *_: object, **__: object) -> None:
        raise GraphError("Microsoft Graph request was redirected")


_opener = build_opener(_RefuseRedirects)


def default_transport(method: str, url: str, headers: dict[str, str], payload: dict[str, Any] | None) -> dict[str, Any]:
    if method != "GET":
        raise GraphError("Graph connector permits read-only GET requests")
    request = Request(url, headers=headers, method="GET")
    try:
        import json
        with _opener.open(request, timeout=15) as response:
            return json.loads(response.read())
    except GraphError:
        raise
    except HTTPError as error:
        if error.code == 401:
            raise GraphAuthError("Microsoft Graph rejected the access token") from error
        if error.code in THROTTLE_STATUSES:
            raise GraphThrottledError(_retry_after(error.headers.get("Retry-After"))) from error
        raise GraphError("Microsoft Graph request failed") from error
    except Exception as error:  # transport details can contain sensitive request metadata
        raise GraphError("Microsoft Graph request failed") from error


class GraphClient:
    def __init__(self, access_token: str, transport: Transport = default_transport, sleep: Callable[[float], None] = time.sleep) -> None:
        self._headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
        self._transport = transport
        self._sleep = sleep

    def _get_url(self, url: str) -> dict[str, Any]:
        for attempt in range(MAX_RETRIES):
            try:
                return self._transport("GET", url, self._headers, None)
            except GraphThrottledError as error:
                wait = error.retry_after if error.retry_after is not None else 2 ** attempt
                self._sleep(min(wait, MAX_RETRY_AFTER_SECONDS))
        # The last attempt is not retried: throttling here reaches the caller.
        return self._transport("GET", url, self._headers, None)

    def _get(self, path: str) -> dict[str, Any]:
        return self._get_url(f"{GRAPH_ROOT}{path}")

    def _get_paged(self, path: str, limit: int) -> list[dict[str, Any]]:
        """Collect ``value`` rows across ``@odata.nextLink`` pages, up to ``limit``.

        A next link is followed only while it stays under ``GRAPH_ROOT``: it is an
        absolute URL from the response, and following it sends the bearer token.
        An empty page ends paging, so a server that keeps linking to nothing cannot
        loop the client.
        """
        rows: list[dict[str, Any]] = []
        url: str | None = f"{GRAPH_ROOT}{path}"
        while url and len(rows) < limit:
            page = self._get_url(url)
            values = page.get("value", [])
            rows.extend(values)
            url = page.get("@odata.nextLink") if values else None
            if url and not url.startswith(f"{GRAPH_ROOT}/"):
                raise GraphError("Microsoft Graph returned a next link outside the Graph API")
        return rows[:limit]

    def me(self) -> dict[str, Any]:
        # ``mail`` can differ from the principal name on alias-domain tenants; the
        # promotion heuristic accepts mail addressed to either.
        return self._get("/me?$select=id,userPrincipalName,mail")

    def inbox_messages(self, limit: int = 50) -> list[dict[str, Any]]:
        # Recipients and headers are what the promotion heuristic reads to tell mail
        # addressed to the user from a bulk mailing; both are returned only on $select.
        select = "id,subject,bodyPreview,webLink,receivedDateTime,from,toRecipients,internetMessageHeaders"
        path = f"/me/mailFolders/inbox/messages?$top={limit}&$select={quote(select, safe=',')}"
        return self._get_paged(path, limit)
