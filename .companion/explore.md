# Explore — Jira as a tracked source, scoped to what the owner touched

## Idea
Track Jira issues via the HTTP API. Default: only issues the owner participated in. On request:
full visibility into a named project, for management.

## Facts
- **The seam is already built.** A connector registers with one call —
  `register_sync_handler(kind, handler)` (`backend/app/services/sync_registry.py:27`); `sync()` only
  dispatches (`backend/app/services/sync.py:69-79`) and always calls
  `handler(settings, db=db, limit=limit, client=client)`, so a Jira handler must accept and ignore
  the Graph-only `client`. T04's fake-kind test proves the seam without surgery
  (`backend/tests/test_sync_dispatch.py:46-62`). Registration is import-triggered; nothing imports a
  Jira module today, so one explicit import must be added (`backend/app/main.py:1-11`).
- **No Alembic revision needed.** `source_kind` is plain `VARCHAR(13)` with no CHECK, so adding
  `jira` to `SourceKind` (`backend/app/models.py:33-35`) needs no DDL. T19's `0008` existed only
  because *removing* a kind orphans rows.
- **Promotion would promote every Jira issue.** Rules read `sender`, `sender_kind`, `headers`,
  `to_recipients` only (`backend/app/services/promotion.py:149-158`). With all absent,
  `_is_automated_sender(None)`=False, `_is_bulk_mail({})`=False, `_is_only_copied([])`=False →
  `should_promote` returns True unconditionally (`promotion.py:158`).
- **You already ingest Jira notification mail.** `TICKET_SENDER_MARKERS = ("jira", "atlassian",
  "freshservice")` (`promotion.py:40`, from `e10ca8f`, which took recall 55% → 94%). A direct API
  connector therefore risks **the same issue in the queue twice**, under two `external_id`s.
- **Scope cannot be a `sources` column.** `alembic/versions/0001_initial_schema.py:31` pins the
  column set and `backend/tests/test_migrations.py:247` fails on any addition, by design — the
  intended extension point is the `SourceSignalContext` side table (`models.py:85-88`). So
  participated-vs-project is a side table or configuration.
- **"Participated" is not one JQL field.** Stock user fields are `assignee`, `reporter`, `creator`,
  `watcher`, `voter`. **There is no `commentedBy`**, and `comment ~ currentUser()` is invalid
  (`comment` is TEXT, `currentUser()` is a USER function). Comment authorship needs ScriptRunner
  (`issueFunction in commented(...)`), a paid app requiring site-admin install. `worklogAuthor` is
  no longer documented on Cloud — treat as unsupported.
  Working JQL: `(assignee = currentUser() OR reporter = currentUser() OR creator = currentUser()
  OR watcher = currentUser() OR voter = currentUser()) AND updated >= -15m ORDER BY updated DESC`.
  `watcher = currentUser()` needs no extra permission when querying yourself.
- **Endpoint**: `GET|POST /rest/api/3/search/jql`. `/rest/api/3/search` is `deprecated: true`,
  "Endpoint currently removed" (CHANGE-2046). Cursor pagination via `nextPageToken`; **no `total`,
  no `startAt`**; absent token = last page. **`fields` defaults to `id` only** — fields must be
  requested explicitly. Counts come from `POST /rest/api/3/search/approximate-count`. JQL must be
  *bounded*. Scope `read:jira-work`.
- **Auth**: Basic `email:api_token`. Classic token → `https://<site>.atlassian.net/...`; **scoped**
  token → `https://api.atlassian.com/ex/jira/{cloudId}/...`, wrong host gives 401. `cloudId` from
  `/_edge/tenant_info`. No admin needed. Rate limits: 429 + `Retry-After`; the March 2026 points
  quota targets apps — "API token-based traffic … will continue to be governed by existing burst
  rate limits".
- **Descriptions are ADF JSON**, not text (Atlassian Document Format) — rendering to text is work.
- **Eventual consistency**: the search index lags seconds to minutes; `updated >= -15m` is safe,
  absolute watermarks must be converted to the token owner's Jira profile timezone, not UTC.
- **Credential**: `EncryptedTokenStore` hardcodes AAD `b"workboard-graph-v1"` twice
  (`services/crypto.py:34,42`), though `path` is per-instance. There is **no writer path** for a
  non-OAuth token, and `APP_ENCRYPTION_KEY` lives in the same `.env` a Jira token would
  (`config.py:36`) — so the store adds no secrecy for a never-refreshing token. Settings shape to
  copy: `_BLANKABLE_OPTIONAL_FIELDS` (`config.py:13-20`) plus a `jira_configuration_errors()`
  mirroring `graph_configuration_errors()` (`config.py:90-102`).
- **Surfaces a new kind touches**: enum, config, `.env.example:6-20`, CLI choices twice
  (`scripts/pending-work:139,146`, pinned by `tests/agent_protocol/test_pending_work_cli.py:103`),
  frontend union (`frontend/src/api.ts:2`), labels (`frontend/src/lib/work-items.ts:7`), filter
  (`frontend/src/components/mail-nav.tsx:8`).
- **`POST /api/sync` never passes `kind`** (`backend/app/api/sync.py:21-23`), so the registry is
  reachable only from Python today.
- **Gate drift**: `scripts/deadcode.sh` now measures **7** while `.companion/deadcode.baseline`
  reads **6**, and nothing in CI reads that file. Also, the dead-docs checker treats a kind spelled
  in a migration but absent from `SourceKind` as a *retired* connector
  (`scripts/deaddocs_check.py:50-60`) — so "jira" must be spelled identically everywhere or every
  "Jira" in the docs counts as dead documentation.
- **Scale**: `POST /api/sync` bounds `limit ≤ 100`; a project-wide query can return thousands.

## Options
| # | What | Pros | Cons | Effort |
|---|------|------|------|--------|
| A | **Five-clause participation JQL + polling connector** — assignee/reporter/creator/watcher/voter, `updated >= -15m`, cursor paging | Stock API, no admin, no plugin; matches the proven registry seam | Misses comment-only involvement; needs a promotion rule for header-less signals | M |
| B | **A + comment coverage** — widen to project issues, then fetch each issue's comments and match accountId | True participation | N+1 calls, burst limits, ADF parsing for every comment | L |
| C | **ScriptRunner `issueFunction in commented(...)`** | One query, exact | Paid app, site-admin install — you do not control that | L |
| D | **Stay on Jira notification mail** (status quo) | Zero code; already scored 94% recall | No issue state, no project visibility, no management mode | S |
| E | **Project-visibility mode as browse-only** — project issues become `Source` rows that are never promoted | Management view without flooding the queue | Second concept in the data model (browsable vs actionable) | M |

## Recommendation
**A, with E for the management mode.** Five-clause JQL is the only path with no admin dependency,
and it plugs into T04's registry without touching `sync()`. Keep project-wide issues browse-only so
management visibility cannot flood the actionable queue.

## Open questions
1. Classic API token (site URL) or scoped token (needs `cloudId`, different base URL)?
2. Must "participated" include comment authorship — the expensive 20% that needs a paid plugin?
3. Which project key(s) get management visibility, and should it include done/archived issues?
4. Jira issues already arrive as notification mail. Dedupe them, or keep both?

## Decisions (owner, 2026-09-19)
1. **Dedupe: API wins, suppress the mail.** When a notification mail is recognisably about an issue
   the API also returns, keep the API version — it carries real status, priority and assignee.
   Requires extracting the issue key from notification mail so the two can be matched, and a rule
   for the ordering race (mail may arrive before the next poll, or after).
2. **Promotion: assigned to me promotes.** Reporter, creator, watcher and voter involvement is
   stored and browsable but not promoted — those are things being followed, not owed. This is the
   Jira answer to the header-less-signal problem (`promotion.py:158` would otherwise promote all).
3. **Classic API token**, so Basic auth against `https://<site>.atlassian.net` and **no cloudId
   lookup**. Token lives in settings beside `MICROSOFT_CLIENT_SECRET`, listed in
   `_BLANKABLE_OPTIONAL_FIELDS`, with a `jira_configuration_errors()` mirroring the Graph one.
4. **Project mode: browse-only, never promoted.** Introduces a browsable-vs-actionable distinction;
   per the migration-test constraint it must live in a side table or configuration, never a new
   `sources` column.
5. Not doing: comment-authorship participation (needs ScriptRunner, a paid admin-installed app) —
   record as a known gap, revisit only if comment-only threads are actually being missed.

## Carried into the contract
- Correct `.companion/deadcode.baseline` (reads 6, measures 7) **before** sealing — playbook
  requires a measured baseline in the contract.
- Spell `jira` identically in the enum, any migration and the docs, or `scripts/deaddocs_check.py`
  marks the connector retired and every "Jira" mention becomes dead documentation.
- `POST /api/sync` passes no `kind` today; the contract must say how a Jira sync is triggered.
- The `run:` command must start the thing today; T23 (leave-no-trace) is still open in plan.md.
