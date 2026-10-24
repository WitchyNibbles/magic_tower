"""Which registered sources are ready to sync, and the per-kind lock around ``sync()``.

Readiness decides what the scheduler and ``POST /api/sync/all`` sync without being
asked for a kind; the lock keeps a scheduled run and a button press from syncing
the same source at once. Every handler registered here is a stub: no test in this
file may reach Jira or Graph.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.services import jira_sync  # noqa: F401 -- side effect: registers the Jira handler
from app.services.crypto import generate_encryption_key
from app.services.sync import SyncError, sync, token_store
from app.services.sync_registry import ready_kinds, register_sync_handler, unregister_sync_handler

READY_KIND = "fake-ready"
NOT_READY_KIND = "fake-not-ready"
NO_READY_FN_KIND = "fake-no-ready-fn"
LOCKED_KIND = "fake-locked"

GRAPH_SETTINGS = {
    "microsoft_tenant_id": "tenant",
    "microsoft_client_id": "client",
    "microsoft_client_secret": "secret",
    "microsoft_target_user_id": "user",
    "app_encryption_key": "key",
}
JIRA_SETTINGS = {"jira_site_url": "https://example.atlassian.net", "jira_account_email": "me@example.com", "jira_api_token": "token"}
NOTHING_CONFIGURED = {name: None for name in (*GRAPH_SETTINGS, *JIRA_SETTINGS)}


def _stub(settings: Settings, db: Any = None, limit: int = 50, **_: Any) -> dict[str, Any]:
    return {"count": 0}


@pytest.fixture
def stub_kinds():
    register_sync_handler(READY_KIND, _stub, ready=lambda settings: True)
    register_sync_handler(NOT_READY_KIND, _stub, ready=lambda settings: False)
    register_sync_handler(NO_READY_FN_KIND, _stub)
    try:
        yield
    finally:
        for kind in (READY_KIND, NOT_READY_KIND, NO_READY_FN_KIND):
            unregister_sync_handler(kind)


def test_ready_kinds_lists_only_kinds_whose_ready_check_passes(stub_kinds) -> None:
    kinds = ready_kinds(Settings(**NOTHING_CONFIGURED))

    assert READY_KIND in kinds
    assert NOT_READY_KIND not in kinds


def test_a_handler_registered_without_a_ready_check_is_never_listed(stub_kinds) -> None:
    assert NO_READY_FN_KIND not in ready_kinds(Settings(**NOTHING_CONFIGURED))


def test_ready_check_receives_the_settings_it_was_asked_about() -> None:
    seen: list[Settings] = []
    register_sync_handler(READY_KIND, _stub, ready=lambda settings: seen.append(settings) or True)
    try:
        settings = Settings(**NOTHING_CONFIGURED)
        ready_kinds(settings)
    finally:
        unregister_sync_handler(READY_KIND)

    assert seen == [settings]


def test_unregistering_a_kind_drops_its_ready_check() -> None:
    register_sync_handler(READY_KIND, _stub, ready=lambda settings: True)
    unregister_sync_handler(READY_KIND)

    assert READY_KIND not in ready_kinds(Settings(**NOTHING_CONFIGURED))


def test_graph_and_jira_are_not_ready_without_their_settings() -> None:
    kinds = ready_kinds(Settings(**NOTHING_CONFIGURED))

    assert "graph" not in kinds
    assert "jira" not in kinds


def _graph_settings(tmp_path: Path) -> Settings:
    """Graph fully configured, with a real encryption key and a token store under ``tmp_path``."""
    values = {**NOTHING_CONFIGURED, **GRAPH_SETTINGS, "app_encryption_key": generate_encryption_key()}
    return Settings(**values, token_store_path=tmp_path / "graph-tokens.json")


def test_graph_configured_but_not_connected_is_not_ready(tmp_path: Path) -> None:
    kinds = ready_kinds(_graph_settings(tmp_path))

    assert "graph" not in kinds
    assert "jira" not in kinds


def test_graph_is_ready_once_it_is_configured_and_connected(tmp_path: Path) -> None:
    settings = _graph_settings(tmp_path)
    token_store(settings).save({"access_token": "stored-access-token"})

    assert "graph" in ready_kinds(settings)


def test_graph_with_an_unreadable_token_store_is_not_ready_rather_than_an_error(tmp_path: Path) -> None:
    settings = _graph_settings(tmp_path)
    settings.token_store_path.write_text("this is not an encrypted token store")

    assert "graph" not in ready_kinds(settings)


def test_graph_connected_but_no_longer_configured_is_not_ready(tmp_path: Path) -> None:
    settings = _graph_settings(tmp_path)
    token_store(settings).save({"access_token": "stored-access-token"})

    assert "graph" not in ready_kinds(settings.model_copy(update={"microsoft_tenant_id": None}))


def test_jira_is_ready_once_its_three_settings_are_set() -> None:
    kinds = ready_kinds(Settings(**{**NOTHING_CONFIGURED, **JIRA_SETTINGS}))

    assert "jira" in kinds
    assert "graph" not in kinds


def test_sync_holds_one_lock_per_kind_so_two_syncs_of_a_kind_run_in_turn() -> None:
    """The second sync must not enter the handler until the first has left it."""
    first_inside, release_first = threading.Event(), threading.Event()
    lock = threading.Lock()
    inside, most_inside, entries = 0, 0, 0

    def handler(settings: Settings, db: Any = None, limit: int = 50, **_: Any) -> dict[str, Any]:
        nonlocal inside, most_inside, entries
        with lock:
            inside += 1
            entries += 1
            most_inside = max(most_inside, inside)
            this_is_first = entries == 1
        if this_is_first:
            first_inside.set()
            release_first.wait(timeout=5)
        with lock:
            inside -= 1
        return {"count": 0}

    register_sync_handler(LOCKED_KIND, handler)
    try:
        settings = Settings(**NOTHING_CONFIGURED)
        threads = [threading.Thread(target=sync, args=(settings,), kwargs={"kind": LOCKED_KIND}) for _ in range(2)]
        threads[0].start()
        assert first_inside.wait(timeout=5)
        threads[1].start()
        threads[1].join(timeout=0.3)
        assert threads[1].is_alive(), "second sync should be waiting on the kind's lock"
        release_first.set()
        for thread in threads:
            thread.join(timeout=5)
    finally:
        release_first.set()
        unregister_sync_handler(LOCKED_KIND)

    assert entries == 2
    assert most_inside == 1


def test_the_lock_is_released_when_a_handler_raises() -> None:
    calls = 0

    def handler(settings: Settings, db: Any = None, limit: int = 50, **_: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise SyncError("boom")
        return {"count": 0}

    register_sync_handler(LOCKED_KIND, handler)
    try:
        settings = Settings(**NOTHING_CONFIGURED)
        with pytest.raises(SyncError):
            sync(settings, kind=LOCKED_KIND)
        runner = threading.Thread(target=sync, args=(settings,), kwargs={"kind": LOCKED_KIND})
        runner.start()
        runner.join(timeout=2)
        assert not runner.is_alive(), "a failed handler must not leave the kind's lock held"
    finally:
        unregister_sync_handler(LOCKED_KIND)


def test_different_kinds_do_not_wait_for_each_other() -> None:
    release = threading.Event()
    other_ran = threading.Event()

    def slow(settings: Settings, db: Any = None, limit: int = 50, **_: Any) -> dict[str, Any]:
        release.wait(timeout=5)
        return {"count": 0}

    def quick(settings: Settings, db: Any = None, limit: int = 50, **_: Any) -> dict[str, Any]:
        other_ran.set()
        return {"count": 0}

    register_sync_handler(LOCKED_KIND, slow)
    register_sync_handler(READY_KIND, quick)
    try:
        settings = Settings(**NOTHING_CONFIGURED)
        holder = threading.Thread(target=sync, args=(settings,), kwargs={"kind": LOCKED_KIND})
        holder.start()
        sync(settings, kind=READY_KIND)
        assert other_ran.is_set()
        release.set()
        holder.join(timeout=5)
    finally:
        release.set()
        unregister_sync_handler(LOCKED_KIND)
        unregister_sync_handler(READY_KIND)
