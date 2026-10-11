"""Browser sessions live in the database, so an API restart does not sign the owner out.

A restart is simulated by writing a ``BrowserSession`` row directly, as an earlier
process would have, and then presenting its cookie to the running app: nothing
in this process ever saw that session being created.
"""

import hashlib
import time

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import BrowserSession
from app.security import SESSION_COOKIE

TOKEN = {"Authorization": "Bearer test-local-agent-token"}


def _hash(session_id: str) -> str:
    return hashlib.sha256(session_id.encode()).hexdigest()


def _store(session_id: str, csrf_token: str, expires_at: float) -> None:
    with SessionLocal() as db:
        db.add(BrowserSession(id_hash=_hash(session_id), csrf_token=csrf_token, expires_at=expires_at))
        db.commit()


def _rows() -> list[BrowserSession]:
    with SessionLocal() as db:
        return list(db.scalars(select(BrowserSession)))


def test_a_session_created_by_an_earlier_process_is_still_honoured() -> None:
    _store("from-before-the-restart", "csrf-from-before", time.time() + 3600)
    with TestClient(app, cookies={SESSION_COOKIE: "from-before-the-restart"}) as client:
        response = client.get("/api/session")
    assert response.status_code == 200
    assert response.json() == {"csrf_token": "csrf-from-before"}


def test_the_database_holds_a_hash_of_the_session_id_never_the_cookie_value() -> None:
    with TestClient(app) as client:
        assert client.post("/api/session", headers=TOKEN).status_code == 201
        session_id = client.cookies[SESSION_COOKIE]
    rows = _rows()
    assert [row.id_hash for row in rows] == [_hash(session_id)]
    assert all(session_id not in (row.id_hash, row.csrf_token) for row in rows)


def test_an_expired_session_is_refused_and_deleted() -> None:
    _store("expired", "csrf", time.time() - 1)
    with TestClient(app, cookies={SESSION_COOKIE: "expired"}) as client:
        assert client.get("/api/session").status_code == 401
    assert _rows() == []


def test_signing_out_deletes_the_session_row() -> None:
    with TestClient(app) as client:
        csrf = client.post("/api/session", headers=TOKEN).json()["csrf_token"]
        assert client.delete("/api/session", headers={"X-CSRF-Token": csrf}).status_code == 204
    assert _rows() == []


def test_starting_a_session_clears_out_expired_ones() -> None:
    _store("long-gone", "csrf", time.time() - 1)
    with TestClient(app) as client:
        assert client.post("/api/session", headers=TOKEN).status_code == 201
    id_hashes = [row.id_hash for row in _rows()]
    assert len(id_hashes) == 1
    assert _hash("long-gone") not in id_hashes
