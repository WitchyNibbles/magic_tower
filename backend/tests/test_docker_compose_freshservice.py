"""``docker-compose.yml``'s Freshservice passthrough into the ``api`` container.

The compose file's ``env_file`` entry already carries a value written in the project's
dotenv file. What it cannot do is carry a variable that only exists in the shell that runs
``docker compose up`` -- and the owner keeps the Freshservice key under their own,
differently named, shell variables and maps them onto ``FRESHSERVICE_*`` in their shell
profile. So the api service lists the three connection settings under ``environment:`` as
``${NAME:-}``: Compose interpolates those from the shell first and the project dotenv file
second, so a shell value arrives, a value in the dotenv file alone still arrives, and an
unset one becomes an empty string, which ``Settings`` reads as "not configured"
(``_BLANKABLE_OPTIONAL_FIELDS``) rather than breaking startup.

Like ``test_docker_compose.py`` these tests ask ``docker compose config`` what it would
hand the container; nothing is started. ``--env-file`` points at a throwaway file
instead of the repository's gitignored one, so a developer's own settings cannot change
the answer. The values are invented.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
NAMES = ("FRESHSERVICE_URL", "FRESHSERVICE_API_KEY", "FRESHSERVICE_AGENT_EMAIL")


def _api_environment(tmp_path: Path, file_values: dict[str, str], shell_values: dict[str, str]) -> dict[str, str]:
    """The ``api`` service's ``environment`` as Compose renders it.

    The process environment is stripped of every ``FRESHSERVICE_*`` name first, so only
    ``shell_values`` can come from the shell, and only ``file_values`` from the env file.
    """
    env_file = tmp_path / "compose.env"
    env_file.write_text("".join(f"{name}={value}\n" for name, value in file_values.items()))
    env = {name: value for name, value in os.environ.items() if not name.startswith("FRESHSERVICE_")}
    env.update(shell_values)

    result = subprocess.run(
        ["docker", "compose", "--env-file", str(env_file), "config"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    return yaml.safe_load(result.stdout)["services"]["api"]["environment"]


def test_values_in_the_env_file_alone_reach_the_api_container(tmp_path: Path) -> None:
    environment = _api_environment(
        tmp_path,
        file_values={
            "FRESHSERVICE_URL": "https://example.freshservice.com",
            "FRESHSERVICE_API_KEY": "file-key",
            "FRESHSERVICE_AGENT_EMAIL": "agent@example.com",
        },
        shell_values={},
    )

    assert environment["FRESHSERVICE_URL"] == "https://example.freshservice.com"
    assert environment["FRESHSERVICE_API_KEY"] == "file-key"
    assert environment["FRESHSERVICE_AGENT_EMAIL"] == "agent@example.com"


def test_shell_values_reach_the_api_container_and_win_over_the_env_file(tmp_path: Path) -> None:
    environment = _api_environment(
        tmp_path,
        file_values={"FRESHSERVICE_URL": "https://file.freshservice.com"},
        shell_values={
            "FRESHSERVICE_URL": "https://example.freshservice.com",
            "FRESHSERVICE_API_KEY": "shell-key",
            "FRESHSERVICE_AGENT_EMAIL": "agent@example.com",
        },
    )

    assert environment["FRESHSERVICE_URL"] == "https://example.freshservice.com"
    assert environment["FRESHSERVICE_API_KEY"] == "shell-key"
    assert environment["FRESHSERVICE_AGENT_EMAIL"] == "agent@example.com"


@pytest.mark.parametrize("name", NAMES)
def test_unset_values_render_empty_without_breaking_compose(tmp_path: Path, name: str) -> None:
    environment = _api_environment(tmp_path, file_values={}, shell_values={})

    assert environment[name] == ""
