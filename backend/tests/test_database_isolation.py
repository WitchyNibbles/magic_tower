"""Guards the per-process isolation of the test database configured in conftest."""

import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = TESTS_DIR.parent
# ``conftest`` picks the database path at import time, so importing it in a bare
# interpreter reports exactly what a second, concurrent pytest process would use.
REPORT_DATABASE_URL = "import os, sys; sys.path.insert(0, sys.argv[1]); import conftest; print(os.environ['DATABASE_URL'])"


def _database_url_of_a_separate_process() -> str:
    command = [sys.executable, "-c", REPORT_DATABASE_URL, str(TESTS_DIR)]
    result = subprocess.run(command, cwd=BACKEND_DIR, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_two_test_processes_never_share_one_database_file():
    first = _database_url_of_a_separate_process()
    second = _database_url_of_a_separate_process()
    assert first.startswith("sqlite:///")
    assert first != second, f"two parallel suites would drop each other's tables in {first}"
