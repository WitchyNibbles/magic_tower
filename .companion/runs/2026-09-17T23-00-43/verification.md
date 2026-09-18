# Verification — FAIL

## Contract checks

- AC1: pass — `cd backend && uv run pytest tests ../tests/agent_protocol -q`
- AC2: pass — `git ls-files --error-unmatch frontend/package-lock.json && grep -q 'npm ci' frontend/Dockerfile && cd frontend && npm ci --silent && npm run build`
- AC3: pass — `cd frontend && npm run build >/dev/null 2>&1; cd .. && test -z "$(git status --porcelain)"`
- AC4: pass — `cd backend && rm -f /tmp/ac4-alembic.db && DATABASE_URL=sqlite:////tmp/ac4-alembic.db uv run alembic upgrade head && ! grep -q 'ALTER TABLE' app/main.py`
- AC5: **FAIL** — `cd backend && uv run pytest tests -q -k excerpt_is_encrypted_at_rest`
  ```
  =============================== warnings summary ===============================
  .venv/lib/python3.12/site-packages/starlette/testclient.py:40
    /home/eimi/projects/magic-tower/backend/.venv/lib/python3.12/site-packages/starlette/testclient.py:40: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
      _PortalFactoryType = typing.Callable[[], typing.ContextManager[anyio.abc.BlockingPortal]]
  
  -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
  18 deselected, 1 warning in 0.23s
  ```
- AC6: **FAIL** — `cd backend && uv run pytest tests -q -k per_source_dispatch`
  ```
  =============================== warnings summary ===============================
  .venv/lib/python3.12/site-packages/starlette/testclient.py:40
    /home/eimi/projects/magic-tower/backend/.venv/lib/python3.12/site-packages/starlette/testclient.py:40: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
      _PortalFactoryType = typing.Callable[[], typing.ContextManager[anyio.abc.BlockingPortal]]
  
  -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
  18 deselected, 1 warning in 0.21s
  ```
- AC7: **FAIL** — `cd backend && uv run pytest tests -q -k promotion`
  ```
  =============================== warnings summary ===============================
  .venv/lib/python3.12/site-packages/starlette/testclient.py:40
    /home/eimi/projects/magic-tower/backend/.venv/lib/python3.12/site-packages/starlette/testclient.py:40: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
      _PortalFactoryType = typing.Callable[[], typing.ContextManager[anyio.abc.BlockingPortal]]
  
  -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
  18 deselected, 1 warning in 0.22s
  ```
- AC8: **FAIL** — `cd backend && uv run pytest tests -q -k backfill`
  ```
  =============================== warnings summary ===============================
  .venv/lib/python3.12/site-packages/starlette/testclient.py:40
    /home/eimi/projects/magic-tower/backend/.venv/lib/python3.12/site-packages/starlette/testclient.py:40: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
      _PortalFactoryType = typing.Callable[[], typing.ContextManager[anyio.abc.BlockingPortal]]
  
  -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
  18 deselected, 1 warning in 0.22s
  ```
- AC9: **FAIL** — `cd backend && uv run pytest tests -q -k "pagination or indexes"`
  ```
  =============================== warnings summary ===============================
  .venv/lib/python3.12/site-packages/starlette/testclient.py:40
    /home/eimi/projects/magic-tower/backend/.venv/lib/python3.12/site-packages/starlette/testclient.py:40: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
      _PortalFactoryType = typing.Callable[[], typing.ContextManager[anyio.abc.BlockingPortal]]
  
  -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
  18 deselected, 1 warning in 0.22s
  ```
- AC10: **FAIL** — `cd backend && uv run pytest tests -q -k "promote_endpoint or dismiss_endpoint"`
  ```
  =============================== warnings summary ===============================
  .venv/lib/python3.12/site-packages/starlette/testclient.py:40
    /home/eimi/projects/magic-tower/backend/.venv/lib/python3.12/site-packages/starlette/testclient.py:40: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
      _PortalFactoryType = typing.Callable[[], typing.ContextManager[anyio.abc.BlockingPortal]]
  
  -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
  18 deselected, 1 warning in 0.22s
  ```
- AC11: **FAIL** — `cd backend && uv run python -m app.tools.heuristic_eval --sample "${MAGIC_TOWER_SAMPLE:-$HOME/.magic-tower/labeled-sample.json}"`
  ```
  /home/eimi/projects/magic-tower/backend/.venv/bin/python3: Error while finding module specification for 'app.tools.heuristic_eval' (ModuleNotFoundError: No module named 'app.tools')
  ```
- AC12: pass — `cd frontend && npm run test -- --run`
- AC13: pass — `cd frontend && npm run test -- --run -t "triage"`
- AC14: **FAIL** — `cd backend && uv run pytest tests -q -k sync_populates_api`
  ```
  =============================== warnings summary ===============================
  .venv/lib/python3.12/site-packages/starlette/testclient.py:40
    /home/eimi/projects/magic-tower/backend/.venv/lib/python3.12/site-packages/starlette/testclient.py:40: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
      _PortalFactoryType = typing.Callable[[], typing.ContextManager[anyio.abc.BlockingPortal]]
  
  -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
  18 deselected, 1 warning in 0.22s
  ```
- AC15: **FAIL** — `test "$(gh run list --branch "$(git rev-parse --abbrev-ref HEAD)" --limit 1 --json headSha,conclusion -q '.[0].headSha+":"+.[0].conclusion')" = "$(git rev-parse HEAD):success"`

## Dead code

- dead-code count 3 (baseline 4)

## Transcript scan

- `noqa` in backend/alembic/env.py:23: …from app import models  # noqa: F401…

## Not verified (residuals)

- none
