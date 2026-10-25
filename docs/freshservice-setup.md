# Connecting Freshservice

The Freshservice connector (`backend/app/integrations/freshservice.py`, `backend/app/services/freshservice_sync.py`) reads the tickets assigned to you and keeps the unresolved ones as work items. It is proven against invented fixtures in the test suite and its check has run once against a real Freshservice site (2026-10-24): [What is not verified yet](#what-is-not-verified-yet) lists exactly which parts are still open.

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
| `FRESHSERVICE_TICKET_FIELD` | no | The internal name of a custom ticket field that says whose ticket it is. Set together with the next one: [section 5](#5-share-an-agent-with-a-team-the-custom-field-filter). |
| `FRESHSERVICE_TICKET_FIELD_VALUE` | no | The value that field must hold for a ticket to be yours. |

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

Open a new shell, then start the stack from it. `FRESHSERVICE_SYNC_LOOKBACK_DAYS`, `FRESHSERVICE_TICKET_FIELD` and `FRESHSERVICE_TICKET_FIELD_VALUE` are not part of the passthrough: put them in `.env`.

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
- `Freshservice agent lookup by FRESHSERVICE_AGENT_EMAIL failed: ...` means the owner could not be found by that address. A `403` here may mean the key's role cannot list agents: try unsetting `FRESHSERVICE_AGENT_EMAIL` so the key's own agent is used. `no agent matched` means no agent has that address: check it for typos.
- `Freshservice agent lookup for the API key's own agent failed: ...` means `/api/v2/agents/me` did not name an agent. A `404` here means the endpoint is not available on your site: set `FRESHSERVICE_AGENT_EMAIL` instead. See the unverified part below.
- A message containing `Freshservice rate limit exceeded, retry after <seconds>` is [the rate limit](#rate-limits).

## 4. What syncs and what promotes

One search per sync, for the agent found in step 3: every ticket assigned to that agent that is Open or Pending, whatever its age, plus every assigned ticket updated since the cut-off day (any status, so resolutions and custom statuses are seen). The cut-off is the day the last good sync started, minus two days of overlap (the filter compares dates only, and your account's timezone may sit behind UTC), or the lookback window on the first sync and after a long gap. All of them are stored and browsable under the source "Freshservice".

Only a ticket that is assigned to you and not Resolved or Closed becomes a work item. If the connector cannot tell who you are, it promotes nothing. Each ticket links to `https://<domain>.freshservice.com/a/tickets/<id>`.

Run a sync from the UI (Sync now), wait for the scheduled one, or call it yourself the way `docs/jira-setup.md` does:

```sh
curl -s -X POST "http://localhost:8787/api/sync?kind=freshservice" -H "Authorization: Bearer $LOCAL_API_TOKEN"
```

A healthy answer is `{"mode":"read-only","synced_at":"...","count":3,"new_sources":3,"new_work_items":2,"since":"2026-10-10","truncated":false,"filtered_out":0}`. Without the two required settings it answers `409` with the missing names. `filtered_out` is how many returned tickets the [field filter](#5-share-an-agent-with-a-team-the-custom-field-filter) dropped; it is `0` when no filter is set.

A search reads at most 50 pages of 30 tickets. If you have more than 1500 matching tickets, the answer says `"truncated": true` and the API log warns; the oldest ones are skipped.

## 5. Share an agent with a team: the custom-field filter

Use this when you are one of several people behind a shared agent that holds hundreds of tickets, and a custom field on the ticket names the person it is really for (a dropdown called, say, "Technician" set to your name). Without a filter every ticket of the shared agent is synced as yours; with one, only the tickets whose field holds your value are stored and promoted. Leave both settings out if your tickets are simply assigned to you.

| Variable | What to put |
| --- | --- |
| `FRESHSERVICE_TICKET_FIELD` | The field's internal name, for example `technician`: lowercase letters, digits and underscores only. |
| `FRESHSERVICE_TICKET_FIELD_VALUE` | The value, for example `Jane Example`. |

Both or neither. `.env.example` does not list them yet; add them to `.env` by hand.

**Finding the internal name.** It is not the label you see on the ticket form. Ask for the ticket form's field definitions, which an admin can read: `GET /api/v2/ticket_form_fields` returns a list, and each custom field's `name` is what goes in `FRESHSERVICE_TICKET_FIELD` (usually the label in lowercase with underscores, sometimes with a number after it). If your key cannot read that list, ask a Freshservice admin for the name, or look at one of your tickets under `custom_fields` in `GET /api/v2/tickets/<id>`.

**The value must match the dropdown choice exactly**, letter for letter (case counts; spaces at the ends are ignored). A value with a quote (`'` or `"`) or a backslash is refused, because it goes into the search text and the way to escape it is not known: the check and the sync stop with `Freshservice is not configured: FRESHSERVICE_TICKET_FIELD_VALUE must not contain quotes or backslashes`. Setting only one of the two stops them with `missing FRESHSERVICE_TICKET_FIELD` or `missing FRESHSERVICE_TICKET_FIELD_VALUE`. Messages name the setting and never print the value. The whole search text must also stay within 512 characters; a very long value is refused with a message saying so.

What it does: the search asks Freshservice for `AND <field>:'<value>'` next to the agent, and the sync then checks each returned ticket again and drops any whose `custom_fields` do not hold the value, so a site that ignores the clause still cannot put a colleague's tickets in your queue. The sync answer's `filtered_out` counts the dropped ones.

With the filter on, the check from step 3 adds a line with the field name (never the value) and counts only the tickets that match:

```text
connected to https://example.freshservice.com as 'Owner Example' (agent id 1001)
ticket field filter: technician (value set)
assigned tickets (open, pending, or updated in the last 14 days): 3
server returned 5, 3 matched the field filter
```

The last line appears only when the server returned more than matched; if it does, Freshservice is not applying the clause itself and the client-side check is doing the work. That is safe, but the search reads all of the agent's tickets, so the page limit in step 4 applies to them.

## Read-only

The client refuses anything but `GET` before a request is made. Nothing is created, updated, assigned, closed or replied to in Freshservice, and the connector sends no request body.

## Rate limits

Freshservice limits calls per minute by plan and answers `429` with a `Retry-After` header. One sync makes one agent lookup and as many search pages as your tickets fill (30 per page, at most 50), so it stays well under typical limits. If a `429` happens anyway, the sync stops with the message above, nothing is stored from that run and the cursor does not move, so the next scheduled sync (or Sync now) covers the same window.

## What is not verified yet

The first real checks (2026-10-24) confirmed the lookup by `FRESHSERVICE_AGENT_EMAIL` (`GET /api/v2/agents?email=<email>`), the ticket filter with its `agent_id` term, and the custom-field filter: the server applied `<field>:'<value>'` itself and returned only matching tickets. These were built from the public API documentation and are still tested against stubs only:

- The lookup of the key's own agent, `GET /api/v2/agents/me`, used when `FRESHSERVICE_AGENT_EMAIL` is unset: reported to work but undocumented. Its parser, like the email one, treats an unexpected shape as "owner unknown", which fails the sync with a `Freshservice agent lookup ... failed` message instead of guessing.
- The ticket link `https://<domain>.freshservice.com/a/tickets/<id>`: the agent-portal address is assumed, not confirmed.
- How your account's timezone treats the `updated_at` cut-off of the ticket filter (the sync backs off two days to cover it).

If one of these fails on your site, the check in step 3 shows it, and the fix is a small change in `backend/app/integrations/freshservice.py`.
