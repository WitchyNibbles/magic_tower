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
- status: todo
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

## T06 — Backfill the Sources already stored
- status: todo
- complexity: normal
- deps: T05
- done-when: `cd backend && uv run pytest tests -q -k backfill`

Promote `Source` rows written before T05 once, so the queue populates without waiting for a sync.
Re-running must be safe — run the backfill twice in the test and assert a stable count. Document
where it runs (startup vs explicit endpoint); if startup, it must not slow boot on an empty DB.
Probe note: test-shaped; falsify by hand (stub the body, confirm the test reddens).

## T07 — Index and paginate the list endpoints
- status: todo
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

## T09 — Measure the heuristic against real mail
- status: todo
- complexity: normal
- deps: T05
- done-when: `cd backend && uv run python -m app.tools.heuristic_eval --sample "${MAGIC_TOWER_SAMPLE:-$HOME/.magic-tower/labeled-sample.json}"`

A command that replays a labeled sample through the heuristic and reports precision and recall.
The sample is the owner's real mail and **must never enter the repository** — read it from a
gitignored local path, default `~/.magic-tower/labeled-sample.json`, and **exit 0 with a clear
message when the file is absent** so CI and other machines pass. Ship a documented sample schema
plus a small synthetic example committed in its place, and document how the owner exports and
labels theirs. Report counts, precision, recall, and list the misclassified items so the rules can
be tuned.

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
