# Explore — "fix the broken piece: TestClient tests hang in AnyIO portal"

## Idea
README claims the FastAPI `TestClient` tests hang in Starlette's AnyIO portal and need a
compatibility repair. Goal: make the backend suite run green.

## Facts
- **The hang does not reproduce.** `cd backend && uv sync && uv run pytest -q` → `8 passed in ~0.7s`,
  exit 0. Three scouts ran it independently (12x, 3x, per-file, reverse order, `--collect-only`).
  No faulthandler dump at `faulthandler_timeout=25/30`. There is no portal deadlock to fix.
- **The real bug was import order, not a hang.** `backend/app/database.py:17` builds the engine at
  import time from `@lru_cache get_settings` (`backend/app/config.py:65-67`). Both test modules used
  to set `DATABASE_URL` at module scope, so whichever imported first won. Reproduced from HEAD files:
  `sqlalchemy.exc.OperationalError: unable to open database file`, `cargs = ('/data/workboard.db',)`
  — 5 errors in 2.2s. Default DB path is `/data/workboard.db` (`backend/app/config.py:17`), and
  `/data` does not exist on this host.
- **It is already fixed, by untracked code.** `backend/tests/conftest.py` (NEW) sets `DATABASE_URL`
  and `LOCAL_API_TOKEN` before app import (`:7-8`) and adds an autouse `get_settings.cache_clear()` +
  drop/create fixture (`:16-24`). Delete conftest → `5 failed, 3 passed`, same OperationalError.
  The diffs to `test_security.py` / `test_work_items.py` only remove the old per-module blocks.
- **The README paragraph is stale.** `README.md:30-33` asserts the hang; README mtime Sep 13 13:23,
  tests rewritten 11:03 — the claim was written ~2h *after* the fix landed.
- Tests already use `with TestClient(app) as client:` (`test_work_items.py:5`, `test_security.py:19`),
  so the #1 real hang cause (lifespan never runs) was never in play. Every route is sync `def`; the
  only `async def` is the body-limit middleware (`backend/app/main.py:16-43`), so blocking SQLAlchemy
  runs in the anyio threadpool by construction. `check_same_thread: False` is set.
- Locked stack: Python 3.12, fastapi 0.115.6, starlette 0.41.3, anyio 4.15.1, httpx 0.28.1,
  sqlalchemy 2.0.36, pytest 8.3.4. No pytest-asyncio, no pytest-timeout, no anyio mode config
  (`backend/pyproject.toml:23-25` is only `testpaths`/`pythonpath`). `uv lock --check` clean.
- **Commit hazard.** `backend/Dockerfile:3,12-13` is now uv-based and COPYs `pyproject.toml uv.lock`
  — both untracked. Committing the Dockerfile without them breaks `docker compose build`.
  `requirements.txt` is deleted and nothing else in the repo references it (0 grep hits).
  `uv sync` warns: `project.scripts` skipped, no `[build-system]` — so README's
  `uv tool install --editable .` / `magic-tower-api` path is unverified.
- **Latent tripwire.** starlette 0.41.3 imports `anyio.abc.BlockingPortal` (`testclient.py:40`);
  anyio 4.15 made that a deprecated lazy alias (agronholm/anyio#1169). Emits a DeprecationWarning
  today; adding `filterwarnings = ["error"]` would break *collection* (exit 2) — cf. guard-agent#55,
  Doberman-Core#553. Fixed upstream by Kludex/starlette#3498 (merged 2026-09-05, not in 1.6.0).
- **Upgrade debt.** `@app.on_event("startup")` (`backend/app/main.py:46`) is deprecated and removed
  in Starlette 1.x — a version bump breaks the app, not the tests.
- Isolation is coarse: one fixed SQLite path `/tmp/workboard-tests.db`, drop/create per test (not
  rollback). `_sessions` global (`backend/app/security.py:31`) is never cleared between tests.
  pytest-xdist would have workers dropping tables under each other. `backend/workboard.db` is
  untracked and *not* gitignored (created by a manual uvicorn run; suite never touches it).
  Neither `.venv/` nor `*.egg-info/` are ignored either.
- Scope boundary: `testpaths` is rooted at backend, so `tests/agent_protocol/test_pending_work_cli.py`
  (10 tests, passes in 0.04s) is NOT in the backend command. No CI (`.github` absent), no Makefile,
  no Docker test path (Dockerfile installs `--no-dev`, so pytest is absent from the image).
- Security invariants a fix must not weaken: no hardcoded secrets in app code, secrets default `None`
  (`backend/app/config.py:18-26`), missing token → 503 (`backend/app/security.py:35-43`),
  `hmac.compare_digest` bearer compare (`:48`). Tests pin literal tokens (`conftest.py:8` consumed at
  `test_work_items.py:8,37`; `unit-test-token` at `test_security.py:25`) — changing them breaks tests.

## Options
| # | What | Pros | Cons | Effort |
|---|------|------|------|--------|
| A | **Land the fix that exists**: commit conftest.py + pyproject.toml + uv.lock with the Dockerfile, rewrite `README.md:30-33` to document `uv sync && uv run pytest` as green, gitignore `*.db`/`.venv/`/`*.egg-info/` | Makes the green suite reproducible for everyone; removes the only artifact still asserting a bug; unblocks `docker compose build` | Doesn't harden anything | S |
| B | **A + harden**: per-test DB via `tmp_path_factory`, add `pytest-timeout` with `--timeout-method=thread`, clear `_sessions` between tests, add `[build-system]` so `project.scripts` works | Import-order trap can't return; any future hang self-diagnoses instead of blocking; parallel-safe | Touches app/test wiring; small scope creep | M |
| C | **Rewrite to `httpx.AsyncClient` + `ASGITransport`** | Async failures surface loudly | Needs `asgi-lifespan` (ASGITransport skips lifespan); rewrites 8 passing tests; every route here is sync so it buys nothing | L |
| D | **Version bump** fastapi 0.115→0.141 / starlette 1.6 | Clears the anyio 4.15 deprecation permanently | Forces `on_event`→lifespan rewrite + Starlette 1.0 breaking changes; solves a problem not currently biting | M |

## Recommendation
**B** — land the existing fix properly (commit the uv migration + conftest, correct the stale README,
fix .gitignore) and spend the extra S on per-test DB isolation plus a `pytest-timeout` tripwire so
the import-order trap can't come back silently. Schedule D separately as a dependency-upgrade task;
skip C entirely — the app is 100% sync routes.

## Open questions
1. Was the hang ever observed on *this* machine, or in CI/Docker/a pre-uv pip env? Nobody can
   reproduce it on 3.12 or 3.13 with the locked versions.
2. Does "green" mean `cd backend && uv run pytest` only, or also the root `tests/agent_protocol`
   suite (10 tests) and `docker compose build`?
3. Commit the untracked uv migration (pyproject.toml, uv.lock, conftest.py) on this branch, or keep
   it separate from the Dockerfile change?
4. Add `[build-system]` so README's `uv tool install --editable .` / `magic-tower-api` actually works?

## Decisions (owner, 2026-09-17)
1. **Scope: Option B** — land the existing fix *and* harden (per-test DB via `tmp_path_factory`,
   `pytest-timeout --timeout-method=thread`, clear the `_sessions` global between tests).
2. **Green bar is all four**: `cd backend && uv run pytest`; the root `tests/agent_protocol` suite
   (10 tests); `docker compose build`; and a CI workflow enforcing them. CI is net-new work
   (no `.github` today) — this is the largest single piece, ~M on its own. Widening the bar to
   `agent_protocol` means either widening `testpaths` (`backend/pyproject.toml:23-25`) or running
   two pytest invocations in CI; the contract should pick one.
3. **Two commits**: (1) uv migration — `pyproject.toml`, `uv.lock`, `Dockerfile`; (2) test fix —
   `conftest.py`, test diffs, README. Noted and accepted: commit 1 alone has no working test path
   (pytest resolves, but 5 tests fail on `/data/workboard.db` until conftest lands).
4. **Extras: both** — add `[build-system]` so `project.scripts` / `uv tool install --editable .`
   work as the README promises, and gitignore `*.db`, `.venv/`, `*.egg-info/`.
5. Not doing: Option C (async client rewrite) or D (fastapi/starlette bump). D stays a separate
   task — it forces the `on_event`→lifespan rewrite.
