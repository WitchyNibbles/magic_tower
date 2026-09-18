# Verification — PASS

## Contract checks

- AC1: pass — `cd backend && uv run pytest tests ../tests/agent_protocol -q`
- AC2: pass — `git ls-files --error-unmatch frontend/package-lock.json && grep -q 'npm ci' frontend/Dockerfile && cd frontend && npm ci --silent && npm run build`
- AC3: pass — `cd frontend && npm run build >/dev/null 2>&1; cd .. && test -z "$(git status --porcelain)"`
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
- AC14: pass — `cd backend && uv run pytest tests -q -k sync_populates_api`
- AC15: pass — `test "$(gh run list --branch "$(git rev-parse --abbrev-ref HEAD)" --limit 1 --json headSha,conclusion -q '.[0].headSha+":"+.[0].conclusion')" = "$(git rev-parse HEAD):success"`

## Dead code

- dead-code count 3 (baseline 4)

## Transcript scan

- `noqa` in backend/alembic/env.py:23: …from app import models  # noqa: F401…

## Not verified (residuals)

- none
