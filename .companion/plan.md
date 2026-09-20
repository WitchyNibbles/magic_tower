# Plan — Jira as a tracked source

One task per `## Txx — title` heading. Statuses: `todo` → `doing` → `claimed` → `verified`,
or `blocked(<reason>)`. Only the manager edits this file.

## T01 — Make leave-no-trace checkable
- status: verified
- complexity: normal
- deps:
- done-when: `bash scripts/leave-no-trace.sh && cd backend && uv run pytest tests -q -k leave_no_trace`

Folded in from the cleanup retro at the owner's request. Cleanup was enforced by memory and was
forgotten all last run: 15 stale worktrees, 21 orphan branches, 224 project files in `/tmp`, a vite
dev server alive for hours, containers left up. Add `scripts/leave-no-trace.sh` reporting, and
exiting non-zero on, anything left behind: `git worktree list` entries beyond the main one,
`worktree-agent-*` branches, `/tmp` entries matching this project's task-file patterns, and running
processes whose command line points inside this repository. One labeled line per category, total on
the last line, matching `scripts/deadcode.sh`'s shape. Test it as the dead-code gate is tested:
create one artefact of each category, assert the count rises, remove it, assert it falls — the
script must not report zero because a category silently failed to run.
**Verified 2026-09-20.** The gate shipped in `9620c1c` and `2a4e23e` and is correct; it blocked
only on `/tmp/t2.json`, a stale report from the previous contract that the build loop is denied
permission to delete. I deleted it from this session, where that permission exists. Owner's policy:
`/tmp` stays **fatal** and gate output moves to `.companion/scratch/` — fix the cause, not the
check.
Probe note: script-shaped; falsify by hand, each category separately.

## T02 — Make the dead-code baseline true
- status: verified
- complexity: simple
- deps: T01
- done-when: `test "$(bash scripts/deadcode.sh | tail -1)" -le "$(cat .companion/deadcode.baseline)" && test "$(cat .companion/deadcode.baseline)" -lt 9`

`.companion/deadcode.baseline` reads 6 while the gate measures 9. Resolve the `frontend/.gitignore`
claim at `.companion/progress.md:92` — create the file if it is wanted, or correct the line if it is
not; do not delete accurate history to satisfy a checker. Then write the true total. T01 removes the
leave-no-trace findings; this task removes the rest and records what remains.
**Verified 2026-09-20.** Gate **7** (vulture 3, knip 1, css 1, docs 2), baseline **7**, both
clauses falsified individually. The `frontend/.gitignore` claim was resolved by *creating* the file:
`.companion/progress.md:92` is a dated record pinned to `bfcc54d`, where the absence was true, so
no accurate history was deleted. The two remaining docs findings are this plan's own citations of
the client module T04 will add and the setup guide T12 will ship — future deliverables, left cited
in their own task bodies on purpose. Each takes the gate down by one as it lands, so a later task
may lower the baseline but must never raise it. Spelling either path in backticks *here* costs a
finding per line, which is how this note first pushed the gate 7 to 9 before being rewritten.
Probe note: config-shaped; falsify by hand.

## T03 — Jira settings, failing closed
- status: verified
- complexity: simple
- deps:
- done-when: `cd backend && uv run pytest tests -q -k jira_configuration`

`JIRA_SITE_URL`, `JIRA_ACCOUNT_EMAIL`, `JIRA_API_TOKEN` and a management-project key, as optional
settings mirroring the Graph ones (`backend/app/config.py:31-39`). Each must be listed in
`_BLANKABLE_OPTIONAL_FIELDS` (`config.py:13-20`) **and** the duplicated list in
`backend/tests/test_config.py:22-29`, or a blank `.env` line reads as `SecretStr("")` not `None`.
Add `jira_configuration_errors()` mirroring `graph_configuration_errors()` (`config.py:90-102`),
returning env-var **names** only. Add the rows to `.env.example`. Values never enter the repo.

## T04 — Jira HTTP client
- status: verified
- complexity: normal
- deps: T03
- done-when: `cd backend && uv run pytest tests -q -k jira_client`

`backend/app/integrations/jira.py` mirroring the Graph client's shape: injectable transport
(`backend/app/integrations/graph.py:11,31`), GET-only guard, no network in tests. Classic API token
over Basic auth (`email:token`) against `https://<site>.atlassian.net` — **not** the scoped-token
host, which would 401. Handle 429 with `Retry-After`. `httpx` is dev-only today: either keep stdlib
`urllib.request` like Graph, or promote `httpx` to a runtime dependency and say which and why.
**Not a hard task — three sessions were killed at 600s.** The harness terminated each worker with
"Background tasks still running after 600s; terminating"; nothing was committed and no transcript
survived. The loop is now run with `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0`. Treat this as attempt 1.
**Verified 2026-09-20.** Attempt 1 (sonnet) shipped the client and 13 tests; the reviewer blocked
on a `search_issues` method the task never asked for, aimed at the search endpoint T05's body
records as removed, with a test pinning that path. The opus repair deleted the method and its
test and nothing else. Twelve tests remain, each reddened by a distinct mutation of mine with a
comment-only negative control green. Gate **3** against baseline 7 — but see the backlog: vulture
reads 0 only because the new classmethod reads `cls`, which suppresses three pre-existing false
positives in the settings module, so the drop is an artefact, not a cleanup.
Probe note: `backend/app/integrations/jira.py` is the one revertible implementation file; the
repair round is pure deletion, so falsify it by grepping the tree for the removed endpoint.

## T05 — The participation query
- status: todo
- complexity: normal
- deps: T04
- done-when: `cd backend && uv run pytest tests -q -k jira_query`

`GET|POST /rest/api/3/search/jql` — the old `/rest/api/3/search` is removed. The JQL is
`(assignee = currentUser() OR reporter = currentUser() OR creator = currentUser() OR
watcher = currentUser() OR voter = currentUser()) AND updated >= -15m ORDER BY updated DESC`,
which must be **bounded**. Cursor pagination via `nextPageToken`; there is no `total` and no
`startAt`; absent token means last page. **`fields` defaults to `id` alone** — request
summary, status, priority, assignee, reporter, updated, project explicitly. Descriptions come back
as ADF JSON: extract plain text, no fidelity work. The search index is eventually consistent, and
`updated` is relative to the token owner's Jira profile timezone, not UTC — `-15m` is safe, an
absolute watermark is not without conversion.

## T06 — Jira sync handler
- status: todo
- complexity: normal
- deps: T05
- done-when: `cd backend && uv run pytest tests -q -k jira_sync`

Add `jira` to `SourceKind` (`backend/app/models.py:33-35`) — **no Alembic revision**, the column is
`VARCHAR(13)` with no CHECK. Spell it identically everywhere or `scripts/deaddocs_check.py:50-60`
marks the connector retired and every "Jira" in the docs becomes dead documentation. Register via
`register_sync_handler("jira", handler)` (`backend/app/services/sync_registry.py:27`) and add the
one import that triggers registration (`backend/app/main.py:1-11`). The handler signature must
accept and ignore the Graph-only `client` kwarg (`backend/app/services/sync.py:79`) and return the
same envelope (`sync.py:63`). `external_id` follows the existing `"kind:{id}"` convention.

## T07 — Promote only what is assigned to you
- status: todo
- complexity: complex
- deps: T06
- done-when: `cd backend && uv run pytest tests -q -k jira_promotion`

Today a signal with no sender, headers or recipients passes every rule and promotes unconditionally
(`backend/app/services/promotion.py:158`). Owner's decision: an issue **assigned to the owner**
promotes; reporter, creator, watcher and voter involvement is stored and browsable but never
promoted — those are things being followed, not owed. Identifying "the owner" needs care: nothing
persists owner identity today, and Jira uses `accountId`, not email. Decide and document how the
owner is recognised. Each rule falsifiable on its own: stub its input, confirm the suite reddens.

## T08 — One ticket, not two
- status: todo
- complexity: complex
- deps: T07
- done-when: `cd backend && uv run pytest tests -q -k jira_dedupe`

Jira notification mail already promotes — `TICKET_SENDER_MARKERS` (`promotion.py:40`, `e10ca8f`,
part of the 55% → 94% recall jump). Without dedupe the same ticket lands twice under two
`external_id`s. Owner's decision on ordering: **mail promotes immediately, and the API replaces it**
when the poll catches up — nothing is invisible while waiting. Extract the issue key from
notification mail to match the two, carry over any dismissal so a dismissed ticket stays dismissed,
and keep evidence from both. Test both orderings: mail-then-API and API-then-mail.

## T09 — Browse a whole project without flooding the queue
- status: todo
- complexity: normal
- deps: T07
- done-when: `cd backend && uv run pytest tests -q -k jira_project_visibility`

A named project syncs browse-only: its issues become `Source` rows that are **never** promoted, so
management visibility cannot flood the actionable queue. Scope cannot be a `sources` column —
`0001_initial_schema.py:31` pins the set and `backend/tests/test_migrations.py:247` fails on any
addition; use the `SourceSignalContext` side table or configuration, and say which. An issue both
assigned to the owner and inside the visible project must still promote, once.

## T10 — Sync a chosen source
- status: todo
- complexity: normal
- deps: T06
- done-when: `cd backend && uv run pytest tests -q -k sync_kind_parameter`

`POST /api/sync` passes no kind (`backend/app/api/sync.py:21-23`), so the registry is reachable only
from Python. Add an optional kind parameter defaulting to today's Graph behaviour, so nothing
breaks. An unknown kind must fail cleanly, not 500 — `UnknownSourceKindError` already exists
(`sync_registry.py:35-39`). Update the CLI choices, which are hand-written in two places
(`scripts/pending-work:139,146`) and pinned by `tests/agent_protocol/test_pending_work_cli.py:103`.

## T11 — Jira in the GUI
- status: todo
- complexity: normal
- deps: T10
- done-when: `cd frontend && npx vitest run -t "jira" --reporter=json --outputFile=../.companion/scratch/t11.json >/dev/null 2>&1; python3 -c "import json,sys; d=json.load(open('.companion/scratch/t11.json')); sys.exit(0 if d.get('numPassedTests',0)>=2 and d.get('numFailedTests',0)==0 else 1)"`

The frontend is exhaustive on the source union: `frontend/src/api.ts:2`, the `Record<SourceKind,…>`
labels (`frontend/src/lib/work-items.ts:7`) and the hardcoded filter list
(`frontend/src/components/mail-nav.tsx:8`). Add Jira to all three, show the issue key and link back
to the browse URL, and make the source filter select Jira items. Gate note: `-t` exits 0 on zero
matches, hence the counted assertion above.

## T12 — Prove it against the owner's real Jira
- status: todo
- complexity: normal
- deps: T08, T09, T11, T02
- done-when: `cd backend && uv run pytest tests ../tests/agent_protocol -q && cd ../frontend && npm run test -- --run && cd .. && test "$(gh run list --branch "$(git rev-parse --abbrev-ref HEAD)" --limit 1 --json headSha,conclusion -q '.[0].headSha+":"+.[0].conclusion')" = "$(git rev-parse HEAD):success"`

AC16 is manual by necessity: the owner's site URL, email and API token are not on this machine and
must not be. Ship `docs/jira-setup.md` — where to create a classic API token, which env vars to set,
how to run a first sync, and what a healthy result looks like — and a command the owner runs that
reports what came back without printing the token. Confirm every command in it runs as written up to
the point real credentials are required. Then push so CI runs on this exact commit.
