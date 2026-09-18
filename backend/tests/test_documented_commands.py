"""The commands ``docs/second-pc.md`` hands somebody who has never seen this repository.

Measuring the heuristic is the one workflow that runs on a *second* machine -- the
one with Outlook access -- so its commands get read literally and pasted. The export
command once omitted ``DATABASE_URL`` and therefore opened the Docker path
``/data/workboard.db``, which a checkout cannot open; the eval command once omitted
``--owner-address``, which left rule 4 (mail the owner was only copied on) unscored
against a sync that always applies it; the compose block once copied into
``~/.magic-tower`` before anything had created it, which fails with "invalid output
path" on a machine that has never run the export -- the fresh-clone state by
definition. These tests read ``docs/second-pc.md`` itself, so none of the three can
come back. (The sequence used to live in the README; T18 moved the ordered,
pasteable walkthrough to ``docs/second-pc.md`` so there is one copy, not two that
can drift apart, and these tests moved with it.)

Two more invariants joined them for the same reason. The eval command has to keep
``MAGIC_TOWER_REQUIRE_SAMPLE=1``, the one thing that stops a second PC from "passing"
by printing "nothing to evaluate" and exiting 0; and every runner the document pastes
has to be named in its own Prerequisites section, which once listed Docker alone while
the steps below it pasted ``git``, ``python3`` and ``uv`` -- all three "command not
found" on a machine that installed exactly what it was told to.

The two directory tests run the documented lines instead of matching their text.
What the document promises about ``~/.magic-tower`` is an outcome -- it is there,
and it is owner-only -- and any spelling that delivers that outcome is correct.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path, PurePosixPath

SECOND_PC_DOC = Path(__file__).resolve().parents[2] / "docs" / "second-pc.md"

# Where the document tells the second PC to keep the labeled sample: outside the
# repository, gitignored, and holding the owner's real mail in cleartext.
SAMPLE_PATH = "~/.magic-tower/labeled-sample.json"


def _fenced_blocks() -> list[list[str]]:
    """Every fenced code block in the document, one list of folded commands per fence.

    Backslash continuations are folded, so a command spread over two lines is read
    as the single command a reader would paste.
    """
    blocks: list[list[str]] = []
    current: list[str] = []
    fenced = False
    pending = ""
    for line in SECOND_PC_DOC.read_text().splitlines():
        if line.startswith("```"):
            if fenced:
                blocks.append(current)
                current = []
            fenced = not fenced
            continue
        if not fenced:
            continue
        pending += line.rstrip()
        if pending.endswith("\\"):
            pending = pending[:-1]
            continue
        if pending:
            current.append(" ".join(pending.split()))
        pending = ""
    return blocks


def _documented_commands(module: str) -> list[str]:
    """Every command inside a docs/second-pc.md code fence that runs ``python -m <module>``."""
    return [command for block in _fenced_blocks() for command in block if module in command]


def _writes_the_sample(command: str) -> bool:
    """Whether ``command`` puts the labeled sample on this host.

    Either the export is told to write it there, or a ``docker compose cp`` carries
    it out of the container to there. The eval block names the same path but only
    reads it, and has no directory to prepare.
    """
    return f"--output {SAMPLE_PATH}" in command or (
        command.startswith("docker compose cp") and command.endswith(SAMPLE_PATH)
    )


def _lines_this_test_can_run(commands: list[str]) -> list[str]:
    """The documented lines that only touch this host's filesystem.

    Docker commands need a running daemon and ``uv run`` needs a database a sync
    has filled, neither of which this test has; ``cd`` would carry the rest of the
    block somewhere it does not control. What is left is exactly the directory
    preparation these tests are about.
    """
    return [
        command for command in commands
        if not command.startswith(("docker ", "cd ")) and "uv run" not in command
    ]


def _paste_into(home: Path, commands: list[str]) -> None:
    """Run ``commands`` the way a reader pastes them, with ``~`` meaning ``home``."""
    result = subprocess.run(
        ["bash", "-c", "\n".join(["set -e", *commands])],
        env={"HOME": str(home), "PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert result.returncode == 0, result.stderr


def _expand(path: str, home: Path) -> Path:
    return Path(path.replace("~", str(home), 1))


# The tools docs/second-pc.md's own commands invoke that a fresh second PC may not
# have. Deliberately a fixed, small set and not a shell parser: a command whose first
# word is none of these needs no prerequisite worth naming, because ``cd``, ``cp``,
# ``mkdir`` and ``chmod`` are on every machine that can run the rest of this document.
RUNNERS = ("docker", "git", "python3", "uv")


def _runner_of(command: str) -> str | None:
    """The tool ``command`` needs installed, or ``None`` if it needs nothing special.

    Leading ``VAR=value`` assignments are skipped, so
    ``MAGIC_TOWER_REQUIRE_SAMPLE=1 uv run ...`` is a ``uv`` command -- and a line that
    is nothing but assignments, as every line of the ``.env`` fence is, invokes nothing.
    """
    for word in command.split():
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", word):
            continue
        return word if word in RUNNERS else None
    return None


def _prerequisites() -> str:
    """The body of the document's Prerequisites section."""
    section = re.search(
        r"\n## Prerequisites\n(.*?)(?=\n## )", SECOND_PC_DOC.read_text(), re.DOTALL
    )
    assert section, "docs/second-pc.md no longer has a Prerequisites section"
    return section.group(1)


def test_the_documented_compose_copy_has_a_directory_to_copy_into(tmp_path) -> None:
    """``docker compose cp`` exits 1 with "invalid output path" when the host
    directory it writes into does not exist yet -- exactly the state of
    ``~/.magic-tower`` on a machine that has never run the export. Pasting the
    block's host-side lines onto such a machine has to leave that directory there.
    """
    copies = 0
    for block in _fenced_blocks():
        for index, command in enumerate(block):
            if not (command.startswith("docker compose cp") and command.endswith(SAMPLE_PATH)):
                continue
            home = tmp_path / f"fresh-home-{copies}"
            home.mkdir()
            copies += 1

            _paste_into(home, _lines_this_test_can_run(block[:index]))

            destination = _expand(str(PurePosixPath(SAMPLE_PATH).parent), home)
            assert destination.is_dir(), f"{command!r} would fail: {destination} does not exist"

    assert copies, "docs/second-pc.md no longer documents the docker compose cp step"


def test_every_documented_way_of_writing_the_sample_leaves_its_directory_owner_only(tmp_path) -> None:
    """``mkdir`` applies its mode only when it actually creates the directory, so a
    ``~/.magic-tower`` another tool already made ``0755`` keeps that mode and every
    filename in it stays world-readable. A block that writes real mail there has to
    set the mode itself, whatever the directory's mode already was.
    """
    blocks = [block for block in _fenced_blocks() if any(_writes_the_sample(line) for line in block)]

    assert blocks, "docs/second-pc.md no longer documents how to write a labeled sample"
    for number, block in enumerate(blocks):
        home = tmp_path / f"used-home-{number}"
        directory = _expand(str(PurePosixPath(SAMPLE_PATH).parent), home)
        directory.mkdir(parents=True)
        os.chmod(directory, 0o755)

        _paste_into(home, _lines_this_test_can_run(block))

        mode = stat.S_IMODE(directory.stat().st_mode)
        assert mode == 0o700, f"{block} leaves {directory} at {mode:04o}, not 0700"


def test_every_documented_export_command_names_the_database_it_opens() -> None:
    commands = _documented_commands("app.tools.heuristic_export")

    assert commands, "docs/second-pc.md no longer documents how to export a labeled sample"
    for command in commands:
        assert "DATABASE_URL=" in command or command.startswith("docker compose exec"), command


def test_every_documented_eval_command_passes_the_owners_addresses() -> None:
    commands = _documented_commands("app.tools.heuristic_eval")

    assert commands, "docs/second-pc.md no longer documents how to score the heuristic"
    for command in commands:
        assert "--owner-address" in command, command


def test_every_documented_eval_command_requires_the_sample() -> None:
    """``heuristic_eval`` exits 0 when the sample is missing or was never labeled, which
    is what keeps CI and a machine that has never synced real mail green. On the second
    PC that default is the whole failure this document exists to close: a reader who
    pastes the eval line without ``MAGIC_TOWER_REQUIRE_SAMPLE=1`` gets "nothing to
    evaluate" and a zero exit, and cannot tell that apart from a heuristic that scored.
    """
    commands = _documented_commands("app.tools.heuristic_eval")

    assert commands, "docs/second-pc.md no longer documents how to score the heuristic"
    for command in commands:
        assert "MAGIC_TOWER_REQUIRE_SAMPLE=1" in command, command


def test_every_documented_command_names_its_runner_as_a_prerequisite() -> None:
    """A second PC that installed exactly what Prerequisites names has to be able to run
    every line the document then tells it to paste. The section once named Docker alone,
    while step 1 pastes ``git``, step 2 pastes ``python3`` and step 7 pastes ``uv`` --
    "command not found" on a Docker-only machine, and all of them reached *before* the
    one line the document warns needs a real Microsoft credential, so the reader stalls
    where they were promised nothing could go wrong.
    """
    prerequisites = _prerequisites()

    runners = {
        runner
        for block in _fenced_blocks()
        for command in block
        if (runner := _runner_of(command))
    }

    assert runners, "docs/second-pc.md no longer documents any command to run"
    for runner in sorted(runners):
        assert re.search(rf"\b{re.escape(runner)}\b", prerequisites, re.IGNORECASE), (
            f"docs/second-pc.md pastes a {runner} command "
            f"but its Prerequisites section never names {runner}"
        )
