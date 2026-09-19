"""``scripts/leave-no-trace.sh``, the gate the contract's AC4 line runs.

Cleanup used to be enforced by memory alone, and it was forgotten for an
entire run: 15 stale worktrees, 21 orphan branches, 224 project files left in
``/tmp``, a vite dev server alive for hours. This script turns each of those
into a counted, checkable category -- one labeled line per category, the
total alone on the last line, the same shape as ``scripts/deadcode.sh``.

Each test below falsifies exactly one category by hand: create a real
artefact of that kind (a real ``git worktree add``, a real branch, a real
``/tmp`` file, a real child process whose command line points inside the
repository), assert the labeled count rises by exactly one, remove the
artefact, assert it falls back. Measuring a *delta* rather than an absolute
count is deliberate -- this repository is shared by concurrent agent runs,
so the baseline for any category can be nonzero for reasons this test did
not cause. For the same reason every artefact's name carries this process's
PID: two concurrent runs of this suite must not collide on a branch or file
name. Every artefact is created and destroyed inside a ``try/finally`` so a
failing assertion cannot leak a worktree, branch or process into the next
thing that runs this same gate.

The ``/tmp`` category's *naming rules* -- which names are task-scoped and
which of those a sealed contract mandates -- cannot be falsified against the
real ``/tmp``: proving ``ac13.json`` is exempt needs a file by that exact
name, and this machine's ``/tmp`` already holds one that AC13's own verify
command wrote and that no test may clobber or delete. Those two tests
therefore point the category at a private directory via
``LEAVE_NO_TRACE_TMP_DIR``; the rise-and-fall test above them still passes no
override, so the default ``/tmp`` path stays exercised on every run.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "leave-no-trace.sh"


def _run_script(tmp_dir: Path | None = None) -> tuple[int, dict[str, int], int]:
    """Run the gate once; return (exit code, {label: count}, total).

    ``tmp_dir`` points the stray-temp-file category at a private directory
    instead of the real ``/tmp``; left unset, the script scans ``/tmp``.
    """
    env = dict(os.environ)
    if tmp_dir is not None:
        env["LEAVE_NO_TRACE_TMP_DIR"] = str(tmp_dir)
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    lines = [line for line in result.stdout.splitlines() if line]
    assert lines, f"scripts/leave-no-trace.sh produced no output; stderr: {result.stderr}"
    assert re.fullmatch(r"[0-9]+", lines[-1]), f"last line {lines[-1]!r} is not a bare integer"
    per_label: dict[str, int] = {}
    for line in lines[:-1]:
        m = re.match(r"^(.+):\s*([0-9]+)\s*$", line)
        assert m, f"unlabeled line in output: {line!r}"
        per_label[m.group(1)] = int(m.group(2))
    assert per_label, f"no per-category lines found in: {lines}"
    assert int(lines[-1]) == sum(per_label.values()), (
        f"script reported {lines[-1]}, its own category lines sum to {sum(per_label.values())}"
    )
    return result.returncode, per_label, int(lines[-1])


def test_leave_no_trace_script_exists_and_is_runnable() -> None:
    assert SCRIPT.is_file(), "scripts/leave-no-trace.sh does not exist"


def test_leave_no_trace_script_exits_zero_only_when_the_total_is_zero() -> None:
    """The gate's contract is to fail the run when anything was left behind."""
    returncode, _per_label, total = _run_script()
    if total == 0:
        assert returncode == 0, "total is 0 but the script exited nonzero"
    else:
        assert returncode != 0, f"total is {total} but the script exited 0"


def test_stray_worktree_is_counted_then_disappears_once_removed(tmp_path) -> None:
    """A real `git worktree add` beyond the one running the check rises, then falls."""
    _rc, before, _total = _run_script()
    baseline = before["stray worktrees"]

    worktree_path = tmp_path / "probe-worktree"
    branch = f"probe-leave-no-trace-stray-worktree-{os.getpid()}"
    try:
        add = subprocess.run(
            ["git", "worktree", "add", "-q", str(worktree_path), "-b", branch, "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert add.returncode == 0, add.stderr

        _rc, during, _total = _run_script()
        assert during["stray worktrees"] == baseline + 1
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree_path)],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
        )
        subprocess.run(
            ["git", "branch", "-D", branch], cwd=REPO_ROOT, check=False, capture_output=True
        )

    _rc, after, _total = _run_script()
    assert after["stray worktrees"] == baseline


def test_orphan_worktree_agent_branch_is_counted_then_disappears() -> None:
    """A `worktree-agent-*` branch with no worktree checking it out is an orphan."""
    _rc, before, _total = _run_script()
    baseline = before["orphan worktree-agent branches"]

    branch = f"worktree-agent-probe-leave-no-trace-orphan-{os.getpid()}"
    try:
        create = subprocess.run(
            ["git", "branch", branch, "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True
        )
        assert create.returncode == 0, create.stderr

        _rc, during, _total = _run_script()
        assert during["orphan worktree-agent branches"] == baseline + 1
    finally:
        subprocess.run(
            ["git", "branch", "-D", branch], cwd=REPO_ROOT, check=False, capture_output=True
        )

    _rc, after, _total = _run_script()
    assert after["orphan worktree-agent branches"] == baseline


def test_stray_tmp_task_file_is_counted_then_disappears() -> None:
    """A `/tmp` file named after this project's task/AC convention (`t<N>...`, `ac<N>...`)."""
    _rc, before, _total = _run_script()
    baseline = before["stray /tmp task files"]

    probe = Path("/tmp") / f"t99999_leave_no_trace_probe_{os.getpid()}.tmp"
    try:
        probe.write_text("probe")

        _rc, during, _total = _run_script()
        assert during["stray /tmp task files"] == baseline + 1
    finally:
        probe.unlink(missing_ok=True)

    _rc, after, _total = _run_script()
    assert after["stray /tmp task files"] == baseline


def test_task_id_must_end_at_a_terminator_so_nanoids_are_not_task_files(tmp_path) -> None:
    """`t2zBWPxqUQ5ntZbhoh4Ai` is a nanoid, not task 2's scratch file.

    Random 21-character names are how several unrelated tools name their
    ``/tmp`` entries, and roughly one in two hundred of them opens with a
    letter this project uses for task IDs followed by a digit. Matching on
    the bare prefix made the gate red for artefacts this project never
    created and cannot clean up, so the ID has to *end* -- at a ``.``, ``-``,
    ``_`` or the end of the name.
    """
    scan = tmp_path / "scan"
    scan.mkdir()
    for name in ("t2zBWPxqUQ5ntZbhoh4Ai", "ac4XYZbhoh4AiUQ5ntZbh", "toolcache", "acme.log"):
        (scan / name).mkdir()

    _rc, per_label, total = _run_script(scan)
    assert per_label["stray /tmp task files"] == 0, f"nanoid-shaped names counted: {total}"

    for name in ("t03-clone-test", "ac4-alembic.db", "ac14.json", "t7", "t12_report.json"):
        (scan / name).write_text("probe")

    _rc, per_label, _total = _run_script(scan)
    assert per_label["stray /tmp task files"] == 5


def test_tmp_reports_the_sealed_contract_mandates_are_exempt_but_siblings_are_not(
    tmp_path,
) -> None:
    """Only the two basenames a sealed verify command is specified to write.

    AC13's verify line writes ``/tmp/ac13.json`` on every run and never
    deletes it, and task T11's gate writes ``/tmp/t11.json`` the same way, so
    counting those would make this gate red by construction the moment either
    is verified. The exemption is those two names and nothing else: a stale
    report like ``t2.json``, which no criterion mandates, is exactly the trace
    this gate exists to catch.
    """
    scan = tmp_path / "scan"
    scan.mkdir()
    for name in ("ac13.json", "t11.json"):
        (scan / name).write_text("{}")

    _rc, per_label, _total = _run_script(scan)
    assert per_label["stray /tmp task files"] == 0, "a contract-mandated report was counted"

    (scan / "t2.json").write_text("{}")

    _rc, per_label, _total = _run_script(scan)
    assert per_label["stray /tmp task files"] == 1, "an unmandated stale report escaped the gate"


def test_repo_pointing_process_is_counted_then_disappears_once_killed() -> None:
    """A real child process whose command line names a path inside the repository."""
    _rc, before, _total = _run_script()
    baseline = before["repo-pointing processes"]

    target = REPO_ROOT / "backend" / "pyproject.toml"
    proc = subprocess.Popen(
        ["tail", "-f", str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        time.sleep(0.3)  # give it time to actually start before /proc is scanned
        _rc, during, _total = _run_script()
        assert during["repo-pointing processes"] == baseline + 1
    finally:
        proc.terminate()
        proc.wait(timeout=5)

    time.sleep(0.2)  # give the kernel time to reap it out of /proc
    _rc, after, _total = _run_script()
    assert after["repo-pointing processes"] == baseline
