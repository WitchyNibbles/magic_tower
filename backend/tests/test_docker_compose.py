"""``docker-compose.yml``'s web host port, and what the README says about it.

The compose file used to hardcode the web service's published port as
``127.0.0.1:8787:8080``. When something else on the host already held 8787 --
this repository's own dev tooling can -- ``docker compose up`` failed to bind
``web`` regardless of what the application code did, and the documented run
command in the README was simply wrong for that machine. The port has to be
overridable with a ``WEB_PORT`` environment variable, defaulting to 8787 so
nothing changes for a reader who never sets it, and the README has to say so
next to the run instructions it already carries.

These tests shell out to ``docker compose config``, which resolves
``${WEB_PORT:-8787}``-style interpolation the same way ``docker compose up``
would, but needs no daemon and starts no container -- it only parses and
renders the Compose file. That is deliberate: a test that instead grepped the
compose file for the literal string ``${WEB_PORT:-8787}`` would pin the
spelling of the fix, not the behaviour a reader actually gets, and would pass
just as well for a typo that a shell never expands. ``docker compose config``
is also how the port default was proven here: this host's 8787 is held by
unrelated tooling for the whole session, so the default could not be proven by
actually binding it -- only by asking Compose what it would bind. The Docker
CLI is a prerequisite of this repository's own documented run command and is
already relied on by CI's build job on the same runner image, so requiring it
here does not add a new dependency to the suite.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def _rendered_web_ports(web_port: str | None) -> list[dict]:
    """The ``ports`` Compose says it will publish for ``web``, with ``WEB_PORT`` as given.

    ``web_port=None`` means the variable is unset entirely, not set to an empty string.

    ``--env-file /dev/null`` is what makes that true. Compose otherwise interpolates from
    the project-root ``.env`` as well as the environment, and that file is gitignored --
    so a developer who happens to keep ``WEB_PORT`` in their own ``.env`` would see the
    default test render their port and fail, on a checkout identical to everyone else's.
    Only the file the test renders against changes here; ``docker compose up`` still reads
    ``.env`` for the user, which is exactly where their real configuration belongs.
    """
    env = dict(os.environ)
    env.pop("WEB_PORT", None)
    if web_port is not None:
        env["WEB_PORT"] = web_port

    result = subprocess.run(
        ["docker", "compose", "--env-file", "/dev/null", "config"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr

    rendered = yaml.safe_load(result.stdout)
    return rendered["services"]["web"]["ports"]


def test_web_port_defaults_to_8787_on_loopback_only_when_unset() -> None:
    ports = _rendered_web_ports(web_port=None)

    assert len(ports) == 1, ports
    assert ports[0]["published"] == "8787"
    assert ports[0]["host_ip"] == "127.0.0.1"


def test_web_port_env_var_overrides_the_published_port() -> None:
    ports = _rendered_web_ports(web_port="9191")

    assert len(ports) == 1, ports
    assert ports[0]["published"] == "9191"


def test_web_port_override_stays_loopback_only() -> None:
    ports = _rendered_web_ports(web_port="9191")

    assert ports[0]["host_ip"] == "127.0.0.1", "an overridden port must stay loopback-only too"


def test_readme_documents_the_web_port_variable() -> None:
    """The run instructions the README already carries (``docker compose up --build``,
    ``http://localhost:8787``) have to name ``WEB_PORT`` too, so a reader whose 8787 is
    occupied can find out what to do without reading the compose file.
    """
    readme = (REPO_ROOT / "README.md").read_text()

    section = re.search(r"\n## Raise the tower locally\n(.*?)(?=\n## )", readme, re.DOTALL)
    assert section, "README.md no longer has a 'Raise the tower locally' section"
    assert "WEB_PORT" in section.group(1)


def test_readme_web_port_paragraph_points_at_the_redirect_uri() -> None:
    """Changing ``WEB_PORT`` alone silently breaks Graph sign-in, so the paragraph that
    offers the override has to say so.

    ``MICROSOFT_REDIRECT_URI`` defaults to ``http://localhost:8787/api/auth/callback``
    (``app/config.py``) and is not derived from ``WEB_PORT``; nor should it be, since the
    value has to match a URI registered in Entra, and Microsoft rejects one that is not.
    A reader who follows the override advice and nothing else therefore reaches a
    sign-in that cannot complete. Pinning the pointer to the same paragraph keeps the
    two from drifting apart again.
    """
    readme = (REPO_ROOT / "README.md").read_text()

    section = re.search(r"\n## Raise the tower locally\n(.*?)(?=\n## )", readme, re.DOTALL)
    assert section, "README.md no longer has a 'Raise the tower locally' section"

    paragraphs = [p for p in section.group(1).split("\n\n") if "WEB_PORT" in p]
    assert paragraphs, "the 'Raise the tower locally' section no longer mentions WEB_PORT"
    assert any("MICROSOFT_REDIRECT_URI" in p for p in paragraphs), (
        "the WEB_PORT paragraph must tell the reader to move MICROSOFT_REDIRECT_URI too"
    )
