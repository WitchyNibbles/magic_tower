# Verification — FAIL

## Contract checks

- AC1: pass — `cd backend && uv run pytest tests ../tests/agent_protocol -q`
- AC2: pass — `git ls-files --error-unmatch frontend/package-lock.json && grep -q 'npm ci' frontend/Dockerfile && cd frontend && npm ci --silent && npm run build`
- AC3: **FAIL** — `cd frontend && npm run build >/dev/null 2>&1; cd .. && test -z "$(git status --porcelain)"`
- AC4: pass — `cd backend && rm -f /tmp/ac4-alembic.db && DATABASE_URL=sqlite:////tmp/ac4-alembic.db uv run alembic upgrade head && ! grep -q 'ALTER TABLE' app/main.py`
- AC5: pass — `cd backend && uv run pytest tests -q -k excerpt_is_encrypted_at_rest`
- AC6: pass — `cd backend && uv run pytest tests -q -k per_source_dispatch`
- AC7: pass — `cd backend && uv run pytest tests -q -k promotion`
- AC8: **FAIL** — `cd backend && uv run pytest tests -q -k backfill`
  ```
  =============================== warnings summary ===============================
  .venv/lib/python3.12/site-packages/starlette/testclient.py:40
    /home/eimi/projects/magic-tower/backend/.venv/lib/python3.12/site-packages/starlette/testclient.py:40: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
      _PortalFactoryType = typing.Callable[[], typing.ContextManager[anyio.abc.BlockingPortal]]
  
  -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
  112 deselected, 1 warning in 0.28s
  ```
- AC9: **FAIL** — `cd backend && uv run pytest tests -q -k "pagination or indexes"`
  ```
  =============================== warnings summary ===============================
  .venv/lib/python3.12/site-packages/starlette/testclient.py:40
    /home/eimi/projects/magic-tower/backend/.venv/lib/python3.12/site-packages/starlette/testclient.py:40: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
      _PortalFactoryType = typing.Callable[[], typing.ContextManager[anyio.abc.BlockingPortal]]
  
  -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
  112 deselected, 1 warning in 0.27s
  ```
- AC10: **FAIL** — `cd backend && uv run pytest tests -q -k "promote_endpoint or dismiss_endpoint"`
  ```
  =============================== warnings summary ===============================
  .venv/lib/python3.12/site-packages/starlette/testclient.py:40
    /home/eimi/projects/magic-tower/backend/.venv/lib/python3.12/site-packages/starlette/testclient.py:40: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
      _PortalFactoryType = typing.Callable[[], typing.ContextManager[anyio.abc.BlockingPortal]]
  
  -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
  112 deselected, 1 warning in 0.27s
  ```
- AC11: pass — `cd backend && uv run python -m app.tools.heuristic_eval --sample "${MAGIC_TOWER_SAMPLE:-$HOME/.magic-tower/labeled-sample.json}"`
- AC12: pass — `cd frontend && npm run test -- --run`
- AC13: pass — `cd frontend && npm run test -- --run -t "triage"`
- AC14: **FAIL** — `cd backend && uv run pytest tests -q -k sync_populates_api`
  ```
  =============================== warnings summary ===============================
  .venv/lib/python3.12/site-packages/starlette/testclient.py:40
    /home/eimi/projects/magic-tower/backend/.venv/lib/python3.12/site-packages/starlette/testclient.py:40: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
      _PortalFactoryType = typing.Callable[[], typing.ContextManager[anyio.abc.BlockingPortal]]
  
  -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
  112 deselected, 1 warning in 0.26s
  ```
- AC15: **FAIL** — `test "$(gh run list --branch "$(git rev-parse --abbrev-ref HEAD)" --limit 1 --json headSha,conclusion -q '.[0].headSha+":"+.[0].conclusion')" = "$(git rev-parse HEAD):success"`

## Dead code

- dead-code count 3 (baseline 4)

## Transcript scan

- `rm -f tests/test_zzrepro_tmp.py` in T06-1-0.jsonl: …rm -f tests/test_zzrepro_tmp.py /tmp/t06_repro.py && cd /home/eimi/projects/magic-tower && git reset -q --hard 2014c367bf393e703385b8ef5c16adc2b16750a3 && git l…
- `rm -f tests/test_zzrepro_tmp.py` in T06-1-0.jsonl: …rm -f tests/test_zzrepro_tmp.py /tmp/t06_repro.py && ls tests/ | grep -c zzrepro || echo "temp repro removed"…
- `rm -f backend/tests/test_zz_manager_probe.py` in T06-2-0.jsonl: …cd /home/eimi/projects/magic-tower && rm -f backend/tests/test_zz_manager_probe.py && md5sum backend/app/services/promotion.py && cp backend/app/services/promot…
- `noqa` in backend/alembic/env.py:23: …from app import models  # noqa: F401…

## Not verified (residuals)

- untracked files left in the tree (leftovers or tool artifacts?): .claude/
