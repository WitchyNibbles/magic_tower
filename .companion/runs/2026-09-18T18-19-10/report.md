# Report — a populated queue, and a GUI worth looking at · run 2026-09-18T18-19-10

## Result
`docker compose up` does not start: the api container exits 1 because the root `.env` sets the
`MICROSOFT_*` values to empty strings and the validator rejects `""` instead of treating it as
unset. Pre-existing bug, not caused by this contract — but it means the documented `run:` command
fails today. Run the two processes directly and everything works: a sync now creates work items
instead of dead `Source` rows, content is encrypted at rest, and the GUI groups them for triage.

## Verified live
All 15 run by me in this session, 0 manual.

| Criterion | Result |
|---|---|
| AC1 backend suite | pass — 168 passed in 29.6s |
| AC2 lockfile + `npm ci` build | pass — built in 242ms |
| AC3 clean tree after build | pass |
| AC4 Alembic chain, no startup DDL | pass — upgraded through `0007` |
| AC5 content encrypted at rest | pass — 1 passed |
| AC6 per-source dispatch | pass — 3 passed |
| AC7 promotion + idempotency | pass — 54 passed |
| AC8 backfill | pass — 14 passed |
| AC9 pagination + indexes | pass — 12 passed |
| AC10 promote/dismiss API | pass — 12 passed |
| AC11 heuristic eval | pass — **via its skip path**, see residuals |
| AC12 frontend tests | pass |
| AC13 triage view | pass |
| AC14 end-to-end sync → API | pass — 1 passed |
| AC15 CI green on HEAD | pass — `5b6dd25`, 3 jobs |

Dead code 3, baseline 4.

## Running
**GUI: http://127.0.0.1:5173** · **API: http://127.0.0.1:8000**

    cd backend && DATABASE_URL=sqlite:///./workboard.db LOCAL_API_TOKEN=present-token uv run uvicorn app.main:app --port 8000
    cd frontend && npm run dev -- --port 5173

Smoke-tested just now: `/api/health` → `{"status":"ok","service":"workboard-api"}`;
`/api/work-items` without a token → **401**; with the token → paginated envelope
`{"items":[],"total":0,"limit":2,"offset":0}`; POST a work item → created, list then
`total=1 items=1`. Stop with `pkill -f "uvicorn app.main:app"` and `pkill -f "vite"`.

## What was built
| Task | Model(s) | Review | Commit(s) |
|---|---|---|---|
| T01 reproducible frontend | sonnet | approve | `6e343ae` |
| T02 Alembic, column-aware stamp | opus ×2 | approve | `65d6020`, `027fdf2` |
| T03 encrypt content at rest | opus | approve | `636eb61` |
| T04 per-source dispatch | opus | approve | `e2ee8f9` |
| T05 promotion heuristic | opus ×2 | blocked once, then approve | `0dd793a`, `90dafc9` |
| T06 backfill | opus ×3 | blocked twice, then approve | `bbada43`, `cabef2d` |
| T07 indexes + pagination | opus | approve | `91583bd` |
| T08 promote/dismiss API | opus | approve | `5134f8f` |
| T09 heuristic eval | opus ×2 | blocked once, then approve | `8f72654`, `cc2a177` |
| T10 frontend test infra + shadcn | sonnet | approve | `ab5ec9b` |
| T11 three-pane layout + palette | sonnet | approve | `238d022` |
| T12 triage view + grouping | opus | approve | `5375ff1` and T12 commits |
| T13 GUI wiring | opus ×3 | blocked once, then approve | `2ca211f`, `d57d196`, `c903dfe` |
| T14 end-to-end + CI | opus | approve | `94dbc75` |
| T15 migration fixtures | opus | approve | `a8307cd`, `fa6d0bc` |

Four tasks blocked and were repaired: T05 (rules had no falsifiable coverage), T06 (backfill
silently reported 0 after any sync), T09 (documented export command failed on a fresh PC), T13
(promote resurrected "Load more" and duplicated a row). Each block was an owner decision.

## Blocked
| Task | Reason |
|---|---|
| — | none; all 15 verified |

## Not verified (residuals)
- **`docker compose up` fails.** api exits 1 on empty `MICROSOFT_*` in the root `.env`. The
  contract's `run:` command is therefore unproven end to end; the GUI was exercised via the dev
  server instead. AC7's fresh-clone `docker compose build` passes — building is not running.
- **AC11 passed through its skip path**, printing `no labeled sample at
  /home/eimi/.magic-tower/labeled-sample.json; nothing to evaluate`. The heuristic has **never been
  measured against real mail**. That is by design — this machine has no Outlook/Teams access — but
  precision and recall are unknown until the owner labels a sample on the second PC.
- **The promotion heuristic is unvalidated against reality.** It is proven against synthetic
  fixtures only. It will misclassify real mail in ways nobody here can predict.
- **The second-PC path is documented but never executed.** Export → label → eval has not been run
  on a machine with Graph access.
- Frontend dead code is counted by knip, but no tool checks dead CSS.
- Teams `Chat.Read` may need admin consent in the owner's tenant — untested.

## Transcript scan
Clean — no hack words found in this run's transcripts.

## Next
Give feedback, then `/companion:retro`.
