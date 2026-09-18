"""Hand correction of the promotion heuristic (T08, AC10).

``should_promote`` gets it wrong sometimes -- a real inbox is not a fixture -- and
the owner needs two ways to correct it by hand: promote a ``Source`` the rules
missed, and dismiss a ``WorkItem`` that should never have been promoted.

Dismissing is a status transition, never a delete (B36 already pins the hand
-delete path as a permanent rejection; this is the other one). The status must
survive both places a source could otherwise be offered to the heuristic again --
an ordinary re-sync through ``promote_signals`` and the T06 backfill through
``backfill_promoted_sources`` -- so each has its own test rather than one that
only proves the API route flips a column.

Promoting by hand must also write the same ``source_promotions`` ledger row
``promote_signals`` writes (B44), or the backfill would read the source as never
judged and offer it to the heuristic again, reporting a promotion this endpoint
already made.

Every fixture here is synthetic; no real mail content lives in this repository.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import engine
from app.main import app
from app.models import SourcePromotion, WorkItem, WorkStatus
from app.services.backfill import backfill_promoted_sources
from app.services.graph import persist_signals
from app.services.promotion import promote_signals

MAILBOX = "owner@contoso.com"
OWNER = (MAILBOX,)
BEARER = {"Authorization": "Bearer test-local-agent-token"}


def _email(**overrides: Any) -> dict[str, Any]:
    """A normalized inbox message a colleague sent to the owner, by default."""
    return {
        "external_id": "outlook:direct-1",
        "source_kind": "outlook_email",
        "title": "Can you review the migration plan?",
        "excerpt": "Please take a look when you get a chance.",
        "source_url": "https://outlook.office.com/mail/direct-1",
        "observed_at": "2026-09-18T08:30:00Z",
        "sender": "colleague@contoso.com",
        "sender_kind": "user",
        "to_recipients": [MAILBOX],
        "headers": {},
        **overrides,
    }


def _create_source(client: TestClient, **overrides: Any) -> dict:
    payload = {
        "kind": "outlook_email",
        "external_id": "outlook:missed-1",
        "subject": "Can you review the migration plan?",
        "excerpt": "Please take a look when you get a chance.",
        "url": "https://outlook.office.com/mail/missed-1",
        **overrides,
    }
    created = client.post("/api/sources", json=payload, headers=BEARER)
    assert created.status_code == 201, created.text
    return created.json()


def _create_work_item(client: TestClient, **overrides: Any) -> dict:
    payload = {
        "title": "Wrongly promoted",
        "source_kind": "outlook_email",
        "source_external_id": "outlook:wrong-1",
        "evidence": [{"source_kind": "outlook_email", "external_id": "outlook:wrong-1",
                     "excerpt": "irrelevant newsletter"}],
        **overrides,
    }
    created = client.post("/api/work-items", json=payload, headers=BEARER)
    assert created.status_code == 201, created.text
    return created.json()


# -- promote_endpoint ---------------------------------------------------------


def test_promote_endpoint_creates_a_work_item_for_a_source_the_rules_missed():
    with TestClient(app) as client:
        source = _create_source(client)

        response = client.post(f"/api/sources/{source['id']}/promote", headers=BEARER)

        assert response.status_code == 201, response.text
        item = response.json()
        assert item["source_external_id"] == source["external_id"]
        assert item["status"] == "pending"
        assert item["evidence"][0]["excerpt"] == source["excerpt"]


def test_promote_endpoint_writes_the_source_promotion_ledger_row():
    """B44: without the ledger row the backfill would re-offer this source."""
    with TestClient(app) as client:
        source = _create_source(client)
        assert client.post(f"/api/sources/{source['id']}/promote", headers=BEARER).status_code == 201

    with Session(engine) as session:
        assert session.query(SourcePromotion).filter_by(source_id=UUID(source["id"])).count() == 1

        result = backfill_promoted_sources(session)

        assert result == {"considered": 0, "new_work_items": 0, "judged_without_context": 0,
                          "promoted_without_owner_check": 0}


def test_promote_endpoint_rejects_a_source_already_promoted():
    with TestClient(app) as client:
        source = _create_source(client)
        first = client.post(f"/api/sources/{source['id']}/promote", headers=BEARER)
        assert first.status_code == 201

        second = client.post(f"/api/sources/{source['id']}/promote", headers=BEARER)
        assert second.status_code == 409


def test_promote_endpoint_404s_for_an_unknown_source():
    with TestClient(app) as client:
        response = client.post("/api/sources/00000000-0000-0000-0000-000000000000/promote", headers=BEARER)
        assert response.status_code == 404


def test_promote_endpoint_refuses_a_caller_without_local_write_access():
    with TestClient(app) as client:
        source = _create_source(client)
        assert client.post(f"/api/sources/{source['id']}/promote").status_code == 401


def test_promote_endpoint_requires_csrf_on_a_browser_session():
    with TestClient(app) as client:
        source = _create_source(client)
        login = client.post("/api/session", headers=BEARER)
        assert login.status_code == 201
        csrf = login.json()["csrf_token"]

        denied = client.post(f"/api/sources/{source['id']}/promote")
        assert denied.status_code == 403

        allowed = client.post(f"/api/sources/{source['id']}/promote", headers={"X-CSRF-Token": csrf})
        assert allowed.status_code == 201


# -- dismiss_endpoint ----------------------------------------------------------


def test_dismiss_endpoint_transitions_status_without_deleting_the_work_item():
    with TestClient(app) as client:
        created = _create_work_item(client)

        response = client.post(f"/api/work-items/{created['id']}/dismiss", headers=BEARER)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "dismissed"
        assert body["evidence"][0]["excerpt"] == "irrelevant newsletter"

        fetched = client.get(f"/api/work-items/{created['id']}", headers=BEARER)
        assert fetched.json()["status"] == "dismissed"


def test_dismiss_endpoint_404s_for_an_unknown_item():
    with TestClient(app) as client:
        response = client.post("/api/work-items/00000000-0000-0000-0000-000000000000/dismiss", headers=BEARER)
        assert response.status_code == 404


def test_dismiss_endpoint_refuses_a_caller_without_local_write_access():
    with TestClient(app) as client:
        created = _create_work_item(client)
        assert client.post(f"/api/work-items/{created['id']}/dismiss").status_code == 401


def test_dismiss_endpoint_requires_csrf_on_a_browser_session():
    with TestClient(app) as client:
        created = _create_work_item(client)
        login = client.post("/api/session", headers=BEARER)
        assert login.status_code == 201
        csrf = login.json()["csrf_token"]

        denied = client.post(f"/api/work-items/{created['id']}/dismiss")
        assert denied.status_code == 403

        allowed = client.post(f"/api/work-items/{created['id']}/dismiss", headers={"X-CSRF-Token": csrf})
        assert allowed.status_code == 200


def test_dismiss_endpoint_survives_a_resync_of_the_same_signal():
    """A live re-sync must not resurrect a dismissed item under the same source."""
    signal = _email(external_id="outlook:resync-1")
    with Session(engine) as session:
        persist_signals(session, [signal])
        assert promote_signals(session, [signal], OWNER) == 1
        item_id = session.query(WorkItem).one().id

    with TestClient(app) as client:
        assert client.post(f"/api/work-items/{item_id}/dismiss", headers=BEARER).status_code == 200

    with Session(engine) as session:
        assert promote_signals(session, [signal], OWNER) == 0, "the re-sync must not create a second work item"

    with Session(engine) as session:
        assert session.query(WorkItem).count() == 1
        item = session.query(WorkItem).one()
        assert item.status == WorkStatus.dismissed


def test_dismiss_endpoint_survives_the_backfill():
    """T06's backfill must not undo a dismissal either -- it is not just the sync path."""
    signal = _email(external_id="outlook:backfill-dismiss-1")
    with Session(engine) as session:
        persist_signals(session, [signal])
        assert promote_signals(session, [signal], OWNER) == 1
        item_id = session.query(WorkItem).one().id

    with TestClient(app) as client:
        assert client.post(f"/api/work-items/{item_id}/dismiss", headers=BEARER).status_code == 200

    with Session(engine) as session:
        result = backfill_promoted_sources(session)

        assert result == {"considered": 0, "new_work_items": 0, "judged_without_context": 0,
                          "promoted_without_owner_check": 0}
        item = session.query(WorkItem).one()
        assert item.status == WorkStatus.dismissed
