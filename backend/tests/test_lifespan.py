"""The app lifespan starts the sync scheduler only when ``SYNC_INTERVAL_MINUTES`` is above 0.

``SyncScheduler`` is replaced by a recorder here, so no thread ever starts.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import get_settings
from app.services.scheduler import run_scheduled_sync


class _RecordingScheduler:
    instances: list["_RecordingScheduler"] = []

    def __init__(self, interval_seconds: float, run: Any, **_: Any) -> None:
        self.interval_seconds = interval_seconds
        self.run = run
        self.events: list[str] = []
        type(self).instances.append(self)

    def start(self) -> None:
        self.events.append("start")

    def stop(self, *_: Any, **__: Any) -> None:
        self.events.append("stop")


@pytest.fixture(autouse=True)
def recording_scheduler(monkeypatch: pytest.MonkeyPatch):
    _RecordingScheduler.instances = []
    monkeypatch.setattr(main, "SyncScheduler", _RecordingScheduler)


def _set_interval(monkeypatch: pytest.MonkeyPatch, minutes: int) -> None:
    monkeypatch.setenv("SYNC_INTERVAL_MINUTES", str(minutes))
    get_settings.cache_clear()


def test_a_positive_interval_starts_the_scheduler_and_stops_it_on_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_interval(monkeypatch, 7)

    with TestClient(main.app):
        (scheduler,) = _RecordingScheduler.instances
        assert scheduler.events == ["start"]
    assert scheduler.events == ["start", "stop"]
    assert scheduler.interval_seconds == 7 * 60
    assert scheduler.run is run_scheduled_sync


def test_zero_means_no_scheduler_at_all(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_interval(monkeypatch, 0)

    with TestClient(main.app) as client:
        assert client.get("/api/health").status_code == 200

    assert _RecordingScheduler.instances == []


def test_the_scheduler_is_stopped_even_if_the_app_fails_while_running(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_interval(monkeypatch, 5)

    with pytest.raises(RuntimeError):
        with TestClient(main.app):
            raise RuntimeError("shutdown mid-flight")

    assert _RecordingScheduler.instances[0].events == ["start", "stop"]
