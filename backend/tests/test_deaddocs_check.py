"""``scripts/deaddocs_check.py``, the dead-documentation checker plugged into
``scripts/deadcode.sh``'s dead-code gate (see the ``# --- Documentation`` block).

Owner: "even dead documentation... should be common sense." A doc that still
tells the reader to hit a file, an endpoint, an env var, or a CLI module that no
longer exists is exactly the kind of dead reference the rest of the gate cannot
see, because vulture/knip/the CSS checker only look at code, never at prose.

These tests build a *synthetic* repository under ``tmp_path`` rather than
mutating this repository's own README/docs, for two reasons: the checker's
real-world false-positive count on this repo's actual docs (documented in the
checker's own module docstring) would make a hard-coded "starts at N" assertion
brittle against unrelated doc edits, and a synthetic fixture lets each class of
reference (path / endpoint / env var / command) be pinned in isolation with a
known-good and a known-dead example side by side.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / "scripts" / "deaddocs_check.py"


def _run(root: Path) -> tuple[int, str, str]:
    result = subprocess.run(
        [sys.executable, str(CHECKER), str(root)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.returncode, result.stdout, result.stderr


def _count(root: Path) -> int:
    status, stdout, stderr = _run(root)
    assert status == 0, f"checker crashed: stderr={stderr!r}"
    lines = [line for line in stdout.splitlines() if line]
    assert lines and re.fullmatch(r"[0-9]+", lines[-1]), f"non-integer output: {stdout!r}"
    return int(lines[-1])


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """A minimal repository shaped like this one: a FastAPI router, a config
    module, a `.env.example`, a `docker-compose.yml`, and README/docs/.companion
    doc files that reference only things which genuinely exist in it.
    """
    root = tmp_path / "repo"
    (root / "backend" / "app" / "api").mkdir(parents=True)
    (root / "backend" / "app" / "tools").mkdir(parents=True)
    (root / "frontend" / "src").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / ".companion").mkdir()

    (root / "backend" / "app" / "api" / "routes.py").write_text(
        'from fastapi import APIRouter\n'
        'router = APIRouter(prefix="/api")\n\n'
        '@router.get("/work-items")\n'
        'def list_items():\n'
        '    ...\n'
    )
    (root / "backend" / "app" / "main.py").write_text(
        'from fastapi import FastAPI\n'
        'app = FastAPI()\n\n'
        '@app.get("/api/health")\n'
        'def health():\n'
        '    ...\n'
    )
    (root / "backend" / "app" / "config.py").write_text(
        'class Settings:\n'
        '    known_setting: str = "x"\n'
    )
    # The two halves of the retired-capability vocabulary: what the code
    # supports now, and what the schema has ever spelled.
    (root / "backend" / "app" / "models.py").write_text(
        "import enum\n\n"
        "class SourceKind(str, enum.Enum):\n"
        '    outlook_email = "outlook_email"\n'
        '    manual = "manual"\n'
    )
    (root / "backend" / "alembic" / "versions").mkdir(parents=True)
    (root / "backend" / "alembic" / "versions" / "0001_initial.py").write_text(
        "import sqlalchemy as sa\n"
        "from alembic import op\n\n"
        "def upgrade():\n"
        "    op.create_table(\n"
        "        'sources',\n"
        "        sa.Column('kind', sa.Enum('outlook_email', 'teams_message', 'manual',"
        " name='sourcekind'), nullable=False),\n"
        "    )\n"
    )
    (root / "backend" / "app" / "tools" / "real_tool.py").write_text("def main(): ...\n")
    (root / "frontend" / "src" / "component.ts").write_text("export const x = 1;\n")
    (root / ".env.example").write_text("KNOWN_ENV_VAR=\n")
    (root / "docker-compose.yml").write_text("services: {}\n")
    # Both gitignore shapes the checker has to handle: a directory-only pattern
    # (matched only when the query carries a trailing slash) and a plain file.
    (root / ".gitignore").write_text("node_modules/\nbackend/local-notes.md\n__pycache__/\n")

    (root / "README.md").write_text(
        "# Fake project\n\n"
        "See `backend/app/tools/real_tool.py` for the entry point.\n"
        "Run `GET /api/work-items` to list items.\n"
        "Set `KNOWN_ENV_VAR` before starting.\n"
        "Or run `uv run python -m app.tools.real_tool`.\n"
    )
    (root / "docs" / "guide.md").write_text("Nothing else to see here.\n")
    (root / ".companion" / "plan.md").write_text("Planning notes, no references.\n")
    (root / ".companion" / "harness-notes.md").write_text(
        "For the owner to carry to the project-companion repo.\n"
        "`scripts/lib/plan.mjs` lives over there, not here.\n"
    )

    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    return root


def test_checker_script_exists() -> None:
    assert CHECKER.is_file(), "scripts/deaddocs_check.py does not exist"


def test_clean_fixture_reports_zero(fake_repo: Path) -> None:
    """A repo whose docs reference only things that really exist reports 0."""
    assert _count(fake_repo) == 0


# --- file paths --------------------------------------------------------------

def test_dead_path_reference_raises_the_count_by_one(fake_repo: Path) -> None:
    """Casualty this pins: a doc line naming a file that was deleted (or never
    existed) but is still linked from the docs, the motivating bug behind this
    checker (a broken ``docker compose cp`` path in the README, historically).
    """
    before = _count(fake_repo)
    readme = fake_repo / "README.md"
    readme.write_text(readme.read_text() + "\nAlso see `backend/app/tools/deleted_tool.py`.\n")
    assert _count(fake_repo) == before + 1


def test_existing_path_reference_does_not_raise_the_count(fake_repo: Path) -> None:
    """Negative control for the test above: a line added in the same shape,
    naming a file that *does* exist, must not move the count at all.
    """
    before = _count(fake_repo)
    readme = fake_repo / "README.md"
    readme.write_text(readme.read_text() + "\nAlso see `backend/app/config.py`.\n")
    assert _count(fake_repo) == before


def test_path_under_subproject_root_resolves_after_a_cd(fake_repo: Path) -> None:
    """Docs switch base directory mid-file after `cd backend` (this project's
    own README does exactly that around its Alembic instructions), so a path
    written relative to `backend/` must resolve against `backend/` too, not
    only against the repo root.
    """
    before = _count(fake_repo)
    readme = fake_repo / "README.md"
    readme.write_text(readme.read_text() + "\nFrom `backend/`, see `app/config.py`.\n")
    assert _count(fake_repo) == before


def test_gitignored_path_is_not_flagged_as_dead(fake_repo: Path) -> None:
    """A path that resolves nowhere but matches `.gitignore` (a build artifact,
    a user-created file) is expected-absent in a fresh checkout, not dead.

    The probe token has to be path-shaped (`backend/local-notes.md`, not a bare
    `notes.md`): `_looks_like_path` discards a token with no `/` and no leading
    dot long before the gitignore branch is reached, so a bare token would make
    this test pass for the wrong reason.

    Casualty this pins: deleting the `_is_gitignored` call site entirely.
    """
    before = _count(fake_repo)
    readme = fake_repo / "README.md"
    readme.write_text(readme.read_text() + "\nYour own notes live at `backend/local-notes.md`.\n")
    assert _count(fake_repo) == before


def test_gitignored_directory_pattern_is_not_flagged_as_dead(fake_repo: Path) -> None:
    """`git check-ignore` honours a directory-only pattern (`node_modules/`)
    only when the query itself carries the trailing slash -- verified directly:
    `frontend/node_modules` is reported not-ignored, `frontend/node_modules/`
    ignored. Casualty this pins: dropping `_is_gitignored`'s trailing-slash
    retry, which would flag every doc mention of an uninstalled `node_modules`.
    """
    before = _count(fake_repo)
    readme = fake_repo / "README.md"
    readme.write_text(readme.read_text() + "\nRun `npm ci` to populate `frontend/node_modules`.\n")
    assert _count(fake_repo) == before


def test_line_number_suffix_is_stripped_before_the_path_is_resolved(fake_repo: Path) -> None:
    """Docs and session logs cite live code by line (`app/models.py:26-29`), in
    three spellings: a single line, a range, and a comma-separated list. The
    suffix is not part of the filename and must be stripped before the path is
    resolved.

    Casualty this pins: neutering `_strip_line_suffix` to `return token`, which
    takes this repository's own count from 1 to 134 -- every such citation in
    `.companion/progress.md` becomes a false positive.
    """
    before = _count(fake_repo)
    readme = fake_repo / "README.md"
    readme.write_text(
        readme.read_text()
        + "\nSee `backend/app/config.py:2`, `backend/app/config.py:1-2`,"
        " and `backend/app/config.py:1,2`.\n"
    )
    assert _count(fake_repo) == before


def test_dead_path_carrying_a_line_suffix_is_still_flagged(fake_repo: Path) -> None:
    """Negative control for the test above: stripping the suffix must not be
    over-eager and swallow the finding. A citation of a file that does not
    exist is dead whether or not it names a line.
    """
    before = _count(fake_repo)
    readme = fake_repo / "README.md"
    readme.write_text(readme.read_text() + "\nSee `backend/app/vanished.py:42-48`.\n")
    assert _count(fake_repo) == before + 1


def test_absolute_path_is_not_treated_as_a_filesystem_claim(fake_repo: Path) -> None:
    """`/data`, `/api/...`, `/me` are a container mount, this app's own HTTP
    API, and Microsoft Graph, respectively -- none is a claim about a file in
    this repository, so none should be checked for filesystem existence.
    """
    before = _count(fake_repo)
    readme = fake_repo / "README.md"
    readme.write_text(readme.read_text() + "\nMounted at `/data/nonexistent-nested-thing`.\n")
    assert _count(fake_repo) == before


def test_harness_notes_file_is_excluded_from_the_path_scan(fake_repo: Path) -> None:
    """`.companion/harness-notes.md` documents a different repository (its own
    first line says so); a dead-looking path in it must not be flagged.
    """
    before = _count(fake_repo)
    notes = fake_repo / ".companion" / "harness-notes.md"
    notes.write_text(notes.read_text() + "\nAlso see `scripts/lib/verify.mjs` over there.\n")
    assert _count(fake_repo) == before


def test_a_markdown_link_with_a_backticked_label_counts_its_path_once(fake_repo: Path) -> None:
    """``[`docs/x.md`](docs/x.md)`` is this repo's own README idiom
    (`README.md:127`). It matches the backtick pattern *and* the markdown-link
    pattern, so one dead reference was reported twice -- measured on this
    repository: one such added line took the total from 11 to 13, while the
    same path written plainly took it to 12.
    """
    before = _count(fake_repo)
    readme = fake_repo / "README.md"
    readme.write_text(readme.read_text() + "\nSee [`docs/gone.md`](docs/gone.md).\n")
    assert _count(fake_repo) == before + 1


def test_two_different_dead_paths_on_one_line_count_twice(fake_repo: Path) -> None:
    """Negative control for the de-duplication above: it keys on the resolved
    path, not on the line, so it must not collapse genuinely distinct findings.
    """
    before = _count(fake_repo)
    readme = fake_repo / "README.md"
    readme.write_text(readme.read_text() + "\nSee `docs/gone-a.md` and `docs/gone-b.md`.\n")
    assert _count(fake_repo) == before + 2


# --- doc scopes ----------------------------------------------------------------

def test_companion_log_identifiers_are_out_of_scope(fake_repo: Path) -> None:
    """`.companion/*.md` is a session-by-session historical log that narrates
    *other* systems' APIs (a third-party connector sketch in `explore.md`) and
    the harness's own internal names inline in prose, so the endpoint, env-var
    and command checks deliberately stop at `README.md` and `docs/`.

    Casualty this pins: widening `_doc_scopes` to `return path_scope,
    path_scope`, which would turn all three lines below into findings.
    """
    before = _count(fake_repo)
    explore = fake_repo / ".companion" / "explore.md"
    explore.write_text(
        "Sketch of a third-party connector, not this repo's own API.\n"
        "It exposes `GET /api/work-items/imaginary`, reads"
        " `OTHER_SYSTEM_API_TOKEN`, and runs as `python -m other_repo.tool`.\n"
    )
    assert _count(fake_repo) == before


def test_companion_log_file_paths_are_in_scope(fake_repo: Path) -> None:
    """The other half of that asymmetry, so the narrowing cannot quietly become
    a blanket exclusion: a broken *path* is a narrower, more objective claim
    than an endpoint or a bare identifier, and stays checked across
    `.companion/*.md`.

    Casualty this pins: narrowing `_doc_scopes` to `return doc_files,
    doc_files`.
    """
    before = _count(fake_repo)
    progress = fake_repo / ".companion" / "progress.md"
    progress.write_text("Deleted `backend/app/tools/gone_tool.py` this session.\n")
    assert _count(fake_repo) == before + 1


# --- endpoints -----------------------------------------------------------------

def test_dead_endpoint_reference_raises_the_count_by_one(fake_repo: Path) -> None:
    """Casualty this pins: a doc line advertising a route this repo's FastAPI
    routers no longer register (renamed, or removed along with a feature).
    """
    before = _count(fake_repo)
    readme = fake_repo / "README.md"
    readme.write_text(readme.read_text() + "\nAlso call `POST /api/work-items/retire`.\n")
    assert _count(fake_repo) == before + 1


def test_existing_endpoint_reference_does_not_raise_the_count(fake_repo: Path) -> None:
    before = _count(fake_repo)
    readme = fake_repo / "README.md"
    readme.write_text(readme.read_text() + "\nOr `GET /api/health` to check liveness.\n")
    assert _count(fake_repo) == before


def test_endpoint_outside_this_repos_routers_is_left_alone(fake_repo: Path) -> None:
    """A `/api/...`-shaped path whose first segment matches none of this repo's
    routers names someone else's API (a third-party connector sketch, in this
    project's real docs) -- not ours to judge, so it is not flagged.
    """
    before = _count(fake_repo)
    readme = fake_repo / "README.md"
    readme.write_text(readme.read_text() + "\nFreshservice: `GET /api/v2/tickets`.\n")
    assert _count(fake_repo) == before


# --- env vars --------------------------------------------------------------------

def test_dead_env_var_reference_raises_the_count_by_one(fake_repo: Path) -> None:
    """Casualty this pins: a doc line naming a setting nobody's code reads --
    invented, or left behind after the code that read it was deleted."""
    before = _count(fake_repo)
    readme = fake_repo / "README.md"
    readme.write_text(readme.read_text() + "\nSet `TOTALLY_INVENTED_SETTING` too.\n")
    assert _count(fake_repo) == before + 1


def test_existing_env_var_reference_does_not_raise_the_count(fake_repo: Path) -> None:
    before = _count(fake_repo)
    readme = fake_repo / "README.md"
    readme.write_text(readme.read_text() + "\n`KNOWN_ENV_VAR` again, mentioned twice.\n")
    assert _count(fake_repo) == before


def test_snake_case_settings_field_backs_its_upper_env_var_spelling(fake_repo: Path) -> None:
    """`known_setting` in `config.py` is spelled lower in Python; the doc names
    its env-var spelling `KNOWN_SETTING` -- these must be recognized as the
    same name, case-folded, not flagged as two different unknown ones.
    """
    before = _count(fake_repo)
    readme = fake_repo / "README.md"
    readme.write_text(readme.read_text() + "\nAlso `KNOWN_SETTING` from config.\n")
    assert _count(fake_repo) == before


# --- commands ---------------------------------------------------------------------

def test_dead_command_reference_raises_the_count_by_one(fake_repo: Path) -> None:
    """Casualty this pins: a `-m package.module` invocation naming a module
    file that does not exist under `backend/`."""
    before = _count(fake_repo)
    readme = fake_repo / "README.md"
    readme.write_text(readme.read_text() + "\nOr `uv run python -m app.tools.vanished_tool`.\n")
    assert _count(fake_repo) == before + 1


def test_existing_command_reference_does_not_raise_the_count(fake_repo: Path) -> None:
    before = _count(fake_repo)
    readme = fake_repo / "README.md"
    readme.write_text(readme.read_text() + "\nAgain: `uv run python -m app.tools.real_tool`.\n")
    assert _count(fake_repo) == before


# --- retired capabilities ----------------------------------------------------------

def test_dead_capability_reference_raises_the_count_by_one(fake_repo: Path) -> None:
    """Casualty this pins: backlog B94 -- 14 doc lines still advertising Teams
    ingestion after the enum, the dispatch table and the Graph calls dropped
    it. Such a line names no file, no route, no env var and no module, only a
    connector, so none of the four checks above can see it.
    """
    before = _count(fake_repo)
    readme = fake_repo / "README.md"
    readme.write_text(readme.read_text() + "\nIngests Outlook mail and Teams conversations.\n")
    assert _count(fake_repo) == before + 1


def test_live_capability_reference_does_not_raise_the_count(fake_repo: Path) -> None:
    """Negative control: a connector the enum still defines is not dead."""
    before = _count(fake_repo)
    readme = fake_repo / "README.md"
    readme.write_text(readme.read_text() + "\nIngests Outlook mail from one mailbox.\n")
    assert _count(fake_repo) == before


def test_a_line_naming_a_retired_connector_twice_counts_once(fake_repo: Path) -> None:
    """The unit is the doc line, the way backlog B94 counts its 14 -- otherwise
    one wordy sentence would outweigh three separately wrong ones.
    """
    before = _count(fake_repo)
    readme = fake_repo / "README.md"
    readme.write_text(readme.read_text() + "\nTeams scopes and Teams metadata are both gone.\n")
    assert _count(fake_repo) == before + 1


def test_retired_vocabulary_comes_from_the_migrations_not_a_hardcoded_name(
    fake_repo: Path,
) -> None:
    """The word `teams` is never written in the checker: it is derived, so
    retiring the *next* connector needs no edit there. Rewrite the fixture's
    migration history so it never knew that kind and the identical sentence
    stops being a finding.
    """
    readme = fake_repo / "README.md"
    readme.write_text(readme.read_text() + "\nIngests Outlook mail and Teams conversations.\n")
    assert _count(fake_repo) == 1
    migration = fake_repo / "backend" / "alembic" / "versions" / "0001_initial.py"
    migration.write_text(migration.read_text().replace("'teams_message', ", ""))
    assert _count(fake_repo) == 0


def test_a_removal_migrations_kind_constant_also_feeds_the_vocabulary(fake_repo: Path) -> None:
    """A removal migration deletes rows by a `..._KIND = "..."` constant
    (`0008_remove_teams_source.py:57` in this repo). That constant is the only
    record of a kind an *initial* enum listing never contained, so it feeds the
    vocabulary too -- the next connector to be cut will leave exactly this
    trace and no other.
    """
    readme = fake_repo / "README.md"
    readme.write_text(readme.read_text() + "\nAlso tracks Jira issues.\n")
    before = _count(fake_repo)
    versions = fake_repo / "backend" / "alembic" / "versions"
    (versions / "0002_remove_jira.py").write_text('REMOVED_KIND = "jira_issue"\n')
    assert _count(fake_repo) == before + 1


def test_companion_log_may_discuss_a_retired_capability(fake_repo: Path) -> None:
    """The session log's whole job is to record *that* a connector was removed;
    it must be able to say so without the gate counting its own history. Same
    narrowing as the endpoint/env-var/command checks.
    """
    before = _count(fake_repo)
    progress = fake_repo / ".companion" / "progress.md"
    progress.write_text("T19 removed the Teams source this session.\n")
    assert _count(fake_repo) == before


# --- crash guard -------------------------------------------------------------------

def test_checker_exits_nonzero_on_an_unreadable_root(tmp_path: Path) -> None:
    """A repo root that does not exist must crash (nonzero exit), not report a
    silent 0 -- ``scripts/deadcode.sh`` treats any nonzero exit here as a crash
    and aborts the whole gate rather than folding it into the total.
    """
    missing = tmp_path / "does-not-exist-at-all"
    status, stdout, _ = _run(missing)
    assert status != 0
    assert stdout.strip() != "0"
