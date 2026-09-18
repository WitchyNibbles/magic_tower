"""The commands the README hands somebody who has never seen this repository.

Measuring the heuristic is the one workflow that runs on a *second* machine -- the
one with Outlook access -- so its commands get read literally and pasted. The export
command once omitted ``DATABASE_URL`` and therefore opened the Docker path
``/data/workboard.db``, which a checkout cannot open; the eval command once omitted
``--owner-address``, which left rule 4 (mail the owner was only copied on) unscored
against a sync that always applies it. These tests read the README itself, so neither
omission can come back.
"""

from __future__ import annotations

from pathlib import Path

README = Path(__file__).resolve().parents[2] / "README.md"


def _documented_commands(module: str) -> list[str]:
    """Every command inside a README code fence that runs ``python -m <module>``.

    Backslash continuations are folded, so a command spread over two lines is read
    as the single command a reader would paste.
    """
    commands: list[str] = []
    fenced = False
    pending = ""
    for line in README.read_text().splitlines():
        if line.startswith("```"):
            fenced = not fenced
            continue
        if not fenced:
            continue
        pending += line.rstrip()
        if pending.endswith("\\"):
            pending = pending[:-1]
            continue
        if module in pending:
            commands.append(" ".join(pending.split()))
        pending = ""
    return commands


def test_every_documented_export_command_names_the_database_it_opens() -> None:
    commands = _documented_commands("app.tools.heuristic_export")

    assert commands, "the README no longer documents how to export a labeled sample"
    for command in commands:
        assert "DATABASE_URL=" in command or command.startswith("docker compose exec"), command


def test_every_documented_eval_command_passes_the_owners_addresses() -> None:
    commands = _documented_commands("app.tools.heuristic_eval")

    assert commands, "the README no longer documents how to score the heuristic"
    for command in commands:
        assert "--owner-address" in command, command
