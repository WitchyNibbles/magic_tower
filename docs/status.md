# Status

Snapshot of 2026-10-24, taken from `main` at `4a423dd`. Things will drift from here: check `git log` and the CI badge before trusting a line.

## What it does today

Magic Tower is a local task queue. It reads your Outlook inbox (Microsoft Graph) and your Jira Cloud issues, keeps the ones a fixed rule set calls "work" as review items with their evidence, and shows them in a React UI on `127.0.0.1:8787`. Local agent clients can read the queue and post proposals and dispatch records through a loopback API guarded by `LOCAL_API_TOKEN`. It never writes to Microsoft 365 or Jira.

## What works end to end

Proven by the test suite and CI, with fake or stubbed Graph and Jira:

- Local UI sign-in with `LOCAL_API_TOKEN`, an HttpOnly session kept in SQLite, and CSRF on writes.
- Outlook connector: PKCE sign-in, token refresh, paging, 429/503 backoff, encrypted token store and excerpts.
- Jira connector: participation search (assigned, reported, created, watched, voted; issues updated in the last 15 minutes only), an optional browse-only management project, dedupe, and promotion of issues assigned to you.
- Promotion rules, the backfill endpoint, review queue actions (filter, update, dismiss, promote, hand off).
- Alembic migrations, also on a database that predates Alembic.
- `docker compose build` (CI job `build`).

Never run against real accounts:

- A Microsoft sign-in and sync against a real tenant (`docs/second-pc.md`, step 4).
- A Jira check or sync against a real site (`docs/jira-setup.md`, "What actually needs real credentials").
- The promotion heuristic scored on real mail (precision and recall are still unknown).

## Gaps before daily use

Ranked by how much they block real daily use at work (Jira Cloud, Freshservice, Outlook only through IT).

1. **Jira sync only sees the last 15 minutes, and nothing syncs on a schedule.** The participation search ends in `updated >= -15m` (`backend/app/integrations/jira.py`), and no scheduler exists. A manual sync once a day therefore misses almost every issue. Only the optional management project is read without a time window. This needs a fix before Jira is usable: a stored watermark or a wider first-sync window, plus a periodic sync.
2. **The UI can't sync Jira or show why a sync failed.** The sync button calls `POST /api/sync` with the default `kind` (Outlook). Jira syncs only through `curl ... /api/sync?kind=jira`. Every error, including a useful 409 such as "Jira is not configured", becomes the same "Sync could not be completed." toast.
3. **No Freshservice connector.** See [Freshservice](#freshservice) below for what it would take.
4. **Outlook needs IT.** Outlook needs an Entra app registration, which a user without the Application Developer role can't create (`docs/work-setup.md`, step 5). Once connected, each sync reads only the newest 50 messages in the Inbox folder, so mail that rules file elsewhere is missed.
5. **Image builds can't trust a company root CA.** The Dockerfiles have no hook for an extra CA, so behind TLS inspection `docker compose build` fails at `npm ci` or `uv sync`. The no-Docker dev loop still works.
6. **Agent handoff has no client.** "Use Codex" and "Use Claude Code" store an `AgentDispatchRequest`, and nothing in the repo consumes it: the pending-work CLI (under scripts/) and its plugins were removed in PR #1 (they survive on `tooling-archive`). An agent can still call the API with `curl`.
7. **Some sync failures are a bare 500.** A Jira or Graph error that isn't a `SyncError` escapes `POST /api/sync` as `500`, with the reason only in `docker compose logs api`.
8. **Unmeasured heuristic.** Until a labeled sample of real mail is scored, nobody knows how much real work the rules miss or how much noise they let through. This needs Outlook.
9. **Jira Cloud only.** Basic auth over `email:classic-token`, and the Cloud-only `/rest/api/3/search/jql` endpoint. Fine for a Cloud site; Server or Data Center would need new code.

### Freshservice

A connector would follow the Jira shape:

- a read-only GET client for `https://<domain>.freshservice.com/api/v2`, with Basic auth (the agent's own API key as username, any dummy password);
- a sync handler registered in `backend/app/services/sync_registry.py`, a promotion rule (tickets where `agent_id` is you), and three settings;
- a `freshservice` source kind in `backend/app/models.py` (no migration: the kind columns are `VARCHAR(13)` with no CHECK, and `freshservice` is 12 characters), plus the frontend source union;
- a connectivity check like `jira_check`.

Useful API facts: `GET /api/v2/tickets/filter?query="agent_id:<id>"`, `updated_since` on the list endpoint (it otherwise returns only the last 30 days), `per_page` up to 100, and per-minute rate limits by plan with `Retry-After` on 429. Jira's connector is about 700 lines of backend code plus tests (`integrations/jira.py`, `services/jira_sync.py`, `services/jira_dedupe.py`, `tools/jira_check.py`). Freshservice can skip the dedupe part, so expect roughly 1 to 2 days of agent work with tests. It stays read-only: nothing is ever written back to Freshservice.

## Repo housekeeping

- Open PRs: none. Issues: none. PRs #1 and #2 are merged (squashed).
- CI: green on `main` (run 38132088850, 2026-10-11). Jobs: backend pytest, frontend vitest, compose build.
- Remote branches besides `main`: `devgod/run_21fb794e4cf5432aac6836c64fdea769` and `polish/utc-readme-screenshot` are superseded (their work is in `main` through PRs #1 and #2). `tooling-archive` is kept on purpose as the archive of removed agent tooling.
- Optional cleanups still open: a `useWorkQueue` hook for `frontend/src/App.tsx`; removing the build-gate scripts `scripts/deadcode.sh`, `scripts/deaddocs_check.py`, `scripts/leave-no-trace.sh` and their tests; ignoring the design hook's untracked .impeccable cache in frontend/.
- Doc drift: `docs/architecture.md` draws only Graph, not Jira. `docs/agent-protocol.md` says the repo ships only the API side, but its dispatch section still reads as if an installed client exists.

## Test results

Run on the dev PC (WSL2, no working Docker) from a fresh worktree of `main`:

- `frontend: npm run test -- --run` → `Tests  25 passed (25)`
- `frontend: npm run build` → `✓ built in 592ms` (includes `tsc -b`)
- `backend: uv run pytest` → `3 failed, 400 passed, 1 warning in 115.65s`. The 3 failures are `test_docker_compose.py::test_web_port_*`: they shell out to `docker compose config`, and this PC has no working Docker. They pass in CI.
- API smoke run with throwaway config and no Graph or Jira credentials (`alembic upgrade head` to `0010`, then `uvicorn`): `/api/health` 200, `/api/sync/status` 200 (`configured: false`), `POST /api/sync` without a token 401, with a token 409 `Microsoft Graph is not configured`, `?kind=jira` 409 `Jira is not configured: ...`, `/api/work-items` 200 with an empty list.

Not checked here: `docker compose up` (no Docker on this PC; CI only builds the images), and anything against a real tenant or Jira site.
