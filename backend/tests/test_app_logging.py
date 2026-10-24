"""The app's own log lines (``app.*``) must reach the console when it runs under uvicorn.

uvicorn configures only its own loggers, so ``app.*`` INFO lines (the scheduler's
per-source results) fall through to a root logger with no handler and vanish. This
runs a fresh interpreter with uvicorn's real ``LOGGING_CONFIG`` applied, because
pytest's root-logger handlers would hide the problem in-process.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SCRIPT = """
import logging, logging.config
from uvicorn.config import LOGGING_CONFIG
logging.config.dictConfig(LOGGING_CONFIG)
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app):
    logging.getLogger("app.services.scheduler").info("probe-info-line")
    logging.getLogger("app.services.sync_all").warning("probe-warning-line")
"""


def test_app_info_and_warning_lines_are_emitted_under_uvicorns_logging_config() -> None:
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        cwd=Path(__file__).resolve().parent.parent,
        env=os.environ,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert "probe-info-line" in result.stderr
    assert "probe-warning-line" in result.stderr
    assert result.stderr.count("probe-info-line") == 1
