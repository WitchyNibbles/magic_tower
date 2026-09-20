# Connecting the owner's real Jira

The Jira connector (`backend/app/integrations/jira.py`, `backend/app/services/jira_sync.py`)
is proven against fixtures in the test suite, but AC16 asks for more than that:
a check against the owner's *real* Jira Cloud site. The owner's site URL, email
and API token are not on the machine that develops this repository and must
never be -- so this document is the exact, runnable sequence for **the
machine with Jira access**, plus a command that reports what came back
without ever printing the token. [What actually needs real
credentials](#what-actually-needs-real-credentials) says exactly which of
these commands were run while writing this document, and which could not be.

## Prerequisites

- A classic Jira API token, created at
  [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens)
  (`.env.example`'s own `JIRA_API_TOKEN` comment names this same page). Not a
  scoped token -- this connector authenticates as Basic auth over
  `email:token` against `https://<site>.atlassian.net`, which a scoped
  token's host would 401 against.
- The four environment variables `.env.example` already lists, filled in:
  - `JIRA_SITE_URL` -- the full `https://<site>.atlassian.net` URL (a bare
    host without the scheme is rejected before any request is made).
  - `JIRA_ACCOUNT_EMAIL` -- the Atlassian account the token belongs to.
  - `JIRA_API_TOKEN` -- the token created above.
  - `JIRA_MANAGEMENT_PROJECT_KEY` -- optional; a project key to sync
    browse-only for management visibility, without promoting its issues into
    the actionable queue. Leave it blank to skip that fetch entirely.
- [`uv`](https://docs.astral.sh/uv/) for the connectivity check below; Docker
  and Docker Compose for a first real sync into the running application. See
  the README's [Develop the API with uv](../README.md#develop-the-api-with-uv)
  section for installing `uv` and what the backend project expects.

## 1. Configure `.env`

```sh
cp .env.example .env
```

Edit `.env` and fill in the four Jira settings from the prerequisites, plus
`LOCAL_API_TOKEN` and `APP_ENCRYPTION_KEY` if this instance does not already
have them (see [`docs/second-pc.md`](docs/second-pc.md) for how those two are
generated -- they gate every write to this instance and are unrelated to
Jira).

## 2. Run the connectivity check

```sh
cd backend
uv run python -m app.tools.jira_check
```

This is read-only: it calls `GET /rest/api/3/myself` and the same
participation search `app/services/jira_sync.py` uses
(`GET /rest/api/3/search/jql`), and never writes to the database or promotes
anything. **The token itself never appears in its output** -- only what Jira's
responses contain (the token owner's display name and account id, and issue
counts); `backend/tests/test_jira_check.py` pins that a report or a printed
line can never carry it.

A healthy result looks like this (real names, real counts -- the shape below
was produced against a stubbed Jira server in `backend/tests/test_jira_check.py`,
not the owner's real site):

```
connected to https://example.atlassian.net as 'Ada Lovelace' (accountId 5b10a2844c20165700ede21g)
participation window: 1 issue(s)
management project 'OPS': 3 issue(s)
```

The last line only appears when `JIRA_MANAGEMENT_PROJECT_KEY` is set. If the
four required settings are missing or blank, it exits `1` and names exactly
which ones, without attempting a request:

```
Jira is not configured: missing JIRA_SITE_URL, JIRA_ACCOUNT_EMAIL, JIRA_API_TOKEN
```

A request that reaches Jira and fails (bad token, wrong site, rate limit)
exits `1` with a message naming the failure, never the token or any other
request detail (`app/integrations/jira.py`'s transport deliberately discards
request metadata from a caught exception before it reaches this message).

## 3. Run a first sync

The connectivity check above never stores anything. To see Jira issues in the
actionable queue, bring the application up and call the same sync endpoint
Microsoft Graph already uses, naming `jira` as the `kind`:

```sh
cd ..
docker compose up -d --wait api web
curl -s -X POST "http://localhost:8787/api/sync?kind=jira" \
    -H "Authorization: Bearer $LOCAL_API_TOKEN"
```

(Use `WEB_PORT=<port> docker compose up -d --wait api web` and the matching
port in the `curl` URL if `8787` is already taken on this machine.)

A healthy response reports how many Jira issues were seen and how many
reached the queue:

```json
{"mode": "read-only", "synced_at": "...", "count": 1, "new_sources": 1, "new_work_items": 0}
```

`new_work_items` counts only issues assigned to the token owner
(`app/services/promotion.py`'s Jira rule); everything else the participation
window or the management project returned is still stored and browsable, just
not promoted. Reload the dashboard at `http://localhost:8787` (or the
`WEB_PORT` above) and filter by source `jira` to see them.

## What actually needs real credentials

Every command above was run while writing this document, against a
throwaway `.env` with a generated `LOCAL_API_TOKEN` and `APP_ENCRYPTION_KEY`
and **no real Jira credentials** -- `JIRA_SITE_URL`, `JIRA_ACCOUNT_EMAIL` and
`JIRA_API_TOKEN` all blank:

- Step 1's `cp .env.example .env`: exits 0.
- Step 2's `uv run python -m app.tools.jira_check`: exits `1` and prints
  exactly `Jira is not configured: missing JIRA_SITE_URL, JIRA_ACCOUNT_EMAIL,
  JIRA_API_TOKEN` -- the "unconfigured" message quoted above, observed
  verbatim, not paraphrased.
- Step 3's `docker compose up -d --wait api web` (with `WEB_PORT=8790`, since
  `8787` was already taken on this machine): both containers report healthy.
  The `curl` line against the running stack, still with Jira unconfigured,
  answered `409 {"detail":"Jira is not configured: missing JIRA_SITE_URL,
  JIRA_ACCOUNT_EMAIL, JIRA_API_TOKEN"}` -- the sync endpoint recognises the
  same unconfigured state the check does, cleanly, rather than crashing.
  `docker compose down` afterwards stopped both containers.

**Not run at all: any request that reaches a real Jira site.** The healthy
report in step 2 and the sync response in step 3 are both shapes pinned by
`backend/tests/test_jira_check.py` and `backend/tests/test_jira_sync.py`
against a stubbed transport, not observations of the owner's real Jira --
that proof needs the owner's own site URL, email and API token, which this
machine does not have and must not be given.
