# Contract — backend suite green, for real and for everyone

Approved: 2026-09-17 · Sealed by `.companion/contract.sha256`.
Changing this file after approval requires `/companion:contract` again; `companion build` refuses otherwise.

## Result
A fresh clone of this branch can run one command and see the whole backend suite pass —
today that is impossible, because the fix lives in three untracked files. The README stops
claiming a hang that no longer exists. Test isolation stops depending on a single shared
SQLite path and a fixed engine built at import time, so the import-order bug that caused
the original failure cannot come back silently. CI enforces all of it on every push.

## Non-goals
- Chasing the reported AnyIO portal hang. Three independent runs (12x, 3x, per-file, reverse
  order) show 8/8 passing; the symptom was `OperationalError: unable to open database file`
  from import order, not a portal deadlock.
- Rewriting tests to `httpx.AsyncClient` + `ASGITransport`. Every route is sync `def`.
- Bumping fastapi 0.115→0.141 / starlette 1.6. That forces the `@app.on_event("startup")`
  → lifespan rewrite (`backend/app/main.py:46`) and is a separate task.
- Touching the frontend, or its unpinned `latest` dependencies (`frontend/package.json:11-17`).

## Environment facts
- test: `cd backend && uv run pytest tests ../tests/agent_protocol -q`
  — **runs today: 18 passed in 0.67s.** Covers both the 8 backend tests and the 10
  `tests/agent_protocol` tests in one invocation.
- run: `cd backend && DATABASE_URL=sqlite:///./workboard.db uv run uvicorn app.main:app`
  (verified: startup completes, `GET /api/health` → 200 with security headers)
- lint: none — no ruff/black/flake8/mypy configured anywhere in `backend/pyproject.toml`.
- dead-code: omitted — vulture is not installed and adding it is out of scope.
- Python 3.12 (`backend/.python-version`), package manager **uv**. No CI exists (`.github` absent),
  no Makefile, no justfile.
- **The test command must be run from `backend/`.** `app/config.py:13` sets `env_file=".env"`,
  which is cwd-relative; from the repo root pytest loads the root `.env`, whose empty
  `MICROSOFT_*` values fail Settings validation and abort collection with 3 pydantic
  `ValidationError`s. Verified today.
- `backend/tests/conftest.py`, `backend/pyproject.toml` and `backend/uv.lock` are **untracked**.
  `backend/Dockerfile:12-13` already COPYs the latter two, so a fresh clone cannot build.
- Env var names the suite depends on: `DATABASE_URL`, `LOCAL_API_TOKEN` (test literals are
  asserted verbatim — `conftest.py:8` is consumed at `test_work_items.py:8,37`).

## Acceptance criteria
- AC1: One command runs both suites green from a fresh clone of the branch.
  - verify: `d=$(mktemp -d) && git clone -q . "$d" && cd "$d/backend" && uv sync -q && uv run pytest tests ../tests/agent_protocol -q`
- AC2: The fix is committed — the uv migration and conftest are tracked files.
  - verify: `git ls-files --error-unmatch backend/pyproject.toml backend/uv.lock backend/tests/conftest.py`
- AC3: The README documents the green command and no longer claims a hang.
  - verify: `grep -q 'uv run pytest' README.md && ! grep -qiE 'hang|AnyIO portal' README.md`
- AC4: Tests no longer share one fixed SQLite path; two suite runs in parallel both pass.
  - verify: `cd backend && (uv run pytest tests -q & uv run pytest tests -q & wait)` — both exit 0
  - verify: `! grep -q '/tmp/workboard-tests.db' backend/tests/conftest.py`
- AC5: A hang anywhere in the suite fails loudly instead of blocking forever.
  - verify: `cd backend && uv run pytest tests ../tests/agent_protocol -q --timeout=30` exits 0,
    and `grep -qE 'timeout' backend/pyproject.toml`
- AC6: The in-process session store does not leak across tests, and a test proves it.
  - verify: `cd backend && uv run pytest tests -q -k session_store_is_isolated`
- AC7: `docker compose build` succeeds from a fresh clone (not just from this working tree).
  - verify: `d=$(mktemp -d) && git clone -q . "$d" && cd "$d" && docker compose build`
- AC8: A CI workflow runs the test command and the Docker build on push.
  - verify: `uv run --project backend --with pyyaml python -c "import yaml,pathlib,sys; w=yaml.safe_load(pathlib.Path('.github/workflows/ci.yml').read_text()); s=str(w); sys.exit(0 if 'uv run pytest' in s and 'docker' in s.lower() else 1)"`
  - note: that the workflow actually passes on GitHub is manual — no runner here, actionlint absent.
- AC9: The README's `uv tool install --editable .` path works — `[build-system]` is present.
  - verify: `cd backend && uv sync -q && ./.venv/bin/magic-tower-api --help`
- AC10: Build artefacts are ignored; `git status` is clean after a full test + run cycle.
  - verify: `cd backend && uv run pytest tests -q >/dev/null && cd .. && test -z "$(git status --porcelain)"`

## Quality bar
- Tests first; each behaviour change has a test that fails without it. AC6 in particular:
  the worker must show the new test failing before the cleanup fixture is added.
- No dead code left behind — `create_item()` at `backend/tests/test_security.py:9` is already
  orphaned by the conftest move and must go.
- No debug output, no unrelated formatting churn.
- Matches existing conventions: sync `def` routes, module-level `app`, docstring style in
  `backend/tests/conftest.py`.
- Secrets stay out of source: settings default `None` (`backend/app/config.py:18-26`), missing
  token → 503 (`backend/app/security.py:35-43`), `hmac.compare_digest` compare. A test fix must
  not weaken any asserted invariant.

## Playbook checks applied
- No `.companion/playbook.md` exists yet — this is the first loop, nothing to carry in.

## Verify commands, run once at contract time (2026-09-17)
| AC | exit | note |
|----|------|------|
| AC1 | 2 | fresh clone has no `pyproject.toml`/`uv.lock` — `uv sync` fails |
| AC2 | 1 | the three files are untracked |
| AC3 | 1 | `README.md:30-33` still claims the hang |
| AC4 | 1 | conftest still pins `/tmp/workboard-tests.db` |
| AC5 | 4 | `pytest: error: unrecognized arguments: --timeout=30` — pytest-timeout absent |
| AC6 | 5 | no such test — 8 deselected |
| AC7 | **0** | passes *today only because HEAD still has the pip Dockerfile + `requirements.txt`*. It becomes a real guard the moment T01 commits the uv Dockerfile; that is exactly the hazard it protects against. |
| AC8 | 1 | no `.github/workflows/ci.yml` |
| AC9 | 127 | no `[build-system]`, so no `magic-tower-api` script in the venv |
| AC10 | 1 | untracked `workboard.db`, `.venv/`, `*.egg-info/` dirty the tree |
