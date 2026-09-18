"""End-to-end proof: a fixture Graph sync leaves ``GET /api/work-items`` non-empty.

``test_sync_dispatch.py``, ``test_pagination.py`` and ``test_promotion.py`` each
pin one layer of this path in isolation -- dispatch, the envelope shape, and the
heuristic's persistence. None of them proves the layers actually compose: a sync
that writes rows a route never reads, or a route that reads rows a sync never
writes, would still leave every one of those tests green. This test drives the
*whole* path in one place -- an injected HTTP transport, through
``app.services.sync.sync``, through the real database, out through the FastAPI
route -- so nothing between "Graph answered" and "the GUI's queue has an item"
is stubbed.

A single-layer stub this test refuses to take: writing the ``WorkItem`` and its
``WorkEvidence`` directly through the ORM (as a shortcut for "a sync happened")
would make the API assertion pass while ``fetch_signals``, ``persist_signals`` and
``promote_signals`` never ran at all, and a broken normalization step would never
be caught. So the only thing this test controls is the wire: the ``Transport``
callable Graph's client takes (``app/integrations/graph.py``), the same seam
``test_promotion.py`` uses. Everything downstream of it -- sync, persistence,
promotion, the API route, the response schema -- runs unmodified.

Every fixture here is synthetic; no real mail content lives in this repository.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import engine
from app.integrations.graph import GraphClient
from app.main import app
from app.services.crypto import EncryptedTokenStore, generate_encryption_key
from app.services.sync import sync

TOKEN_HEADERS = {"Authorization": "Bearer test-local-agent-token"}
MAILBOX = "owner@contoso.com"
PRINCIPAL = "owner@contoso.onmicrosoft.com"
COLLEAGUE = "colleague@contoso.com"
# Distinctive enough that finding it in the API response cannot be a coincidence.
MARKER = "sync-populates-api-marker-9c1e2f"

PROFILE = {"id": "expected-oid", "userPrincipalName": PRINCIPAL, "mail": MAILBOX}
# One actionable message addressed directly to the owner, and one automated
# digest a correct heuristic must reject -- so the test also fails if promotion
# stops discriminating and lets everything through.
INBOX = [
    {
        "id": "direct", "subject": "Please review the proposal", "bodyPreview": MARKER,
        "webLink": "https://outlook.office.com/mail/direct", "receivedDateTime": "2026-09-18T08:30:00Z",
        "from": {"emailAddress": {"address": COLLEAGUE}},
        "toRecipients": [{"emailAddress": {"address": MAILBOX}}],
        "internetMessageHeaders": [],
    },
    {
        "id": "bulk", "subject": "Weekly digest", "bodyPreview": "unsubscribe below",
        "from": {"emailAddress": {"address": "updates@vendor.example"}},
        "toRecipients": [{"emailAddress": {"address": MAILBOX}}],
        "internetMessageHeaders": [{"name": "List-Unsubscribe", "value": "<https://vendor.example/u>"}],
    },
]
CHATS: list[dict[str, Any]] = []


def _selected(url: str, row: dict[str, Any]) -> dict[str, Any]:
    """Only the ``$select``ed fields, as Graph answers; what the client forgets to ask for, it never sees."""
    fields = parse_qs(urlparse(url).query)["$select"][0].split(",")
    return {field: row[field] for field in fields if field in row}


def _fixture_transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict[str, Any]:
    if "/me?$select=" in url:
        return _selected(url, PROFILE)
    if "/me/mailFolders/" in url:
        return {"value": [_selected(url, row) for row in INBOX]}
    if "/me/chats" in url:
        return {"value": [_selected(url, chat) for chat in CHATS]}
    raise AssertionError(url)


def test_sync_populates_api_with_promoted_work_items_and_evidence(tmp_path: Path) -> None:
    encryption_key = generate_encryption_key()
    settings = Settings(
        microsoft_tenant_id="tenant", microsoft_client_id="client", microsoft_client_secret="secret",
        microsoft_target_user_id="expected-oid", app_encryption_key=encryption_key,
        token_store_path=tmp_path / "tokens",
    )
    EncryptedTokenStore(settings.token_store_path, encryption_key).save({"access_token": "token"})

    with Session(engine) as session:
        result = sync(settings, session, client=GraphClient("token", _fixture_transport))

    assert result["new_sources"] == 2, "both the direct message and the digest must be stored as sources"
    assert result["new_work_items"] == 1, "only the direct message is actionable"

    with TestClient(app) as client:
        response = client.get("/api/work-items", headers=TOKEN_HEADERS)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1

    item = body["items"][0]
    assert item["source_external_id"] == "outlook:direct"
    assert item["status"] == "pending"
    assert len(item["evidence"]) == 1
    assert item["evidence"][0]["excerpt"] == MARKER
