# Playbook — questions to ask and checks to run at contract time
One line each. Read by /companion:contract and /companion:explore. Cap 40. Owner-approved only.

- Run every `verify:` command through `verifyCommands()` before sealing, never only by hand — a backticked command with trailing prose reaches bash as command substitution · origin: 2026-09-17T18-57-48 · 2026-09-17
- Contract must carry a `dead-code:` command with a measured baseline; "no tool installed" is not a reason to omit it (`uv run --with vulture … --min-confidence 80`) · origin: 2026-09-17T18-57-48 · 2026-09-17
- Before writing `verify: manual`, check `git remote -v` and `gh auth status` — if a push can prove the criterion, push · origin: 2026-09-17T18-57-48 · 2026-09-17
- Write every out-of-scope finding to `.companion/backlog.md` in the session it is found, not just into a run report · origin: 2026-09-17T18-57-48 · 2026-09-17
- Ask whether each task has a revertible impl file; test-only and docs-only tasks need hand falsification, the vacuity probe proves nothing for them · origin: 2026-09-17T18-57-48 · 2026-09-17
- Start the thing with the contract's `run:` command before sealing; if it does not start today, that is the first task, not a footnote · origin: 2026-09-18T18-19-10 · 2026-09-18
- The dead-code gate must cover every language in the repo plus CSS and documentation, not just the primary language · origin: 2026-09-18T18-19-10 · 2026-09-18
- If a verify command can pass through a skip or absent-input path, say so at contract time and name what would actually prove it · origin: 2026-09-18T18-19-10 · 2026-09-18
- Before using a name-filtered test command as a gate, check the runner's zero-match behaviour — vitest exits 0, pytest exits 5 · origin: 2026-09-18T18-19-10 · 2026-09-18
- When a criterion cannot be proven on this machine for lack of data or access, publish the branch and hand the owner an exact runnable sequence — never let it pass by skipping · origin: 2026-09-18T18-19-10 · 2026-09-18
