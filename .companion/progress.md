2026-09-17 — contract sealed (2ca56e84), 6 tasks todo, next: T01 commit the uv migration

## 2026-09-17T19:15:24Z · T01 · verified
- attempt: 2 · model: opus · reviewer: fable (opus authored the repair, so the reviewer must differ)
- commits: 418eba1
- commands: done-when → exit 0; test → exit 0 (18 passed, main tree); probe: RED
- review: approve
- notes: attempt 1 (sonnet, ed8f246) rejected by manager — the harness creates agent worktrees from `main` (05bc7f3), not from HEAD, so its branch was not fast-forwardable and its diff deleted all of `.companion/`. Repair worker reset onto base first. Adding `[build-system]` (setuptools, per egg-info `top_level.txt = app`) made the project non-virtual, so `uv.lock` had to be regenerated — the committed lock supersedes the copy that was untracked in the primary tree; T02 must take pyproject/lock from git, not re-copy. Suite is green in the main tree only because untracked `conftest.py` is still there; a fresh clone is still red (13 passed, 5 errors, `Engine(sqlite:////data/workboard.db)` at import) — that is T02's to close. `.claude/` worktree dir is untracked and not gitignored; out of T01 scope but it will dirty AC10.
