"""Pagination and indexes for the two list endpoints.

``GET /api/work-items`` and ``GET /api/sources`` used to return every row with no
limit, so the response grew without bound as the queue did. These tests hold the
envelope shape shut at the FastAPI boundary -- not just in the service helper --
because a helper that paginates correctly proves nothing about a route that never
calls it with the caller's numbers, and hold the migration's indexes shut against
a real ``alembic upgrade head`` database, because an ``index=True`` in
``app.models`` that never reaches a revision is invisible to a test that only
inspects ``Base.metadata``.

Every fixture here is synthetic; no real mail content lives in this repository.
"""

import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from app.main import app
from app.services.work_items import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT

BACKEND_DIR = Path(__file__).resolve().parents[1]
TOKEN_HEADERS = {"Authorization": "Bearer test-local-agent-token"}


def _create_work_item(client: TestClient, index: int, status: str = "pending") -> dict:
    payload = {
        "title": f"Work item {index}",
        "source_kind": "manual",
        "source_external_id": f"manual:item-{index}",
        "status": status,
    }
    # status is not settable on create; set it via a follow-up PATCH so the fixture
    # can still exercise the status filter.
    created = client.post("/api/work-items", json={k: v for k, v in payload.items() if k != "status"},
                          headers=TOKEN_HEADERS)
    assert created.status_code == 201, created.text
    item = created.json()
    if status != "pending":
        patched = client.patch(f"/api/work-items/{item['id']}", json={"status": status}, headers=TOKEN_HEADERS)
        assert patched.status_code == 200, patched.text
        item = patched.json()
    return item


def _create_source(client: TestClient, index: int, kind: str = "manual") -> dict:
    created = client.post("/api/sources", json={"kind": kind, "external_id": f"{kind}:source-{index}"},
                          headers=TOKEN_HEADERS)
    assert created.status_code == 201, created.text
    return created.json()


def test_pagination_applies_a_default_limit_when_the_caller_passes_none():
    with TestClient(app) as client:
        for i in range(DEFAULT_PAGE_LIMIT + 5):
            _create_work_item(client, i)

        response = client.get("/api/work-items", headers=TOKEN_HEADERS)

        assert response.status_code == 200
        body = response.json()
        assert body["limit"] == DEFAULT_PAGE_LIMIT
        assert body["offset"] == 0
        assert len(body["items"]) == DEFAULT_PAGE_LIMIT
        assert body["total"] == DEFAULT_PAGE_LIMIT + 5


def test_pagination_honours_limit_and_offset():
    with TestClient(app) as client:
        created = [_create_work_item(client, i) for i in range(10)]

        response = client.get("/api/work-items", params={"limit": 3, "offset": 2}, headers=TOKEN_HEADERS)

        assert response.status_code == 200
        body = response.json()
        assert body["limit"] == 3
        assert body["offset"] == 2
        assert len(body["items"]) == 3
        assert body["total"] == 10
        # Items are sorted by ``updated_at`` descending, so the most recently
        # created item is first; offset 2 skips the two newest.
        expected_ids = [item["id"] for item in reversed(created)][2:5]
        assert [item["id"] for item in body["items"]] == expected_ids


def test_pagination_enforces_the_cap_when_a_caller_asks_for_more():
    with TestClient(app) as client:
        response = client.get("/api/work-items", params={"limit": MAX_PAGE_LIMIT + 1}, headers=TOKEN_HEADERS)

        assert response.status_code == 422


def test_pagination_rejects_a_negative_limit_or_offset_deterministically():
    with TestClient(app) as client:
        assert client.get("/api/work-items", params={"limit": -1}, headers=TOKEN_HEADERS).status_code == 422
        assert client.get("/api/work-items", params={"offset": -1}, headers=TOKEN_HEADERS).status_code == 422
        assert client.get("/api/sources", params={"limit": 0}, headers=TOKEN_HEADERS).status_code == 422


def test_pagination_total_reflects_the_full_row_count_not_the_page_length():
    with TestClient(app) as client:
        for i in range(7):
            _create_work_item(client, i)

        response = client.get("/api/work-items", params={"limit": 2}, headers=TOKEN_HEADERS)

        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) == 2
        assert body["total"] == 7


def test_pagination_an_out_of_range_offset_returns_empty_items_with_correct_total():
    with TestClient(app) as client:
        for i in range(3):
            _create_work_item(client, i)

        response = client.get("/api/work-items", params={"offset": 50}, headers=TOKEN_HEADERS)

        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []
        assert body["total"] == 3


def test_pagination_total_counts_only_the_filtered_rows_not_the_whole_table():
    with TestClient(app) as client:
        _create_work_item(client, 1, status="pending")
        _create_work_item(client, 2, status="pending")
        _create_work_item(client, 3, status="done")

        response = client.get("/api/work-items", params={"status": "done"}, headers=TOKEN_HEADERS)

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert len(body["items"]) == 1
        assert body["items"][0]["status"] == "done"


def test_pagination_sources_endpoint_returns_the_same_envelope():
    with TestClient(app) as client:
        for i in range(5):
            _create_source(client, i)

        response = client.get("/api/sources", params={"limit": 2, "offset": 1}, headers=TOKEN_HEADERS)

        assert response.status_code == 200
        body = response.json()
        assert set(body.keys()) == {"items", "total", "limit", "offset"}
        assert body["total"] == 5
        assert len(body["items"]) == 2
        assert body["limit"] == 2
        assert body["offset"] == 1


def _run_with_database(database_path: Path, *argv: str) -> subprocess.CompletedProcess:
    environment = {**os.environ, "DATABASE_URL": f"sqlite:///{database_path}"}
    return subprocess.run(
        [sys.executable, *argv],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
        timeout=25,
    )


def test_indexes_exist_on_a_real_migrated_database_not_only_in_model_metadata(tmp_path):
    database_path = tmp_path / "indexed.db"

    result = _run_with_database(database_path, "-m", "alembic", "upgrade", "head")
    assert result.returncode == 0, result.stderr

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        inspector = inspect(engine)
        work_item_indexes = {index["name"]: index["column_names"] for index in inspector.get_indexes("work_items")}
        source_indexes = {index["name"]: index["column_names"] for index in inspector.get_indexes("sources")}
    finally:
        engine.dispose()

    assert work_item_indexes["ix_work_items_status"] == ["status"]
    assert work_item_indexes["ix_work_items_source_kind"] == ["source_kind"]
    assert work_item_indexes["ix_work_items_updated_at"] == ["updated_at"]
    assert source_indexes["ix_sources_kind"] == ["kind"]
    assert source_indexes["ix_sources_observed_at"] == ["observed_at"]


def test_indexes_match_between_a_fresh_create_all_database_and_a_migrated_one():
    """``conftest`` builds test schema with ``create_all``; the migration chain must agree."""
    from app.database import engine as test_engine

    inspector = inspect(test_engine)
    work_item_names = {index["name"] for index in inspector.get_indexes("work_items")}
    source_names = {index["name"] for index in inspector.get_indexes("sources")}

    assert {"ix_work_items_status", "ix_work_items_source_kind", "ix_work_items_updated_at"} <= work_item_names
    assert {"ix_sources_kind", "ix_sources_observed_at"} <= source_names
