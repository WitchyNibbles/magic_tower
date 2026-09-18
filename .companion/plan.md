# Plan — a populated queue, and a GUI worth looking at

One task per `## Txx — title` heading. Statuses: `todo` → `doing` → `claimed` → `verified`,
or `blocked(<reason>)`. Only the manager edits this file.

## T01 — Make the frontend build reproducible
- status: verified
- complexity: simple
- deps:
- done-when: `git ls-files --error-unmatch frontend/package-lock.json && grep -q 'npm ci' frontend/Dockerfile && cd frontend && npm ci --silent && npm run build && cd .. && test -z "$(git status --porcelain)"`

Commit `frontend/package-lock.json`, pin the `"latest"` specifiers in `frontend/package.json:11-17`
to what the lockfile resolved, switch `frontend/Dockerfile:3-4` from `npm install` to `npm ci`, and
gitignore the tsc leftovers (`frontend/*.tsbuildinfo`, `frontend/vite.config.js`,
`frontend/vite.config.d.ts`). Closes backlog B6.
Probe note: config-only, no revertible impl file — falsify by hand (remove the lockfile, confirm
`npm ci` fails).

## T02 — Introduce Alembic
- status: verified
- complexity: complex
- deps:
- done-when: `cd backend && uv run pytest tests -q -k alembic_stamp && rm -f /tmp/t02.db && DATABASE_URL=sqlite:////tmp/t02.db uv run alembic upgrade head && ! grep -q 'ALTER TABLE' app/main.py`

Add `alembic` as a runtime dependency, scaffold `backend/alembic/` with `env.py` reading
`DATABASE_URL` from settings, and autogenerate an initial migration matching today's models. Remove
the hand-written `ALTER TABLE` and the `create_all` from startup (`backend/app/main.py:46`) — but
existing databases already have these tables, so the migration must be safe to stamp rather than
re-run. Tests must not regress: `backend/tests/conftest.py` currently builds schema via
`Base.metadata.create_all`, so decide and document whether tests migrate or keep `create_all`.
**Owner decision, 2026-09-18 — the stamp must be column-aware.** Attempt 1 keyed its skip-and-stamp
on table names only, so a pre-Alembic database holding all four tables with a drifted column set was
stamped `0001` and left broken: reproduced by dropping `priority`, after which `alembic upgrade head`
exits 0, `alembic_version='0001'`, the column is still missing and `GET /api/work-items` 500s with
`no such column: work_items.priority`. Before this task, startup's `ALTER TABLE` repaired that
automatically — a loud self-healing path must not become a silent stamp. Compare the real columns
against the model metadata before stamping and **refuse loudly** on any mismatch, naming the
offending table and column. Tests (`-k alembic_stamp`) must cover three cases: fresh database
migrates; matching legacy database stamps; drifted legacy database is refused with a non-zero exit
and a message naming the drift. Closes backlog B10; re-check B11's README/Dockerfile claims match
the behaviour that ships.
Probe note: scaffolding-shaped; falsify by hand, and falsify **each clause** of the compound
done-when separately — a RED on an `&&` chain only proves whichever clause short-circuited.

## T03 — Encrypt message content at rest
- status: verified
- complexity: complex
- deps: T02
- done-when: `cd backend && uv run pytest tests -q -k excerpt_is_encrypted_at_rest`

`Source.excerpt` holds up to 2000 chars of real mail and Teams content in plaintext
(`backend/app/services/graph.py:50`). Encrypt with the existing AES-GCM helper
(`backend/app/services/crypto.py:34`) under its **own AAD** — never reuse `b"workboard-graph-v1"`,
which belongs to the token store. Decrypt on read so the API and the GUI evidence blockquotes keep
working. Test first: persist a signal with a distinctive marker, assert the marker is absent from
the raw bytes of the database file. Ship the data migration as an Alembic revision (T02), including
rows written before this change.

## T04 — Dispatch sync per source kind
- status: verified
- complexity: normal
- deps: T03
- done-when: `cd backend && uv run pytest tests -q -k per_source_dispatch`

`sync()` is hardwired to Graph and asserts the connected Graph user id
(`backend/app/services/sync.py:35-50`). Introduce a registry keyed by `SourceKind` so another kind
registers without editing `sync()`. Prove it with a test that registers a fake kind and syncs it end
to end. Keep the Graph identity assertion for the Graph kind only. No new connector here.

## T05 — Promote actionable signals into work items
- status: verified
- complexity: complex
- deps: T04
- done-when: `cd backend && uv run pytest tests -q -k promotion`

The missing link: `persist_signals` writes only `Source` rows (`backend/app/services/graph.py:45`)
and nothing calls `create_work_item` (`backend/app/services/work_items.py:42`), so the queue is
empty after every sync. One named, unit-testable function holds the heuristic with its rules in a
docstring: promote signals addressed directly to the user, skip automated/newsletter senders and
bulk mail, carry the excerpt across as `WorkEvidence`. Synthetic fixtures must include a newsletter
that must NOT promote and a direct message that must. `source_external_id` is unique
(`backend/app/models.py:41`), so promoting twice must not raise or duplicate —
`test_promotion_is_idempotent` covers it.

**Blocked once, 2026-09-18 — the rules had no real coverage.** Attempt 1 shipped working promotion
code whose tests never exercised rules 1/2/4: the manager stubbed `_address`, `_addresses`,
`toRecipients` in the `$select`, and `_teams_sender_kind` each in turn, and all 87 tests stayed
green. Fix as the manager specified: add two rows plus one chat row to the `INBOX` fixture at
`backend/tests/test_promotion.py:357-371` and assert `new_work_items` stays 1. Before claiming this
task, stub each rule's input in turn and confirm the suite **reddens** for every one — a rule no
test can falsify is not implemented, it is decoration.

## T06 — Backfill the Sources already stored
- status: verified
- complexity: normal
- deps: T05
- done-when: `cd backend && uv run pytest tests -q -k backfill`

Promote `Source` rows written before T05 once, so the queue populates without waiting for a sync.
Re-running must be safe — run the backfill twice in the test and assert a stable count. Document
where it runs (startup vs explicit endpoint); if startup, it must not slow boot on an empty DB.
**Blocked twice; owner decision 2026-09-18 — record judgements in a new table.** A `Source` stores
no sender, headers or recipients, so "unpromoted" cannot distinguish *never judged* from *judged and
declined*, and no predicate over existing state can. Attempt 2's queue-level gate silently disabled
itself after the first promoting sync: two pre-T05 sources + one ordinary sync → backfill reports
`{"new_work_items": 0}`, indistinguishable from "nothing to do", and those rows are unreachable
forever. Fix: a migration adds a **judgements table** recording that `promote_signals` decided on a
source and what the verdict was; the backfill then promotes exactly the never-judged rows. A new
table is deliberately chosen over a column on `Source` — the manager verified empirically that
`0001`'s skip check is scoped to `BASELINE_COLUMNS.keys() & get_table_names()`, so an added table is
invisible to it while an added column is refused. Do not change T02 for this.
Must not report 0 silently: if anything cannot be judged, say so distinctly from "nothing to do".
Probe note: test-shaped; falsify by hand (stub the body, confirm the test reddens).

**Blocked twice, 2026-09-18 — both predicates were unsound, in opposite directions.** Attempt 1
selected every `Source` with no `WorkItem`, which has no time bound, so running the endpoint after a
normal sync re-promoted every newsletter the heuristic had just declined. Attempt 2 replaced it with
a queue-level gate — return 0 if any stored `Source` already has a work item — which fixed that but
silently disables the backfill forever after the first sync that promotes anything: the manager and
the reviewer independently reproduced two pre-T05 sources plus one ordinary sync leaving
`backfill → 0` with no recovery path and a `{"new_work_items": 0}` response indistinguishable from
"nothing to do". Nothing documents or enforces a backfill-before-sync ordering, so sync-first is the
default. A `Source` stores neither sender, headers nor recipients, so "unpromoted" can never by
itself distinguish *never judged* from *judged and declined* — the fix must record the judgement.
The design both reviewers converged on: a durable per-source marker (`source_promotions` table, or
`sources.promotion_checked_at`) written by `promote_signals` for **every** signal it decides, either
verdict; backfill selects sources with no marker and feeds them through `promote_signals` — reusing
the one named heuristic rather than calling `create_work_item` directly, which is a second promotion
path. This also fixes the declined-row resurrection behind a hand-deleted work item (B36). Do **not**
use a timestamp predicate such as `Source.created_at < min(WorkItem.created_at)`: `persist_signals`
commits sources before `promote_signals` writes items, so the first post-T05 sync's declined
newsletter would classify as pre-T05. **Prerequisite: B39** — adding a column to a baseline table
makes T02's `0001` drift check abort, because `test_migrations.py:135,164,178` build their legacy
database from today's models; adding a *table* is not affected (`0001`'s skip check is scoped to
`BASELINE_COLUMNS.keys()`), which is the cheaper route if B39 is not taken first.
**Revision numbering, 2026-09-18:** T09 shipped revision `0004` on `main`, so the preserved
`source_promotions` branch (also `0004`/`down_revision '0003'`) must be renumbered to `0005` on
rebase or `alembic heads` reports a duplicate revision identifier.
Two preserved branches, neither reviewed into `main`: `worktree-agent-aa02c3e50aa3ca413` (attempt 2,
the queue-level gate — its test fixtures and the `…declined_unpromoted` discriminator are worth
keeping) and `worktree-agent-a2af9b2b1c1e76c3e` (an interrupted session's `source_promotions` table
via revision `0004`, **unreviewed**, but verified green by the manager: 98 passed, `test_migrations`
7, `-k backfill` 11).

## T07 — Index and paginate the list endpoints
- status: verified
- complexity: normal
- deps: T06
- done-when: `cd backend && uv run pytest tests -q -k "pagination or indexes"`

`GET /api/work-items` and `/api/sources` return every row (`backend/app/api/routes.py:66`) and
`backend/app/models.py` has no `index=True` anywhere. Add indexes on the columns actually filtered
and sorted (status, source_kind, updated_at, and `Source.external_id` beyond its unique constraint
if the query plan needs it) via an Alembic revision. Return a consistent envelope —
items, total, limit, offset — with a sane default limit and a cap. This changes the shape
`frontend/src/api.ts:33` consumes; T13 adapts the GUI, so leave the frontend working or coordinate
via that task.

## T08 — Promote and dismiss from the API
- status: todo
- complexity: normal
- deps: T07
- done-when: `cd backend && uv run pytest tests -q -k "promote_endpoint or dismiss_endpoint"`

Endpoints to correct the heuristic by hand: promote a `Source` the rules missed, and dismiss a
`WorkItem` that should not have been promoted. Dismiss must not delete provenance — prefer a status
transition over a hard delete, and make a dismissed item stay dismissed across re-syncs and the
T06 backfill (otherwise the next run promotes it again). Both are cookie-writable, so they need the
CSRF path (`backend/app/security.py:106-109`).

**Carried from T07 (manager, 2026-09-18): close the AC9 gap here.**
`GET /api/work-items?assigned_agent=` filters on `WorkItem.assigned_agent`, which T07 left
unindexed — its enumeration named status/source_kind/updated_at only, so AC9's wording ("the
columns they filter and sort on are indexed") is literally unmet on that one column. Verified on a
migrated database: the count query plans as `SCAN work_items`. T07's revision `0006` has shipped by
now, so this needs `index=True` on `backend/app/models.py:44` plus its own revision, not an edit to
`0006`. Index any column this task's own filters add, too. Closes backlog B47.

## T09 — Measure the heuristic against real mail
- status: todo
- complexity: normal
- deps: T05
- done-when: `cd backend && uv run python -m app.tools.heuristic_eval --sample "${MAGIC_TOWER_SAMPLE:-$HOME/.magic-tower/labeled-sample.json}"`

**This machine has no Outlook/Teams access** (owner, 2026-09-18). The owner will clone the repo on
a second PC that does, and label *and tune* there — so everything needed must be committed and must
work from a fresh clone.

Ship two commands, both committed:
- an **export** that reads the local database after a sync and writes a sample file with the fields
  a human needs to judge each signal (subject and excerpt included — the owner chose full content,
  kept on that machine) plus an empty `label` field per row;
- an **eval** that replays a labeled sample through the heuristic and reports counts, precision,
  recall, and the misclassified rows by id so the rules can be tuned on the spot.

Constraints: the sample is real mail and **must never enter the repository** — default it to a
gitignored path (`~/.magic-tower/labeled-sample.json`), and `.gitignore` that path pattern inside
the repo too. Eval must run from the JSON file **alone** — no database, no Graph credentials — so it
works on either machine. It must **exit 0 with a clear message when the sample is absent**, so CI
and this PC stay green. Commit a small synthetic example as the schema reference. Document the exact
sequence for the second PC: set the five `MICROSOFT_*` settings plus `APP_ENCRYPTION_KEY`, sync,
export, label, eval, tune, commit rule changes.

**Blocked once, 2026-09-18 — shipped and merged, but one documented path still fails.** Commits
`8f72654` (attempt 1) and `cc2a177` (repair) are **kept on the branch, not reset away**: both
reviewers endorsed the design, the suite is 125 green, the done-when passes, and the dead-code gate
is 3 of 4. The export and eval commands, the `source_signal_context` table, revision `0004`, the
header allowlist and the tests are all verified. What fails is the `docker compose` half of the
second-PC sequence — README:133 tells the owner to `docker compose cp` into `~/.magic-tower/`, which
does not exist on a fresh machine, so the command exits 1 (`invalid output path`); README:137's
"0600 under a 0700 directory" is false there too, because the tool's `mkdir` runs inside the
container. Repair forward from `cc2a177`: (1) `mkdir -p -m 700 ~/.magic-tower` before the cp line;
(2) extend `backend/tests/test_documented_commands.py` to guard the compose path — it is blind to it
today, which is how a broken pasted command passed a docs test; (3) `heuristic_sample.py:86` needs
`read_text(encoding="utf-8")` or a cp1252 second PC throws `UnicodeDecodeError` on an accented
subject; (4) `heuristic_export.py:73` catches only `OperationalError`, so an unmigrated Postgres URL
still raises a raw `ProgrammingError`.
Note for T06: this task's carry-across **closes the data gap T06's block called permanent** —
`source_signal_context` now stores sender, sender_kind, to_recipients and the heuristic's headers.

**Repair forward from `cc2a177` — do not start over.** Both reviewers endorsed the design (the two
commands, `SourceSignalContext`, revision `0004`, the `persist_signals` carry-across, the header
allowlist and the tests); the block is one README line on one of two documented paths. Exact work,
in order: (1) add `mkdir -p -m 700 ~/.magic-tower` before the `docker compose cp` at `README:133` —
the export tool's `mkdir(mode=0o700)` runs *inside the container*, so the host directory is never
created and `README:137`'s "0600 file under a 0700 directory" claim is false on that path;
(2) make `backend/tests/test_documented_commands.py` actually guard the compose path — it cannot see
it today, which is how a docs test passed over a broken pasted command; (3) `heuristic_sample.py:86`
`path.read_text()` has no `encoding`, so a non-UTF-8 locale (Windows cp1252 is plausible on the
second PC) turns a subject containing `Á` into a `UnicodeDecodeError`; (4) `heuristic_export.py:73`
catches only `OperationalError`, so a non-SQLite URL at an unmigrated database raises a raw
`ProgrammingError` — low weight, SQLite-only today.

## T10 — Frontend test infrastructure and shadcn foundation
- status: verified
- complexity: normal
- deps: T01
- done-when: `cd frontend && npm run test -- --run`

There are no frontend tests today. Add vitest + @testing-library/react + jsdom, a `test` script,
and one real test of the existing app. In the same task add Tailwind and the shadcn CLI setup so
later tasks can copy components in. Pin every version — no `"latest"` — and keep `npm ci` green.

## T11 — Three-pane Mail layout with command palette
- status: verified
- complexity: complex
- deps: T10
- done-when: `cd frontend && npm run test -- --run -t "layout"`

Rebuild the shell on shadcn's Mail example: resizable list + detail panes, and `cmdk` for a command
palette. Replace `frontend/src/styles.css` rather than layering Tailwind over it, and leave no dead
CSS. Keep the existing behaviour that works — session/token handling (`frontend/src/api.ts:14`),
the demo-data fallback on 401/503 (`main.tsx:6-10,17`), and the dispatch clipboard copy.

## T12 — Triage view with grouping
- status: todo
- complexity: complex
- deps: T11, T08
- done-when: `cd frontend && npx vitest run -t "triage" --reporter=json --outputFile=/tmp/t12.json >/dev/null 2>&1; python3 -c "import json,sys; d=json.load(open('/tmp/t12.json')); sys.exit(0 if d.get('numPassedTests',0)>=3 and d.get('numFailedTests',0)==0 else 1)"`

Gate note: `npm run test -- -t <pattern>` **exits 0 when nothing matches** (verified: a bogus
pattern exits 0), so this done-when asserts a passing-test count via vitest's JSON reporter.
The view the owner actually wanted: promoted items grouped for triage (by source kind and thread —
deterministic grouping, no LLM). Tests assert that items group correctly, that an empty queue says
so instead of rendering blank, and that the group counts match the data.

## T13 — Wire pagination, promote and dismiss into the GUI
- status: todo
- complexity: normal
- deps: T12
- done-when: `cd frontend && npx vitest run -t "pagination|dismiss" --reporter=json --outputFile=/tmp/t13.json >/dev/null 2>&1; python3 -c "import json,sys; d=json.load(open('/tmp/t13.json')); sys.exit(0 if d.get('numPassedTests',0)>=3 and d.get('numFailedTests',0)==0 else 1)"`

Consume T07's envelope (items/total/limit/offset) instead of assuming a bare array
(`frontend/src/api.ts:33`), with load-more or pager controls. Wire T08's promote and dismiss,
including the CSRF header the write path requires. Tests assert the request carries the right
offset and that a dismissed item leaves the list.

## T14 — Prove it end to end and on CI
- status: todo
- complexity: normal
- deps: T13, T09
- done-when: `cd backend && uv run pytest tests -q -k sync_populates_api && test "$(gh run list --branch "$(git rev-parse --abbrev-ref HEAD)" --limit 1 --json headSha,conclusion -q '.[0].headSha+":"+.[0].conclusion')" = "$(git rev-parse HEAD):success"`

One backend test running a fixture sync through the whole path, asserting `GET /api/work-items`
returns promoted items with evidence. Extend `.github/workflows/ci.yml` to run the frontend tests
too — today it runs only pytest and the Docker build. Then push so CI runs on this exact commit;
a stale earlier run does not count.

## T15 — Build the migration tests from the frozen baseline
- status: todo
- complexity: normal
- deps: T02
- done-when: `cd backend && uv run pytest tests -q -k "alembic_stamp or migrations"`

`backend/tests/test_migrations.py:135,164,178` build their "legacy" database from **today's** models,
so `0001`'s frozen `BASELINE_COLUMNS` drift check refuses it the moment any migration adds a column
to a baseline table — the tests fail for a reason that has nothing to do with the behaviour under
test. This already shaped a design decision: T06 was pushed toward a new table partly because a
column was thought impossible. Rebuild those fixtures from the frozen baseline schema (the same
definition `0001` stamps against), so adding a column to a baseline table is testable rather than
structurally refused. Prove it: a test that adds a column via a later revision and still stamps and
upgrades a legacy database correctly. Owner asked for this as its own task rather than backlog
(2026-09-18).
