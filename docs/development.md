# Development

Everything here runs from a local checkout, without Docker. The README's [Quick start](../README.md#quick-start) covers the Docker Compose stack.

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
uv run pytest
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
it; `backend/tests/test_migrations.py` fails if the chain and the models drift apart.

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
