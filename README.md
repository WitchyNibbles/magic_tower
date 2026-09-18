# Magic Tower

![Magic Tower, surrounded by floating runic particles](assets/magic-tower-logo.png)

*A quiet, local-first tower for tending the work that finds you.*

Magic Tower is a local-first workboard for tasks found in a specific Outlook mailbox and Teams conversations. Microsoft Graph ingestion and agent-driven work extraction are deliberately opt-in: nothing crosses the threshold until you invite it in.

## Develop the API with uv

The backend is a standalone [uv](https://docs.astral.sh/uv/) project pinned to Python 3.12. From the repository root:

```sh
cd backend
uv sync
DATABASE_URL=sqlite:///./workboard.db uv run alembic upgrade head
DATABASE_URL=sqlite:///./workboard.db uv run uvicorn app.main:app --reload
```

`/data` is the Docker data directory, so the `DATABASE_URL` override gives a
local checkout a writable SQLite database. If you enable Microsoft Graph,
also set `TOKEN_STORE_PATH` and `OAUTH_STATE_STORE_PATH` to writable local
paths.

Run the backend test command from `backend/`:

```sh
cd backend
uv run pytest tests ../tests/agent_protocol
```

The suite must run from `backend/` because `app/config.py:13` sets
`env_file=".env"`, which is resolved relative to the current working
directory. From the repository root, pytest would load the root `.env`
instead, whose empty `MICROSOFT_*` values fail Settings validation and abort
collection.

When dependencies move, update the committed lockfile with `uv lock`.

## Migrate the schema with Alembic

Alembic owns every table. The application creates none of its own at startup, so a
database must be migrated before it can serve a request. `backend/alembic.ini`
holds no URL: `backend/alembic/env.py` reads `DATABASE_URL` through the same
`app.config.get_settings` the API uses, so both always open the same file.

```sh
cd backend
DATABASE_URL=sqlite:///./workboard.db uv run alembic upgrade head                            # apply
DATABASE_URL=sqlite:///./workboard.db uv run alembic revision --autogenerate -m "what changed"
```

Commit the generated revision together with the `app/models.py` change that motivated
it; `tests/test_migrations.py` fails if the chain and the models drift apart.

**A database created before Alembic existed** (a `workboard.db` or `workboard-data`
volume left by the old `create_all` startup hook) already holds the baseline
tables. Revision `0001` detects that -- by column as well as by table name, so a
schema altered by hand since cannot pass as an untouched one -- and records itself
without recreating them, so plain `alembic upgrade head` -- which the API container
now runs before serving -- works unchanged on such a database. Marking it
explicitly is equivalent:

```sh
cd backend
DATABASE_URL=sqlite:///./workboard.db uv run alembic stamp 0001
```

If those tables are present but their columns are not the ones `0001` creates, the
upgrade fails and names the difference, leaving the database unstamped. No later
revision recreates a column `0001` skipped, so stamping over such a database would
strand it: repair the schema by hand, or recreate the database, before migrating.

## Install the API command with uv

To install the API command into uv's tool environment from a local checkout:

```sh
cd backend
uv tool install --editable .
magic-tower-api app.main:app --reload
```

Set `DATABASE_URL=sqlite:///./workboard.db` before starting the command if you
want a writable SQLite database in the checkout.

## Raise the tower locally

```sh
cp .env.example .env
docker compose up --build
```

Open [http://localhost:8787](http://localhost:8787). The web service binds to loopback only; the API stays inside the Compose network. Stop with `docker compose down`; persistent SQLite data is held in the `workboard-data` Docker volume.

On first use, enter the separately generated `LOCAL_API_TOKEN` in the browser to create an HttpOnly, eight-hour local session. The typed value is not persisted in browser storage; cookie-backed writes also require CSRF protection.

## What waits within

- A clean local dashboard can filter, inspect, update, and dispatch pending work with source evidence.
- SQLite-backed work items, sources, evidence, agent proposals, and auditable dispatch records.
- Delegated Microsoft OAuth with PKCE, `/me`-only Outlook and Teams-chat ingestion, bounded excerpts, and encrypted local token storage.
- An installable Codex plugin/skill plus a Claude Code command and loopback-only JSON CLI in `scripts/pending-work`.

## Configure the Graph familiar

Register a Microsoft Entra application for the intended work/school account. Add the exact redirect URI `http://localhost:8787/api/auth/callback`, configure delegated read-only scopes `User.Read`, `Mail.Read`, `Chat.Read`, and `offline_access`, then set the tenant, client, target object ID, and separately generated `APP_ENCRYPTION_KEY` in `.env`. Some tenants require administrator consent for Teams scopes. The connector uses `/me` only and rejects a sign-in whose object ID does not match `MICROSOFT_TARGET_USER_ID`.

Use `GET /api/auth/microsoft/start` to begin sign-in, then `POST /api/sync` to import bounded Outlook/Teams metadata. It never sends messages or acts in Microsoft 365.

If the database holds `sources` rows written before the promotion heuristic existed, call `POST /api/sync/backfill` once to offer them to it; it never runs on its own (not at startup, not from `POST /api/sync`), reaches no network, and is safe to call again -- a source it has already judged, promoted or not, is never re-judged. Its response reports `considered`, `new_work_items`, `judged_without_context` and `promoted_without_owner_check` separately, because a bare `new_work_items` count cannot tell "nothing left to backfill" apart from "backfilled some and the heuristic declined all of it".

The backfill judges slightly less well than a live sync does, and the last two counts are how it says so. `judged_without_context` counts rows stored before the sender and headers were kept at all, which can only be promoted unconditionally. `promoted_without_owner_check` counts rows promoted without the "skip mail you were only copied on" rule: that rule needs your own addresses, only the live Graph profile has them, and nothing stores them -- so **mail you were merely Cc'd on is promoted by the backfill even though a sync would decline it**. Both counts are rows worth reviewing in the queue, not errors; dismiss what does not belong.

## Measure the heuristic against real mail

The promotion heuristic in `app/services/promotion.py` can only be trusted once it has been checked against real mail, but real mail must never enter this repository. This is a two-machine workflow: sign in and sync on the machine with Outlook access, then hand-label and evaluate.

On the machine with Outlook access, after `.env` holds `MICROSOFT_TENANT_ID`, `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`, `MICROSOFT_TARGET_USER_ID`, `MICROSOFT_REDIRECT_URI`, and `APP_ENCRYPTION_KEY`, and a sync has run (`POST /api/sync`), export the synced sources into a labeled-sample file for hand judging.

`heuristic_export` reads the database the sync wrote to and never talks to Microsoft Graph, so it has to be pointed at that same database -- which one it is depends on how you ran the API.

If you ran it from the checkout with uv ([above](#develop-the-api-with-uv)), that is `backend/workboard.db`, and the export needs the same `DATABASE_URL`:

```sh
cd backend
DATABASE_URL=sqlite:///./workboard.db uv run python -m app.tools.heuristic_export \
    --output ~/.magic-tower/labeled-sample.json
```

If you ran it with `docker compose up`, the database is `/data/workboard.db` inside the `workboard-data` volume, which no host-side `DATABASE_URL` reaches. Export from the running container instead, copy the file out, and delete the container's copy -- `docker compose cp` cannot read the container's `/tmp` tmpfs, so the volume is the only way out and your mail would otherwise stay in it:

```sh
docker compose exec api python -m app.tools.heuristic_export --output /data/labeled-sample.json
docker compose cp api:/data/labeled-sample.json ~/.magic-tower/labeled-sample.json
docker compose exec api rm /data/labeled-sample.json
```

Pointed at a database that does not exist or was never migrated, the export names the problem and exits 1 rather than raising a traceback. On success it writes the file `0600` under a `0700` directory: it is real mail, and a second PC is often a shared one.

Each row carries the fields `should_promote` reads (sender, recipients, the headers the rules read, an excerpt) plus an empty `label` field. Open the file and set `label` to `true` or `false` on the rows you have judged by hand; leave the rest `null`. This file is real mail: `~/.magic-tower/` and any `labeled-sample.json` are gitignored everywhere in this repository, and the file never needs to leave the machine it was exported on.

Then score the heuristic against the labeled rows, naming every address the owner receives mail at -- both the `userPrincipalName` and the mail address, since alias-domain tenants hand out different ones:

```sh
cd backend
uv run python -m app.tools.heuristic_eval --sample ~/.magic-tower/labeled-sample.json \
    --owner-address you@tenant.com --owner-address you@tenant.onmicrosoft.com
```

`--owner-address` is what a live sync takes from the Graph profile, and without it the rule for mail you were only copied on (rule 4) never fires: every cc-only message you labeled `false` is then scored a false positive the production path would never have made, and the reported precision is lower than the heuristic actually achieves.

`heuristic_eval` reads only that JSON file -- no database, no Graph credentials -- so it also runs safely on a machine that has never synced real mail: with no sample file present it prints a message and exits 0. See `app/tools/labeled-sample.example.json` for the (entirely synthetic) row shape.

## Agent integration

Set a separate random `LOCAL_API_TOKEN` in `.env`, then expose it to the agent process as `PENDING_WORK_API_TOKEN`. It is a Magic Tower-only credential, never an Azure or Graph token. See [the agent protocol](docs/agent-protocol.md) for installation and exact commands.

## The warding circle

The API is loopback-only through Compose, Graph tokens and stored message excerpts are AES-GCM encrypted at rest under the same `APP_ENCRYPTION_KEY` but separate associated data, and agent operations require the local token. This is a trusted-local-host design, not protection from a compromised browser profile, Docker host, or local administrator. Keep `.env` local, never store raw Graph credentials in the database, and retain only source excerpts necessary to explain a work suggestion.

## License

Magic Tower is released under the [MIT License](LICENSE).
