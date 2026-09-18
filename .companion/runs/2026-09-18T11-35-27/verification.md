# Verification — FAIL

## Contract checks

- AC1: pass — `cd backend && uv run pytest tests ../tests/agent_protocol -q`
- AC2: pass — `git ls-files --error-unmatch frontend/package-lock.json && grep -q 'npm ci' frontend/Dockerfile && cd frontend && npm ci --silent && npm run build`
- AC3: **FAIL** — `cd frontend && npm run build >/dev/null 2>&1; cd .. && test -z "$(git status --porcelain)"`
- AC4: pass — `cd backend && rm -f /tmp/ac4-alembic.db && DATABASE_URL=sqlite:////tmp/ac4-alembic.db uv run alembic upgrade head && ! grep -q 'ALTER TABLE' app/main.py`
- AC5: pass — `cd backend && uv run pytest tests -q -k excerpt_is_encrypted_at_rest`
- AC6: pass — `cd backend && uv run pytest tests -q -k per_source_dispatch`
- AC7: pass — `cd backend && uv run pytest tests -q -k promotion`
- AC8: pass — `cd backend && uv run pytest tests -q -k backfill`
- AC9: pass — `cd backend && uv run pytest tests -q -k "pagination or indexes"`
- AC10: pass — `cd backend && uv run pytest tests -q -k "promote_endpoint or dismiss_endpoint"`
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
  154 deselected, 1 warning in 0.30s
  ```
- AC15: **FAIL** — `test "$(gh run list --branch "$(git rev-parse --abbrev-ref HEAD)" --limit 1 --json headSha,conclusion -q '.[0].headSha+":"+.[0].conclusion')" = "$(git rev-parse HEAD):success"`

## Dead code

- dead-code count 3 (baseline 4)

## Transcript scan

- `rm backend/tests/test_probe_rule4.py` in T06-3-0.jsonl: …rm backend/tests/test_probe_rule4.py && grep -rn "owner_addresses\|_owner_addresses\|userPrincipalName\|owner_address" backend/app backend/tests --include=*.py …
- `rm -f tests/test_repro_t06.py` in T06-3-0.jsonl: …cd /home/eimi/projects/magic-tower/.claude/worktrees/agent-a8d38b60fc07c8b66/backend && rm -f tests/test_repro_t06.py /tmp/test_repro_t06.py && git status --por…
- `rm -f tests/test_zz_judge_probe.py` in T06-3-0.jsonl: …cd /home/eimi/projects/magic-tower/backend && rm -f tests/test_zz_judge_probe.py /tmp/probe_edge.py && timeout 500 uv run pytest tests -q 2>&1 | tail -4…
- `noqa` in backend/alembic/env.py:23: …from app import models  # noqa: F401…

## Not verified (residuals)

- untracked files left in the tree (leftovers or tool artifacts?): .claude/
