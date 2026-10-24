"""Background scheduler: sync every ready source on a fixed interval.

A plain daemon thread waiting on an ``Event`` is enough for one periodic job in
one process, and needs no dependency. The ``Event`` is what makes shutdown prompt:
``stop()`` wakes a thread sleeping out its delay instead of waiting for it, and
the thread being a daemon means a stuck sync can never keep the process alive.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from ..config import get_settings
from ..database import SessionLocal
from .sync_all import sync_ready_sources

logger = logging.getLogger(__name__)

THREAD_NAME = "sync-scheduler"
# Let the app finish starting (and a first request or two be served) before the
# first sync takes the per-kind locks.
DEFAULT_INITIAL_DELAY_SECONDS = 30
DEFAULT_STOP_TIMEOUT_SECONDS = 5


class SyncScheduler:
    """Calls ``run`` after ``initial_delay_seconds`` and then every ``interval_seconds``."""

    def __init__(self, interval_seconds: float, run: Callable[[], None], initial_delay_seconds: float = DEFAULT_INITIAL_DELAY_SECONDS) -> None:
        self._interval = interval_seconds
        self._initial_delay = initial_delay_seconds
        self._run = run
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.is_running():
            return
        self._stopping.clear()
        self._thread = threading.Thread(target=self._loop, name=THREAD_NAME, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = DEFAULT_STOP_TIMEOUT_SECONDS) -> None:
        """Wake the thread and wait up to ``timeout`` seconds for it to finish its tick."""
        self._stopping.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _loop(self) -> None:
        delay = self._initial_delay
        while not self._stopping.wait(delay):
            try:
                self._run()
            except Exception:
                # A failed tick must not end the schedule: the next one may well succeed.
                logger.exception("scheduled sync tick failed")
            delay = self._interval


def _log_result(kind: str, result: dict[str, Any]) -> None:
    """One log line per source: a failure at WARNING, a success at INFO.

    Only the error message or the counts are logged, never anything else from the
    envelope. The levels matter because a failure must stay visible wherever INFO
    is filtered out.
    """
    if "error" in result:
        logger.warning("scheduled sync %s failed: %s", kind, result["error"])
    else:
        logger.info("scheduled sync %s: %s fetched, %s new work items", kind, result.get("count", 0), result.get("new_work_items", 0))


def run_scheduled_sync() -> None:
    """One scheduler tick: sync every ready source in a session of its own.

    The scheduler thread has no request to borrow a session from, and a session
    must not be shared across threads, so each tick opens and closes its own.
    """
    db = SessionLocal()
    try:
        for kind, result in sync_ready_sources(get_settings(), db).items():
            _log_result(kind, result)
    finally:
        db.close()
