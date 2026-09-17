# Plan — backend suite green, for real and for everyone

One task per `## Txx` heading. Statuses: `todo` → `doing` → `claimed` → `verified`, or `blocked(<reason>)`.
Only the manager edits this file.

## T01 — Commit the uv migration
- status: verified
- complexity: simple
- deps:
- done-when: `d=$(mktemp -d) && git clone -q . "$d" && cd "$d" && docker compose build && test -f backend/pyproject.toml && test -f backend/uv.lock`

Commit 1 of the two the owner asked for. Track `backend/pyproject.toml`, `backend/uv.lock` and the
modified `backend/Dockerfile` together — the Dockerfile already COPYs the other two
(`backend/Dockerfile:12-13`), so committing it alone breaks `docker compose build` on a fresh clone.
Also in this commit: add `[build-system]` (hatchling or setuptools, whichever matches the existing
`magic_tower_api.egg-info` layout) so `project.scripts` stops being skipped by `uv sync`, and add
`*.db`, `.venv/`, `*.egg-info/` to `.gitignore`. Track `backend/.python-version` too — it pins 3.12 and
is what makes `uv sync` reproducible. Do not commit `backend/workboard.db`.
Leaves the suite red on a fresh clone — that is expected and T02 closes it.

## T02 — Commit the test fix and correct the README
- status: verified
- complexity: simple
- deps: T01
- done-when: `d=$(mktemp -d) && git clone -q . "$d" && cd "$d/backend" && uv sync -q && uv run pytest tests ../tests/agent_protocol -q`

Commit 2. Track `backend/tests/conftest.py` and the diffs to `test_security.py` / `test_work_items.py`.
Delete the now-orphaned `create_item()` at `backend/tests/test_security.py:9`. Rewrite
`README.md:30-33`: drop the AnyIO-portal hang paragraph entirely and document
`cd backend && uv run pytest tests ../tests/agent_protocol` as the green command, including the fact
that it must run from `backend/` because `env_file=".env"` is cwd-relative (`backend/app/config.py:13`).

## T03 — Give every test its own database
- status: verified
- complexity: normal
- deps: T02
- done-when: `cd backend && (uv run pytest tests -q & uv run pytest tests -q & wait) && ! grep -q '/tmp/workboard-tests.db' tests/conftest.py`

Replace the fixed `/tmp/workboard-tests.db` with a per-session path from `tmp_path_factory`, so two
pytest processes cannot drop each other's tables. The engine is built at import time
(`backend/app/database.py:17`) from `@lru_cache get_settings` (`backend/app/config.py:65-67`), so the
env var must still be set before app import — keep that ordering and write a comment saying why.
Test first: a test that fails under the current shared path.

## T04 — Make a hang fail loudly
- status: verified
- complexity: simple
- deps: T02
- done-when: `cd backend && uv run pytest tests ../tests/agent_protocol -q --timeout=30`

Add `pytest-timeout` to the dev dependency group and configure a default timeout with
`--timeout-method=thread` in `[tool.pytest.ini_options]` (`backend/pyproject.toml:23-25`). Thread
method is the one that can interrupt a blocked C-level call. Re-run `uv lock`. If the original
hang ever returns, this turns it into a dumped stack instead of a stuck CI job.

## T05 — Stop the session store leaking between tests
- status: verified
- complexity: normal
- deps: T02
- done-when: `cd backend && uv run pytest tests -q -k session_store_is_isolated`

`_sessions` is a module-level dict guarded by a `Lock` (`backend/app/security.py:31-32`) and is never
cleared, so session state survives from test to test in-process. Write `session_store_is_isolated`
first and show it failing, then clear the store in the autouse fixture. Do not change the production
locking or the `hmac.compare_digest` comparison (`backend/app/security.py:48`).

## T06 — CI enforces the whole bar
- status: todo
- complexity: normal
- deps: T03, T04, T05
- done-when: `uv run --project backend --with pyyaml python -c "import yaml,pathlib,sys; w=yaml.safe_load(pathlib.Path('.github/workflows/ci.yml').read_text()); s=str(w); sys.exit(0 if 'uv run pytest' in s and 'docker' in s.lower() else 1)"`

Net-new: there is no `.github`, Makefile or justfile. One workflow, on push and pull_request, with a
test job (`astral-sh/setup-uv`, Python 3.12, `cd backend && uv run pytest tests ../tests/agent_protocol`)
and a build job (`docker compose build`). Run the tests from `backend/` — from the repo root a
checkout without `.env` would pass locally-inconsistently, and the cwd-relative `env_file` is a trap
worth not re-learning. That the workflow goes green on GitHub is manual; no runner and no actionlint here.
