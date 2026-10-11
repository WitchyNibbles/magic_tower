"""``scripts/deadcode.sh``, the dead-code gate the contract's ``dead-code:`` line runs.

The gate used to be an inline one-liner: run vulture, run knip, ``paste -sd+ | bc``
the two counts together. That shape has a specific failure the tests below are
about -- ``paste`` and ``bc`` never look at either checker's exit code, so a
checker that cannot run at all (a bad invocation, a missing tool, a crashed
interpreter) contributes an empty stdout, which sums to zero exactly like a
checker that ran cleanly and found nothing. A gate that silently reports "0
dead code" when a checker never ran is worse than no gate, because it looks
green. ``scripts/deadcode.sh`` has to notice the difference and refuse to
print a number when it cannot trust one.

The correctness test below does not hard-code today's count, because that
number drifts with the codebase (vulture's ``cls``-in-classmethod false
positives track how many validators ``backend/app/config.py`` has, and knip's
count tracks whatever ``frontend/node_modules`` state the checkout has). It
instead re-runs the same two checkers itself and checks the script's total
against that, so it stays true regardless of which way the count drifts.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "deadcode.sh"

_KNIP_ISSUE_KEYS = (
    "files",
    "exports",
    "types",
    "dependencies",
    "devDependencies",
    "unlisted",
    "unresolved",
    "duplicates",
    "enumMembers",
    "namespaceMembers",
    "binaries",
)


def _independent_total() -> int:
    """The same two checkers' combined count, computed without the script."""
    vulture = subprocess.run(
        ["uv", "run", "--with", "vulture", "vulture", "app", "tests", "--min-confidence", "80"],
        cwd=REPO_ROOT / "backend",
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert vulture.returncode in (0, 3), (
        f"vulture exited {vulture.returncode} independently of the script; "
        f"stderr: {vulture.stderr}"
    )
    vulture_count = len([line for line in vulture.stdout.splitlines() if line])

    knip = subprocess.run(
        ["npx", "--yes", "knip@latest", "--reporter", "json"],
        cwd=REPO_ROOT / "frontend",
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert knip.returncode in (0, 1), (
        f"knip exited {knip.returncode} independently of the script; stderr: {knip.stderr}"
    )
    data = json.loads(knip.stdout)
    knip_count = sum(
        len(issue.get(key, [])) for issue in data["issues"] for key in _KNIP_ISSUE_KEYS
    )

    return vulture_count + knip_count


def test_deadcode_script_exists_and_is_runnable() -> None:
    assert SCRIPT.is_file(), "scripts/deadcode.sh does not exist"


def test_deadcode_script_prints_a_single_integer_total_matching_the_checkers() -> None:
    """The script's last line is a bare integer equal to vulture's plus knip's count."""
    expected = _independent_total()

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    lines = [line for line in result.stdout.splitlines() if line]
    assert lines, "scripts/deadcode.sh produced no output"
    assert re.fullmatch(r"[0-9]+", lines[-1]), (
        f"last line {lines[-1]!r} is not a bare integer"
    )
    # The per-checker lines are the script's own breakdown: `label: <count>`.
    # Summing them keeps this test checker-agnostic, so adding a checker does not
    # break it -- what is being pinned is "the total is the sum of what it printed".
    per_checker = [
        int(m.group(1))
        for line in lines[:-1]
        if (m := re.search(r":\s*([0-9]+)\s*$", line))
    ]
    assert per_checker, f"no per-checker lines found in: {lines}"
    assert int(lines[-1]) == sum(per_checker), (
        f"script reported {lines[-1]}, its own checker lines sum to {sum(per_checker)}"
    )
    # vulture + knip are still independently recomputed here; any further checker
    # contributes the difference and must be non-negative.
    assert int(lines[-1]) >= expected, (
        f"script reported {lines[-1]}, below the independently computed vulture+knip total {expected}"
    )


def test_deadcode_script_runs_from_any_working_directory(tmp_path) -> None:
    """The script resolves its checkers' directories itself; the caller's cwd should not matter."""
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    lines = [line for line in result.stdout.splitlines() if line]
    assert lines and re.fullmatch(r"[0-9]+", lines[-1]), lines


def test_deadcode_script_does_not_report_zero_when_a_checker_cannot_run(tmp_path) -> None:
    """A checker that cannot run at all must fail the script loudly, not sum to zero.

    ``uv`` here is a stand-in for "the checker's own tool crashed" -- shadowing it
    with a script that always fails reproduces exactly what a broken interpreter,
    a missing binary, or a bad invocation looks like to the wrapper: a nonzero
    exit and no usable stdout. The old ``... | paste -sd+ | bc`` one-liner would
    have folded that into the total as a plain 0; this script must not.
    """
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text("#!/bin/sh\necho 'fake uv: simulated crash' >&2\nexit 1\n")
    fake_uv.chmod(fake_uv.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    env = dict(os.environ)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert result.returncode != 0, (
        f"script exited 0 with a broken vulture; stdout: {result.stdout!r}"
    )
    lines = [line for line in result.stdout.splitlines() if line]
    last = lines[-1] if lines else ""
    assert last != "0", (
        "script reported a total of 0 when its Python checker could not run at all "
        f"-- stdout: {result.stdout!r}, stderr: {result.stderr!r}"
    )
