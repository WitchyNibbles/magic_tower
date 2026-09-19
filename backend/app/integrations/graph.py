"""Narrow, read-only Microsoft Graph client with injectable transport for tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
Transport = Callable[[str, str, dict[str, str], dict[str, Any] | None], dict[str, Any]]


class GraphError(RuntimeError):
    pass


def default_transport(method: str, url: str, headers: dict[str, str], payload: dict[str, Any] | None) -> dict[str, Any]:
    if method != "GET":
        raise GraphError("Graph connector permits read-only GET requests")
    request = Request(url, headers=headers, method="GET")
    try:
        import json
        with urlopen(request, timeout=15) as response:  # nosec B310: fixed Microsoft endpoint
            return json.loads(response.read())
    except Exception as error:  # transport details can contain sensitive request metadata
        raise GraphError("Microsoft Graph request failed") from error


class GraphClient:
    def __init__(self, access_token: str, transport: Transport = default_transport) -> None:
        self._headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
        self._transport = transport

    def _get(self, path: str) -> dict[str, Any]:
        return self._transport("GET", f"{GRAPH_ROOT}{path}", self._headers, None)

    def me(self) -> dict[str, Any]:
        # ``mail`` can differ from the principal name on alias-domain tenants; the
        # promotion heuristic accepts mail addressed to either.
        return self._get("/me?$select=id,userPrincipalName,mail")

    def inbox_messages(self, limit: int = 50) -> list[dict[str, Any]]:
        # Recipients and headers are what the promotion heuristic reads to tell mail
        # addressed to the user from a bulk mailing; both are returned only on $select.
        select = "id,subject,bodyPreview,webLink,receivedDateTime,from,toRecipients,internetMessageHeaders"
        path = f"/me/mailFolders/inbox/messages?$top={limit}&$select={quote(select, safe=',')}"
        return self._get(path).get("value", [])
