"""The background sync scheduler: ticks, survival, shutdown, and what one tick does.

Timing tests use intervals of a few milliseconds and wait on events, never on
fixed sleeps. The tick body (``run_scheduled_sync``) runs against stub handlers in
an emptied registry: no test here reaches Jira or Graph.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import pytest

from app.config import Settings
from app.services import scheduler as scheduler_module
from app.services import sync_registry
from app.services.scheduler import SyncScheduler, run_scheduled_sync
from app.services.sync import SyncError
from app.services.sync_registry import register_sync_handler

WAIT_SECONDS = 5


def test_it_ticks_repeatedly_after_the_initial_delay() -> None:
    ticks = 0
    enough = threading.Event()

    def run() -> None:
        nonlocal ticks
        ticks += 1
        if ticks >= 3:
            enough.set()

    scheduler = SyncScheduler(interval_seconds=0.01, run=run, initial_delay_seconds=0)
    scheduler.start()
    try:
        assert enough.wait(WAIT_SECONDS)
    finally:
        scheduler.stop()

    assert ticks >= 3


def test_nothing_runs_before_the_initial_delay_has_passed() -> None:
    ticks = 0

    def run() -> None:
        nonlocal ticks
        ticks += 1

    scheduler = SyncScheduler(interval_seconds=0.01, run=run, initial_delay_seconds=60)
    scheduler.start()
    stopped = threading.Event()
    threading.Timer(0.1, stopped.set).start()
    stopped.wait(WAIT_SECONDS)
    scheduler.stop()

    assert ticks == 0


def test_a_tick_that_raises_is_logged_and_the_next_tick_still_runs(caplog: pytest.LogCaptureFixture) -> None:
    calls = 0
    recovered = threading.Event()

    def run() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("tick blew up")
        recovered.set()

    scheduler = SyncScheduler(interval_seconds=0.01, run=run, initial_delay_seconds=0)
    with caplog.at_level(logging.ERROR):
        scheduler.start()
        try:
            assert recovered.wait(WAIT_SECONDS)
        finally:
            scheduler.stop()

    assert any(record.exc_info for record in caplog.records)


def test_stop_ends_the_thread_and_no_more_ticks_run() -> None:
    ticks = 0
    started = threading.Event()

    def run() -> None:
        nonlocal ticks
        ticks += 1
        started.set()

    scheduler = SyncScheduler(interval_seconds=0.01, run=run, initial_delay_seconds=0)
    scheduler.start()
    assert started.wait(WAIT_SECONDS)
    scheduler.stop()
    ticks_at_stop = ticks

    assert not scheduler.is_running()
    threading.Event().wait(0.05)
    assert ticks == ticks_at_stop


def test_stop_interrupts_a_long_initial_delay_instead_of_waiting_it_out() -> None:
    scheduler = SyncScheduler(interval_seconds=3600, run=lambda: None, initial_delay_seconds=3600)
    scheduler.start()
    scheduler.stop(timeout=WAIT_SECONDS)

    assert not scheduler.is_running()


def test_the_thread_is_a_daemon_so_it_never_holds_the_process_open() -> None:
    scheduler = SyncScheduler(interval_seconds=3600, run=lambda: None, initial_delay_seconds=3600)
    scheduler.start()
    try:
        threads = [thread for thread in threading.enumerate() if thread.name == scheduler_module.THREAD_NAME]
        assert len(threads) == 1 and threads[0].daemon
    finally:
        scheduler.stop()


def test_stop_before_start_is_harmless() -> None:
    SyncScheduler(interval_seconds=1, run=lambda: None).stop()


def test_starting_twice_does_not_start_a_second_thread() -> None:
    before = threading.active_count()
    scheduler = SyncScheduler(interval_seconds=3600, run=lambda: None, initial_delay_seconds=3600)
    scheduler.start()
    scheduler.start()
    try:
        assert threading.active_count() == before + 1
    finally:
        scheduler.stop()


class _TrackedSession:
    """Stands in for ``SessionLocal()``: records that it was opened and closed."""

    opened = 0
    closed = 0

    def __init__(self) -> None:
        type(self).opened += 1

    def close(self) -> None:
        type(self).closed += 1


@pytest.fixture
def tick_environment(monkeypatch: pytest.MonkeyPatch):
    """An empty registry, a counting session factory, and ``Settings`` with nothing set."""
    monkeypatch.setattr(sync_registry, "_handlers", {})
    monkeypatch.setattr(sync_registry, "_ready_checks", {})
    monkeypatch.setattr(sync_registry, "_locks", {})
    _TrackedSession.opened = _TrackedSession.closed = 0
    monkeypatch.setattr(scheduler_module, "SessionLocal", _TrackedSession)
    monkeypatch.setattr(scheduler_module, "get_settings", lambda: Settings())


def _register(kind: str, handler: Any) -> None:
    register_sync_handler(kind, handler, ready=lambda settings: True)


def test_a_tick_syncs_every_ready_source_in_its_own_session_and_closes_it(tick_environment) -> None:
    seen: list[Any] = []

    def handler(settings: Settings, db: Any = None, limit: int = 50, **_: Any) -> dict[str, Any]:
        seen.append(db)
        return {"count": 0}

    _register("alpha", handler)
    run_scheduled_sync()

    assert len(seen) == 1 and isinstance(seen[0], _TrackedSession)
    assert (_TrackedSession.opened, _TrackedSession.closed) == (1, 1)


def test_the_session_is_closed_even_when_the_tick_raises(tick_environment, monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(settings: Settings, db: Any) -> dict[str, Any]:
        raise RuntimeError("tick failed")

    monkeypatch.setattr(scheduler_module, "sync_ready_sources", explode)

    with pytest.raises(RuntimeError):
        run_scheduled_sync()

    assert (_TrackedSession.opened, _TrackedSession.closed) == (1, 1)


def test_a_tick_logs_one_line_per_source_with_counts_or_the_error(tick_environment, caplog: pytest.LogCaptureFixture) -> None:
    def broken(settings: Settings, db: Any = None, limit: int = 50, **_: Any) -> dict[str, Any]:
        raise SyncError("Microsoft Graph is not connected")

    _register("alpha", lambda settings, db=None, limit=50, **_: {"count": 4, "new_work_items": 2})
    _register("broken", broken)

    with caplog.at_level(logging.INFO, logger=scheduler_module.logger.name):
        run_scheduled_sync()

    messages = [record.getMessage() for record in caplog.records if record.name == scheduler_module.logger.name]
    assert len(messages) == 2
    assert "alpha" in messages[0] and "4" in messages[0] and "2" in messages[0]
    assert "broken" in messages[1] and "Microsoft Graph is not connected" in messages[1]


def test_a_tick_logs_a_failed_source_as_a_warning_and_a_synced_one_as_info(tick_environment, caplog: pytest.LogCaptureFixture) -> None:
    """Under uvicorn only WARNING and above survive by default, so a failure has to be at least that."""

    def broken(settings: Settings, db: Any = None, limit: int = 50, **_: Any) -> dict[str, Any]:
        raise SyncError("Jira request failed with status 500")

    _register("alpha", lambda settings, db=None, limit=50, **_: {"count": 4, "new_work_items": 2})
    _register("broken", broken)

    with caplog.at_level(logging.INFO, logger=scheduler_module.logger.name):
        run_scheduled_sync()

    levels = {record.getMessage().split()[2].rstrip(":"): record.levelno
              for record in caplog.records if record.name == scheduler_module.logger.name}
    assert levels == {"alpha": logging.INFO, "broken": logging.WARNING}
