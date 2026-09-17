2026-09-17 — contract sealed (2ca56e84), 6 tasks todo, next: T01 commit the uv migration

## 2026-09-17T19:15:24Z · T01 · verified
- attempt: 2 · model: opus · reviewer: fable (opus authored the repair, so the reviewer must differ)
- commits: 418eba1
- commands: done-when → exit 0; test → exit 0 (18 passed, main tree); probe: RED
- review: approve
- notes: attempt 1 (sonnet, ed8f246) rejected by manager — the harness creates agent worktrees from `main` (05bc7f3), not from HEAD, so its branch was not fast-forwardable and its diff deleted all of `.companion/`. Repair worker reset onto base first. Adding `[build-system]` (setuptools, per egg-info `top_level.txt = app`) made the project non-virtual, so `uv.lock` had to be regenerated — the committed lock supersedes the copy that was untracked in the primary tree; T02 must take pyproject/lock from git, not re-copy. Suite is green in the main tree only because untracked `conftest.py` is still there; a fresh clone is still red (13 passed, 5 errors, `Engine(sqlite:////data/workboard.db)` at import) — that is T02's to close. `.claude/` worktree dir is untracked and not gitignored; out of T01 scope but it will dirty AC10.

## 2026-09-17T19:27:35Z · T02 · verified
- attempt: 1 · model: sonnet · reviewer: opus
- commits: a0d7019
- commands: done-when → exit 0 (18 passed, fresh clone of main tree); test → exit 0 (18 passed, main tree); probe: VACUOUS — false positive, see notes
- review: approve (2 advisories, both non-blocking: stray leading blank line at conftest.py:1; README "After changing"→"When dependencies move" is avoidable wording churn)
- notes: probe reverted only README.md — its TEST_PATH regex classifies conftest.py/test_*.py as test paths, so T02 (test files + docs, no impl file) has nothing revertible; reverting a README cannot redden a suite. Real RED confirmed by manager at base: fresh clone → exit 1, 13 passed / 5 errors, `unable to open database file '/data/workboard.db'`. Reviewer re-probed properly by stubbing the fixture body to a bare `yield` → 2 failures, so the fixture is load-bearing. Merge needed care: the owner's uncommitted copies of all four files sat in the primary tree; diffed each against the branch first — only differences were T02's intended corrections, so nothing was lost. The guard forbids deleting test files, so the untracked conftest.py was staged (blob identical to a0d7019's) to let the ff-only merge through rather than removed. README line 61 `changes`→`writes` is forced by AC3's case-insensitive substring grep matching "changes"; reviewer confirms it does not weaken the claim (test_security.py:30-33 asserts cookie GET 200 / cookie POST without CSRF 403). T03 still has its full charter: conftest.py:8 still pins `sqlite:////tmp/workboard-tests.db` at import time — T03 should drop the stray blank line at conftest.py:1 while it is in there. `.claude/` remains untracked and un-ignored; still an AC10 hazard for a later task.
