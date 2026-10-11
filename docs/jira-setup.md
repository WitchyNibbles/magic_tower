# Connecting the owner's real Jira

The Jira connector (`backend/app/integrations/jira.py`, `backend/app/services/jira_sync.py`)
is proven against fixtures in the test suite, but AC16 asks for more than that:
a check against the owner's *real* Jira Cloud site. The owner's site URL, email
and API token are not on the machine that develops this repository and must
never be -- so this document is the exact, runnable sequence for **the
machine with Jira access**, plus a command that reports what came back
without ever printing the token. [What actually needs real
credentials](#what-actually-needs-real-credentials) says which of these
commands were run while writing this document, with what result, and which
could not be.

## Prerequisites

- A classic Jira API token, created at
  [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens)
  (`.env.example`'s own `JIRA_API_TOKEN` comment names this same page). Not a
  scoped token -- this connector authenticates as Basic auth over
  `email:token` against `https://<site>.atlassian.net`, which a scoped
  token's host would 401 against.
- The four environment variables `.env.example` already lists, filled in --
  three required, the fourth optional:
  - `JIRA_SITE_URL` -- required; the full `https://<site>.atlassian.net` URL (a
    bare host without the scheme is rejected before any request is made).
  - `JIRA_ACCOUNT_EMAIL` -- required; the Atlassian account the token belongs to.
  - `JIRA_API_TOKEN` -- required; the token created above.
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
have them (see [`second-pc.md`](second-pc.md) for how those two
are generated -- they gate every write to this instance and are unrelated to
Jira).

There is exactly one `.env`, at the repository root, and both steps below read
that one file rather than making a second copy of the token. That takes some
care, because `backend/app/config.py` resolves its `env_file=".env"` against the
**current working directory**: a `.env` at the root is invisible to anything run
from `backend/` unless it is named explicitly. (The README records the same trap
for `pytest`.) Step 2 names it with `uv run --env-file`; step 3 exports it into
the shell for `curl`, and `docker compose` reads it through its own `env_file`.

## 2. Run the connectivity check

```sh
cd backend
uv run --env-file ../.env python -m app.tools.jira_check
```

`--env-file ../.env` is not decoration. Without it this command reads a
`backend/.env` that does not exist and reports all three required settings as
missing, while correct credentials sit in the root `.env` -- observed, not
theorised; see [below](#what-actually-needs-real-credentials).

This is read-only: it calls `GET /rest/api/3/myself` and the same
participation search `backend/app/services/jira_sync.py` uses
(`GET /rest/api/3/search/jql`), and never writes to the database or promotes
anything. **The token itself never appears in its output** -- only what Jira's
responses contain (the token owner's display name and account id, and issue
counts); `backend/tests/test_jira_check.py` pins that a report or a printed
line can never carry it.

A healthy result looks like this. These three lines are what
`backend/tests/test_jira_check.py` asserts character for character against a
stubbed Jira, so they are the tool's real output format rather than a sketch of
it; the site, name, account id and counts are that stub's stand-ins, and a real
run shows the owner's own:

```
connected to https://example.atlassian.net as 'Owner Example' (accountId 5b10a2844c20165700ede21g)
participation window: 1 issue(s)
management project 'OPS': 3 issue(s)
```

The last line only appears when `JIRA_MANAGEMENT_PROJECT_KEY` is set. If any of
the three *required* settings is missing or blank, it exits `1` and names
exactly which ones, without attempting a request:

```
Jira is not configured: missing JIRA_SITE_URL, JIRA_ACCOUNT_EMAIL, JIRA_API_TOKEN
```

A request that does reach Jira and fails exits `1` with that failure's own
message and nothing added to it -- never the token, never any other request
detail (`backend/app/integrations/jira.py`'s transport deliberately discards
request metadata from a caught exception before it reaches this message). A
well-formed `JIRA_SITE_URL` that is not the owner's site, for example:

```
Jira request failed with status 404
```

A DNS failure, a TLS failure, a timeout and unparseable JSON all collapse to the
single message `Jira request failed`, on purpose: what would tell them apart is
exactly the request metadata that must not be printed.

## 3. Run a first sync

The connectivity check above never stores anything. To see Jira issues in the
actionable queue, bring the application up and call the same sync endpoint
Microsoft Graph already uses, naming `jira` as the `kind`:

```sh
cd ..
docker compose up -d --wait api web
set -a; . ./.env; set +a
curl -s -w '\n%{http_code}\n' -X POST "http://localhost:8787/api/sync?kind=jira" \
    -H "Authorization: Bearer $LOCAL_API_TOKEN"
```

(Use `WEB_PORT=<port> docker compose up -d --wait api web` and the matching
port in the `curl` URL if `8787` is already taken on this machine.)

The `set -a; . ./.env; set +a` line is what puts `LOCAL_API_TOKEN` into `curl`'s
environment; `.env` assigns it but exports nothing. Skip that line and the
variable expands empty, so the header goes out blank and
`backend/app/security.py` rejects it like any other invalid token:
`401 {"detail":"A valid local API bearer token is required"}`.

A healthy response reports how many Jira issues were seen and how many reached
the queue, followed by the status code `-w` prints:

```
{"mode":"read-only","synced_at":"...","count":1,"new_sources":1,"new_work_items":0}
200
```

`new_work_items` counts only issues assigned to the token owner
(`backend/app/services/promotion.py`'s Jira rule); everything else the
participation window or the management project returned is still stored and
browsable, just not promoted. Reload the dashboard at `http://localhost:8787`
(or the `WEB_PORT` above) and filter by source `jira` to see them.

Two failures are worth telling apart, and step 2 is how you tell them apart.
Jira simply not configured comes back from this endpoint cleanly:

```
{"detail":"Jira is not configured: missing JIRA_SITE_URL, JIRA_ACCOUNT_EMAIL, JIRA_API_TOKEN"}
409
```

A Jira that *is* configured but cannot be reached, or that rejects the
credentials, comes back as a bare `500 Internal Server Error` with the reason
only in `docker compose logs api` -- `backend/app/api/sync.py` answers `409` for
a `SyncError` and lets every other exception escape, which that route's own
docstring records as its pre-existing behaviour. Step 2 is the quicker way to
read such a failure: it prints the reason straight to your terminal.

## What actually needs real credentials

Every command in this document was run while writing it, on a machine with **no
real Jira credentials**, against a throwaway root `.env` copied from
`.env.example` with a generated `LOCAL_API_TOKEN` and `APP_ENCRYPTION_KEY`. The
Jira settings were filled in twice: once left blank, and once with a
well-formed but fake site URL, email and token -- enough to carry each command
past the configuration check and into a real HTTPS request. `WEB_PORT=8790` was
used throughout, since `8787` was taken on that machine. Every container
started was stopped and its volume removed afterwards.

- Step 1's `cp .env.example .env`: exits `0`.
- Step 2 with the Jira settings blank: exits `1` and prints exactly the "not
  configured" line quoted above, observed verbatim, not paraphrased.
- Step 2 with the fake-but-well-formed settings: exits `1` and prints exactly
  `Jira request failed with status 404`. It built the Basic auth header,
  resolved and connected to `atlassian.net` over TLS and read a real HTTP
  status back, so everything short of the owner's own credentials is exercised.
- Step 2 **without** `--env-file ../.env`, with those same settings present in
  the root `.env`: exits `1` reporting all three as missing. That is the
  working-directory trap the flag exists to avoid.
- Step 3's `docker compose up -d --wait api web`: both containers report
  healthy.
- Step 3's `curl` after the `set -a; . ./.env; set +a` line, Jira blank: `409`
  with the body quoted above. The same `curl` **without** that line: `401
  {"detail":"A valid local API bearer token is required"}`.
- Step 3's `curl` with the fake-but-well-formed Jira settings: `500 Internal
  Server Error`, the unreachable-site case described above.
- `docker compose down -v` afterwards: both containers and the volume gone.

**Not run at all: any request that reaches the owner's real Jira site.** The
healthy three-line report in step 2 and the `200` sync response in step 3 are
the two outputs on this page that no amount of work on this machine can
produce. Both are pinned against a stubbed transport instead of observed --
`backend/tests/test_jira_check.py` asserts those three lines character for
character, and `backend/tests/test_jira_sync.py` asserts the response
envelope's keys -- but that is a proof about this code, not about the owner's
Jira. Only the owner, on the machine holding the site URL, email and API token,
can run step 2 and watch a real name and real counts come back.
