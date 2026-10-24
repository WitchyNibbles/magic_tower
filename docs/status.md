# Status

Snapshot of 2026-10-24, taken from `main` at `fc3e536`. Things will drift from here: check `git log` and the CI badge before trusting a line.

## What it does today

Magic Tower is a local task queue. It reads your Outlook inbox (Microsoft Graph), your Jira Cloud issues and the Freshservice tickets assigned to you, keeps the ones a fixed rule set calls "work" as review items with their evidence, and shows them in a React UI on `127.0.0.1:8787`. Local agent clients can read the queue and post proposals and dispatch records through a loopback API guarded by `LOCAL_API_TOKEN`. It never writes to Microsoft 365, Jira or Freshservice.

## What works end to end

Proven by the test suite and CI, with fake or stubbed Graph, Jira and Freshservice:

- Local UI sign-in with `LOCAL_API_TOKEN`, an HttpOnly session kept in SQLite, and CSRF on writes.
- Outlook connector: PKCE sign-in, token refresh, paging, 429/503 backoff, encrypted token store and excerpts.
- Jira connector: participation search (assigned, reported, created, watched, voted) over the whole gap since the last good sync, an optional browse-only management project, dedupe, and promotion of issues assigned to you.
- Freshservice connector (`docs/freshservice-setup.md`): read-only search of the tickets assigned to you (open and pending ones of any age, plus anything updated within the lookback), dedupe, promotion of the ones assigned to you and not Resolved or Closed, and a connectivity check (`app.tools.freshservice_check`).
- Scheduled sync of every ready source every 10 minutes, and the Sync now button for all of them (`POST /api/sync/all`).
- Promotion rules, the backfill endpoint, review queue actions (filter, update, dismiss, promote, hand off).
- Alembic migrations, also on a database that predates Alembic.
- `docker compose build` (CI job `build`).

Never run against real accounts:

- A Microsoft sign-in and sync against a real tenant (`docs/second-pc.md`, step 4).
- A Jira check or sync against a real site (`docs/jira-setup.md`, "What actually needs real credentials").
- A Freshservice check or sync against a real site (`docs/freshservice-setup.md`, "What is not verified yet").
- The promotion heuristic scored on real mail (precision and recall are still unknown).

## Gaps before daily use

Ranked by how much they block real daily use at work (Jira Cloud, Freshservice, Outlook only through IT).

PR #4 fixed the two that blocked Jira: each sync now covers the whole gap since the last good one (14 days on a first run, `JIRA_SYNC_LOOKBACK_DAYS`), every ready source syncs every 10 minutes on its own (`SYNC_INTERVAL_MINUTES`), and the UI's Sync now button syncs all of them through `POST /api/sync/all`, with a per-source toast.

1. **Freshservice is only partly proven on a real site.** The connector exists and is tested against stubs; one real check (2026-10-24) confirmed the lookup by email and the ticket filter. A full sync, the key's own-agent lookup and the `/a/tickets/<id>` link are unconfirmed. See [Freshservice](#freshservice) below.
2. **Outlook needs IT.** Outlook needs an Entra app registration, and this tenant doesn't let users create one without the Application Developer role (`docs/work-setup.md`, step 5). Once connected, each sync reads only the newest 50 messages in the Inbox folder, so mail that rules file elsewhere is missed.
3. **Image builds can't trust a company root CA.** The Dockerfiles have no hook for an extra CA, so behind TLS inspection `docker compose build` fails at `npm ci` or `uv sync`. The no-Docker dev loop still works.
4. **A big Jira can outgrow one sync.** Each query stops at 2000 issues. A first 14-day sync for a busy account, or a large management project, can hit that; the API log then warns and the Jira result says `"truncated": true`, but the oldest issues are skipped.
5. **Agent handoff has no client.** "Use Codex" and "Use Claude Code" store an `AgentDispatchRequest`, and nothing in the repo consumes it: the pending-work CLI (under scripts/) and its plugins were removed in PR #1 (they survive on `tooling-archive`). An agent can still call the API with `curl`.
6. **Unmeasured heuristic.** Until a labeled sample of real mail is scored, nobody knows how much real work the rules miss or how much noise they let through. This needs Outlook.
7. **An Outlook failure can still be a bare 500.** Jira request failures now answer `409` with their reason, and Sync now always reports per source. A Graph error that isn't a `SyncError` still escapes `POST /api/sync` as `500`, with the reason only in `docker compose logs api`.
8. **Jira Cloud only.** Basic auth over `email:classic-token`, and the Cloud-only `/rest/api/3/search/jql` endpoint. Fine for a Cloud site; Server or Data Center would need new code.

### Freshservice

The connector follows the Jira shape and is read-only (`docs/freshservice-setup.md` is the setup guide):

- a GET-only client for `https://<domain>.freshservice.com/api/v2` with Basic auth (your own API key as username, a dummy password), in `backend/app/integrations/freshservice.py`;
- a sync handler in `backend/app/services/freshservice_sync.py`, a promotion rule (assigned to you and not Resolved or Closed; an unknown owner promotes nothing), and the `freshservice` source kind with no migration;
- `FRESHSERVICE_URL`, `FRESHSERVICE_API_KEY`, optional `FRESHSERVICE_AGENT_EMAIL` and `FRESHSERVICE_SYNC_LOOKBACK_DAYS`, a compose passthrough so shell variables reach the `api` container, and a check command, `app.tools.freshservice_check`;
- the UI lists "Freshservice" as a source.

Run against a real site once (2026-10-24, with the check command): the lookup by `FRESHSERVICE_AGENT_EMAIL` (`/api/v2/agents?email=`) and the ticket filter both worked, and an account with 364 matching tickets showed that the first cap of 300 was too low. Still unverified: the lookup by the key's own agent (`/api/v2/agents/me`, used when no email is set) and the agent-portal ticket link; a wrong guess there shows up as a `Freshservice agent lookup ... failed` message in the check. A search reads at most 1500 tickets (50 pages of 30), then says `"truncated": true`.

## Repo housekeeping

- Issues: none. PRs #1, #2 and #4 are merged (squashed); this doc arrives with #3.
- CI: green on `main` (run 40103017190, 2026-10-24). Jobs: backend pytest, frontend vitest, compose build.
- Remote branches besides `main`: `devgod/run_21fb794e4cf5432aac6836c64fdea769`, `polish/utc-readme-screenshot` and `feat/jira-sync-daily` are superseded (their work is in `main` through PRs #1, #2 and #4). `tooling-archive` is kept on purpose as the archive of removed agent tooling.
- Optional cleanups still open: a `useWorkQueue` hook for `frontend/src/App.tsx`; removing the build-gate scripts `scripts/deadcode.sh`, `scripts/deaddocs_check.py`, `scripts/leave-no-trace.sh` and their tests; ignoring the design hook's untracked .impeccable cache in frontend/.
- Doc drift: `docs/architecture.md`'s diagram draws only Graph, not Jira (its text covers both). `docs/agent-protocol.md` says the repo ships only the API side, but its dispatch section still reads as if an installed client exists.

## Test results

Run on the dev PC (WSL2, no working Docker) on `main` at `fc3e536` plus these docs:

- `frontend: npm run test -- --run` → `Tests  31 passed (31)`
- `frontend: npm run build` → `✓ built in 374ms` (includes `tsc -b`)
- `backend: uv run pytest` → `3 failed, 499 passed, 1 warning in 128.52s`. The 3 failures are `test_docker_compose.py::test_web_port_*`: they shell out to `docker compose config`, and this PC has no working Docker. They pass in CI (`502 passed` on PR #4).
- API smoke runs with throwaway config and no real credentials:
  - before PR #4 (`4a423dd`, migrations to `0010`): `/api/health` 200, `/api/sync/status` 200 (`configured: false`), `POST /api/sync` without a token 401, with a token 409 `Microsoft Graph is not configured`, `?kind=jira` 409 `Jira is not configured: ...`, `/api/work-items` 200 with an empty list.
  - PR #4 (migrations to `0011`, Jira pointed at an unreachable `https://127.0.0.1:9`): `POST /api/sync/all` 200 `{"results":{"jira":{"error":"Jira request failed"}}}`, `?kind=jira` 409 with the same reason, no token 401. A scheduled tick logged a `WARNING` line for Jira, and the API shut down cleanly.

Not checked here: `docker compose up` (no Docker on this PC; CI only builds the images), and anything against a real tenant or Jira site.
