# Contract — Jira as a tracked source, scoped to what you touched

Approved: 2026-09-19 · Sealed by `.companion/contract.sha256`.
Changing this file after approval requires `/companion:contract` again; `companion build` refuses otherwise.

## Result
Jira issues you are involved in appear in the queue alongside your mail, with real status, priority
and assignee — and the same ticket stops appearing twice once its notification mail is superseded.
Issues assigned to you become work items; ones you merely watch, reported or voted on are stored and
browsable but never clutter the actionable queue. A named project can be made fully visible for
management without flooding anything. Cleanup stops depending on memory: worktrees, stray processes
and temp files become a checkable gate.

## Non-goals
- Comment-authorship participation. Jira Cloud has no `commentedBy`, `comment ~ currentUser()` is
  invalid, and `issueFunction in commented(...)` needs ScriptRunner — a paid, admin-installed app.
  Recorded as a known gap; revisit only if comment-only threads are actually missed.
- Scoped API tokens and `cloudId` discovery. The owner has a **classic** token, so Basic auth
  against `https://<site>.atlassian.net`.
- Writing to Jira. Read-only: no transitions, comments or assignment changes.
- Freshservice, and any further connector.
- Rendering ADF richly. Description text is extracted plainly; no ADF-to-markdown fidelity work.
- LLM grouping or summarisation of issues.

## Environment facts
- test: `cd backend && uv run pytest tests ../tests/agent_protocol -q`
  — **runs today: 258 passed in 51.6s.** Frontend: `cd frontend && npm run test -- --run`
  — **23 passed in 4 files.**
- run: `WEB_PORT=8790 docker compose up -d --wait api && docker compose down`
  — **verified working today** (T16). Port 8787 is occupied on this machine, hence `WEB_PORT`.
- lint: none — no ruff/black/flake8/mypy configured.
- dead-code: `bash scripts/deadcode.sh`
  — **measured 9 at sealing** (vulture 3, knip 1, css 1, docs 4), while `.companion/deadcode.baseline`
  reads a stale 6. The four doc findings are two real missing files, each cited twice: the
  leave-no-trace script (promised in `.companion/plan.md` and again in this contract) and a frontend
  gitignore (claimed in `.companion/progress.md` and again here). **Naming a missing file in a
  contract creates two more findings** — an honest quirk of a checker that scans `.companion/*.md`,
  not a reason to write the paths evasively. T01 and T02 take the count down; AC5 pins it at or
  below whatever baseline is then true.
- Python 3.12 + uv; Node 22. `httpx` is **dev-only** (`backend/pyproject.toml:29`); the Graph client
  uses stdlib `urllib.request` with an injectable transport (`backend/app/integrations/graph.py:11,31`).
- The test command must run from `backend/` — `env_file=".env"` is cwd-relative.
- Env var names the connector needs (names only): `JIRA_SITE_URL`, `JIRA_ACCOUNT_EMAIL`,
  `JIRA_API_TOKEN`, and a project key setting for management visibility. Each must be listed in
  `_BLANKABLE_OPTIONAL_FIELDS` (`backend/app/config.py:13-20`) **and** the duplicated list in
  `backend/tests/test_config.py:22-29`, or a blank `.env` line reads as `SecretStr("")` not `None`.
- `source_kind` is `VARCHAR(13)` with no CHECK, so adding `jira` needs **no Alembic revision**.
  But `scripts/deaddocs_check.py:50-60` treats a kind spelled in a migration yet absent from
  `SourceKind` as a *retired* connector — spell `jira` identically in enum, code and docs.
- `alembic/versions/0001_initial_schema.py:31` pins the `sources` column set and
  `backend/tests/test_migrations.py:247` fails on any addition: per-source scope must live in a side
  table or configuration, never a new `sources` column.

## Acceptance criteria
- AC1: Whole backend suite green, including every new test.
  - verify: `cd backend && uv run pytest tests ../tests/agent_protocol -q`
- AC2: Frontend tests green.
  - verify: `cd frontend && npm run test -- --run`
- AC3: A full build leaves the tree clean.
  - verify: `cd frontend && npm run build >/dev/null 2>&1; cd .. && test -z "$(git status --porcelain)"`
- AC4: Cleanup is checkable — stray worktrees, agent branches, project temp files and repo-owned
  processes are counted, and the script proves each category actually runs.
  - verify: `bash scripts/leave-no-trace.sh && cd backend && uv run pytest tests -q -k leave_no_trace`
- AC5: The dead-code gate is at or below its recorded baseline, and the recorded baseline is true.
  - verify: `test "$(bash scripts/deadcode.sh | tail -1)" -le "$(cat .companion/deadcode.baseline)"`
- AC6: A Jira issue the owner is involved in becomes a `Source`, fetched over the HTTP API with an
  injectable transport and no network in tests.
  - verify: `cd backend && uv run pytest tests -q -k jira_sync`
- AC7: Only issues assigned to the owner are promoted; watcher, voter, reporter and creator
  involvement is stored and browsable but never promoted.
  - verify: `cd backend && uv run pytest tests -q -k jira_promotion`
- AC8: The participation query is the five-clause JQL, bounded and cursor-paged, and requests its
  fields explicitly — `fields` defaults to `id` alone.
  - verify: `cd backend && uv run pytest tests -q -k jira_query`
- AC9: The same issue arriving as notification mail and over the API yields one work item, and the
  mail-first ordering keeps the item visible while the API replaces it.
  - verify: `cd backend && uv run pytest tests -q -k jira_dedupe`
- AC10: A named project can be synced browse-only — its issues are never promoted.
  - verify: `cd backend && uv run pytest tests -q -k jira_project_visibility`
- AC11: `POST /api/sync` accepts an optional source kind and still defaults to Graph.
  - verify: `cd backend && uv run pytest tests -q -k sync_kind_parameter`
- AC12: Missing or blank Jira settings fail closed with named env vars, never a stack trace.
  - verify: `cd backend && uv run pytest tests -q -k jira_configuration`
- AC13: The GUI shows Jira items with a working source filter.
  - verify: `cd frontend && npx vitest run -t "jira" --reporter=json --outputFile=../.companion/scratch/ac13.json >/dev/null 2>&1; python3 -c "import json,sys; d=json.load(open('../.companion/scratch/ac13.json')); sys.exit(0 if d.get('numPassedTests',0)>=2 and d.get('numFailedTests',0)==0 else 1)"`
- AC14: The documented run command starts the stack.
  - verify: `WEB_PORT=8790 docker compose up -d --wait api && docker compose exec -T api python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/health').status==200 else 1)" && docker compose down`
- AC15: CI is green for the exact commit at HEAD.
  - verify: `test "$(gh run list --branch "$(git rev-parse --abbrev-ref HEAD)" --limit 1 --json headSha,conclusion -q '.[0].headSha+":"+.[0].conclusion')" = "$(git rev-parse HEAD):success"`
- AC16: The connector is proven against the owner's real Jira, not only fixtures.
  - verify: manual — it needs the owner's site URL, email and API token, which are not on this
    machine and must not be. The contract ships a documented command the owner runs; no local
    command can substitute for real credentials.

## Quality bar
- Tests first; every behaviour change has a test that fails without it. Each Jira rule must be
  falsifiable individually — stub its input, confirm the suite reddens.
- No network in tests: the Jira client takes an injectable transport like
  `backend/app/integrations/graph.py:31`.
- Secrets never enter the repository: names in `.env.example`, values only in `.env`.
- Spell `jira` identically in the enum, code, settings and docs, or the dead-docs checker marks the
  connector retired.
- No dead code above baseline, no debug output, no unrelated formatting churn.
- Every worktree, process and temp file created during a task is gone when that task reports done.
- **Nothing writes scratch to `/tmp`.** Gate and test output goes to `.companion/scratch/`, which is
  git-excluded. This environment denies the build loop permission to remove `/tmp` entries, so a
  `/tmp` file it creates can never be cleared by it. The cleanup gate keeps `/tmp` **fatal** (owner,
  2026-09-20); the fix is to stop writing there, not to soften the check.

## Playbook checks applied
- Verify lines run through `verifyCommands()` before sealing — done; results below.
- `dead-code:` command with a measured baseline — done: measured **7**, and the stale 6 in
  `.companion/deadcode.baseline` is corrected by this contract's first task rather than assumed.
- Push to prove CI rather than `verify: manual` — done: AC15 is a real command.
- Out-of-scope findings to `.companion/backlog.md` — comment-authorship participation, scoped
  tokens, ADF fidelity and Freshservice are recorded there, not dropped.
- Revertibility checked per task for the vacuity probe — T01 (script) and T02 (baseline) are
  config/script-shaped; the manager must falsify those by hand.
- `run:` command started before sealing — done: `docker compose up -d --wait api` verified today.
- A criterion that can pass by skipping is named — AC16 is explicitly manual and says why; AC13
  asserts a passing-test count because `-t` exits 0 on zero matches.
- Scratchpad not `/tmp`, stop every process, remove worktrees — enforced by AC4 rather than memory.
