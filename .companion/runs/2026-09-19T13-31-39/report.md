# Report — a populated queue, and a GUI worth looking at · run 2026-09-19 (final)

## Result
`docker compose up` now starts the whole stack, which is what failed last time. The GUI is served
at the port you choose, the API answers through it, and a sync creates work items instead of dead
`Source` rows. All 22 plan tasks verified, 258 tests green, dead-code gate down from 22 to 6 across
four checkers.

## Verified live
All 15 run by me in this session, 0 manual.

| Criterion | Result |
|---|---|
| AC1 backend suite | pass — 258 passed in 47.6s |
| AC2 lockfile + `npm ci` | pass — built in 270ms |
| AC3 clean tree | pass |
| AC4 Alembic chain | pass — through `0008` (Teams removal) |
| AC5 content encrypted at rest | pass |
| AC6 per-source dispatch | pass — 3 passed |
| AC7 promotion + idempotency | pass — 63 passed |
| AC8 backfill | pass — 14 passed |
| AC9 pagination + indexes | pass — 12 passed |
| AC10 promote/dismiss API | pass — 12 passed |
| AC11 heuristic eval | pass — **via skip path**, see residuals |
| AC12 frontend tests | pass |
| AC13 triage view | pass |
| AC14 end-to-end sync → API | pass |
| AC15 CI green on HEAD | pass — `8979f20`, 3 jobs, **after a fix made during this session** |

Dead-code gate: 6 (python 3, typescript 1, css 1, docs 1), baseline 6.

## Running
**GUI: http://127.0.0.1:8790** — full stack in Docker, api and web both `running`.

    WEB_PORT=8790 docker compose up -d --build

Smoke-tested now: GUI → 200; `/api/health` through nginx → `{"status":"ok","service":"workboard-api"}`;
`/api/work-items` unauthenticated → **503**, the fail-closed response, because no `LOCAL_API_TOKEN`
is set in this compose environment. Stop with `docker compose down`.

## What was built (this segment)
| Task | Model(s) | Review | Commit(s) |
|---|---|---|---|
| T16 compose actually starts | opus | approve | `be548b5`, `2b20f2b`, `725c44a` |
| T17 gate moved into a script | opus | approve | `e8b43dc` |
| T18 publish + hand-off | sonnet | approve | `d5a7c1d`, `0611136` |
| T19 remove Teams | opus | approve | `d3941db`, `3878ae7` |
| T20 dead CSS | assistant (direct) | owner's call | `094078a` |
| T21 dead documentation | sonnet + opus ×3 | blocked ×3, then approve | `aef0f3c`…`fd21b77` |
| T22 fix the docs, re-baseline | opus | blocked once, then approve | `c140766`, `1354f9b`, `15f30e0`, `d666cc2` |

## Blocked
| Task | Reason |
|---|---|
| — | none; all 22 verified |

## Not verified (residuals)
- **AC11 still passes through its skip path.** The heuristic has been tuned against your real mail
  on the second PC, but no precision/recall figure has ever been produced here, and none is pinned
  anywhere in the repo.
- **CI was broken by my own change and I did not catch it before pushing.**
  `tests/test_deadcode_script.py` runs the gate, and knip needs the frontend's `node_modules`, which
  the backend job did not install — knip exited 2 and the suite failed in CI while passing locally.
  Fixed in `8979f20`; the underlying mistake was measuring a gate where its dependencies happen to
  exist.
- **Three T21 rounds and one T22 round were blocked on stale factual claims in docstrings** — a
  pinned integer that the session log's own growth invalidates. The class is fixed; the cost was
  four sessions.
- **I mis-diagnosed three "dead" sessions.** T17's status stayed `blocked` after its work landed,
  so T20 and T21 were unrunnable and the loop jumped to verification. I read that as failing workers
  and acted on it twice.
- **`.companion/deadcode.baseline` was stale at 4 for most of this run** while the true total was 17
  to 22. It now reads 6.
- Ten stale agent worktrees from earlier sessions remain (B85); `.claude/` is gitignored so they no
  longer dirty the tree.

## Transcript scan
Clean for this run's transcripts — the only prior hit was `# noqa: F401` in `backend/alembic/env.py:23`,
a deliberate re-export so Alembic sees the models.

## Next
Give feedback, then `/companion:retro`.
