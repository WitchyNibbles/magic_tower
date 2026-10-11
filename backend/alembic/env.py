"""Alembic environment wired to the application's own settings and metadata.

The URL is never written in ``alembic.ini``: it comes from ``DATABASE_URL`` through
``app.config.get_settings``, the same object the API reads (including its
cwd-relative ``.env``), so a migration can only ever touch the database the
application itself would open.

``render_as_batch`` is on because SQLite cannot ``ALTER``/``DROP`` a column in
place; batch mode rewrites the table instead, which is what future column changes
on the local-first SQLite file will need.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.config import get_settings
from app.database import Base

# Imported for the side effect of registering every table on ``Base.metadata``;
# without it autogenerate would propose dropping the whole schema.
from app import models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout for review instead of touching a database."""
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations against a live connection."""
    engine = create_engine(get_settings().database_url, poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
