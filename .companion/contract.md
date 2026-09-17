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
  — **runs today: 26 passed in 4.70s** (was 18 at first sealing; T03–T06 added 8). Covers the
  backend tests and the `tests/agent_protocol` tests in one invocation.
- run: `cd backend && DATABASE_URL=sqlite:///./workboard.db uv run uvicorn app.main:app`
  (verified: startup completes, `GET /api/health` → 200 with security headers)
- lint: none — no ruff/black/flake8/mypy configured anywhere in `backend/pyproject.toml`.
- (no `dead-code:` key: vulture is not installed and adding it is out of scope. The key is omitted
  rather than given a prose value, because the verifier runs whatever follows `dead-code:` as a command.)
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
  - verify: `cd backend && { uv run pytest tests -q & a=$!; uv run pytest tests -q & b=$!; wait $a && wait $b; }`
  - verify: `! grep -q '/tmp/workboard-tests.db' backend/tests/conftest.py`
- AC5: A hang anywhere in the suite fails loudly instead of blocking forever.
  - verify: `cd backend && uv run pytest tests ../tests/agent_protocol -q --timeout=30 && grep -qE '^timeout' pyproject.toml`
- AC6: The in-process session store does not leak across tests, and a test proves it.
  - verify: `cd backend && uv run pytest tests -q -k session_store_is_isolated`
- AC7: `docker compose build` succeeds from a fresh clone (not just from this working tree).
  - verify: `d=$(mktemp -d) && git clone -q . "$d" && cd "$d" && docker compose build`
- AC8: A CI workflow runs the test command and the Docker build on push.
  - verify: `uv run --project backend --with pyyaml python -c "import yaml,pathlib,sys; w=yaml.safe_load(pathlib.Path('.github/workflows/ci.yml').read_text()); s=str(w); sys.exit(0 if 'uv run pytest' in s and 'docker' in s.lower() else 1)"`
  - verify: manual — that the workflow goes green on GitHub. No runner and no actionlint here, so
    nothing local can check it; the parse check above is the most a command can prove.
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

