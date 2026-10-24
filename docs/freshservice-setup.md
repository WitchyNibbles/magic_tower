# Connecting Freshservice

The Freshservice connector (`backend/app/integrations/freshservice.py`, `backend/app/services/freshservice_sync.py`) reads the tickets assigned to you and keeps the unresolved ones as work items. It is proven against invented fixtures in the test suite and **has not been run against a real Freshservice site yet**: [What is not verified yet](#what-is-not-verified-yet) lists exactly which parts that leaves open.

Placeholders like `<domain>` stand for your own values. Real values go in `.env` and in your shell only. This repo is public: no company names, hosts, addresses or ticket text go into a commit, an issue or a PR.

## 1. Get an API key

In Freshservice, open your profile (your avatar, top right), then **Profile Settings**. The **API Key** panel is on the right: complete the captcha and copy the key. It is your own key and acts as you, with your agent permissions. The connector only ever sends `GET` requests, so it reads what you can read and changes nothing.

Some sites turn the API off for non-admins. If the check below answers `403`, ask whoever runs your Freshservice instance.

## 2. Settings

| Variable | Required | What it is |
| --- | --- | --- |
| `FRESHSERVICE_URL` | yes | `https://<domain>.freshservice.com`. A path after the host is dropped. |
| `FRESHSERVICE_API_KEY` | yes | The key from step 1. Never logged and never returned by the API. |
| `FRESHSERVICE_AGENT_EMAIL` | no | The email of the agent whose tickets to sync. Leave it out and the connector uses the agent the API key belongs to. |
| `FRESHSERVICE_SYNC_LOOKBACK_DAYS` | no | How far back the first sync looks for tickets that were updated. Default 14. After that each sync starts where the last good one stopped. |

Add the ones you need to `.env` (`.env.example` does not list them yet; copy the names from this table). Then, from the repository root:

```sh
chmod 600 .env
```

### Variables from your shell

Docker Compose passes `FRESHSERVICE_URL`, `FRESHSERVICE_API_KEY` and `FRESHSERVICE_AGENT_EMAIL` from the shell that runs `docker compose up` into the `api` container, as well as reading them from `.env`. Compose looks in the shell first and in `.env` second, so a shell value wins when both exist, and a variable set in neither arrives empty, which the app treats as "Freshservice is not configured".

That means you do not have to copy the key into `.env`. If your key already lives in a shell variable with a different name, map it in your shell profile (`~/.bashrc` or your shell's equivalent) and nothing about this repo needs to know the original name:

```sh
export FRESHSERVICE_URL=https://<domain>.freshservice.com
export FRESHSERVICE_API_KEY="$YOUR_OWN_VARIABLE_NAME"
```

Open a new shell, then start the stack from it. `FRESHSERVICE_SYNC_LOOKBACK_DAYS` is not part of the passthrough: put it in `.env`.

## 3. Check without starting the app

```sh
cd backend
uv run --env-file ../.env python -m app.tools.freshservice_check
```

`--env-file ../.env` is needed for the same reason as in `docs/jira-setup.md`: the settings are read relative to the current directory, so from `backend/` the root `.env` is invisible unless it is named. Variables already exported in your shell need no flag.

A healthy run prints two lines (the name, id and count here are invented):

```text
connected to https://example.freshservice.com as 'Owner Example' (agent id 1001)
assigned tickets (open, pending, or updated in the last 14 days): 3
```

The count is the same set the first sync fetches. The tool never writes to the database and never prints the key, your email or any ticket text. On failure it exits `1` with one message:

- `Freshservice is not configured: missing FRESHSERVICE_URL, FRESHSERVICE_API_KEY` names the required settings that are empty. Nothing was requested.
- `FRESHSERVICE_URL must be a full https URL like https://<domain>.freshservice.com` means the URL has no `https://` or no host.
- `Freshservice request failed with status 401` is a wrong or expired key. `403` is the API being closed to you (step 1).
- `Freshservice request failed` with no status is DNS, TLS, a proxy or a timeout.
- `Freshservice agent lookup failed: ...` means the owner could not be found. Check `FRESHSERVICE_AGENT_EMAIL`, or unset it to use the key's own agent. See the unverified part below.
- A message containing `Freshservice rate limit exceeded, retry after <seconds>` is [the rate limit](#rate-limits).

## 4. What syncs and what promotes

One search per sync, for the agent found in step 3: every ticket assigned to that agent that is Open or Pending, whatever its age, plus every assigned ticket updated since the cut-off day (any status, so resolutions and custom statuses are seen). The cut-off is the day the last good sync started, minus one day of overlap, or the lookback window on the first sync and after a long gap. All of them are stored and browsable under the source "Freshservice".

Only a ticket that is assigned to you and not Resolved or Closed becomes a work item. If the connector cannot tell who you are, it promotes nothing. Each ticket links to `https://<domain>.freshservice.com/a/tickets/<id>`.

Run a sync from the UI (Sync now), wait for the scheduled one, or call it yourself the way `docs/jira-setup.md` does:

```sh
curl -s -X POST "http://localhost:8787/api/sync?kind=freshservice" -H "Authorization: Bearer $LOCAL_API_TOKEN"
```

A healthy answer is `{"mode":"read-only","synced_at":"...","count":3,"new_sources":3,"new_work_items":2,"since":"2026-10-10","truncated":false}`. Without the two required settings it answers `409` with the missing names.

A search reads at most 10 pages of 30 tickets. If you have more than 300 matching tickets, the answer says `"truncated": true` and the API log warns; the oldest ones are skipped.

## Read-only

The client refuses anything but `GET` before a request is made. Nothing is created, updated, assigned, closed or replied to in Freshservice, and the connector sends no request body.

## Rate limits

Freshservice limits calls per minute by plan and answers `429` with a `Retry-After` header. One sync makes one agent lookup and up to 10 search pages, so it stays well under typical limits. If a `429` happens anyway, the sync stops with the message above, nothing is stored from that run and the cursor does not move, so the next scheduled sync (or Sync now) covers the same window.

## What is not verified yet

These were built from the public API documentation and tested against stubs only. The first run on a real site is the test:

- The agent lookups: `GET /api/v2/agents?email=<email>` (for `FRESHSERVICE_AGENT_EMAIL`) and `GET /api/v2/agents/me` (for the key's own agent). The first was not found in the documentation we could read; the second is reported to work but is undocumented. Both parsers treat an unexpected shape as "owner unknown", which fails the sync with `Freshservice agent lookup failed` instead of guessing.
- The ticket link `https://<domain>.freshservice.com/a/tickets/<id>`: the agent-portal address is assumed, not confirmed.
- The `agent_id` and date terms of the ticket filter on a real account, in particular how your account's timezone treats the `updated_at` cut-off.

If one of these fails on your site, the check in step 3 shows it, and the fix is a small change in `backend/app/integrations/freshservice.py`.
