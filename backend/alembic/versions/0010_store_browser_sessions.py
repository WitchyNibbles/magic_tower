"""store browser sessions in the database

Adds ``browser_sessions``, which replaces the in-process dict ``app.security``
used to keep signed-in browsers in: every API restart signed the owner out. A row
holds the SHA-256 of the session cookie (never the cookie itself), the CSRF token
issued with it, and its Unix-time expiry, indexed because starting a session
deletes the expired ones.

The table is created empty; sessions held in memory by the process that ran
before this revision are gone either way, and the owner signs in once more. It is
skipped when already present for the same reason ``0009`` skips -- a database
built by ``Base.metadata.create_all`` already has it.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-11 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = '0010'
down_revision: str | None = '0009'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "browser_sessions"


def _already_present() -> bool:
    """True for a database ``create_all`` already built this table in.

    Offline (``--sql``) runs have nothing to inspect and always emit the DDL.
    """
    return not context.is_offline_mode() and TABLE in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _already_present():
        return
    op.create_table(
        TABLE,
        sa.Column('id_hash', sa.String(length=64), nullable=False),
        sa.Column('csrf_token', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint('id_hash'),
    )
    op.create_index(op.f('ix_browser_sessions_expires_at'), TABLE, ['expires_at'])


def downgrade() -> None:
    op.drop_index(op.f('ix_browser_sessions_expires_at'), table_name=TABLE)
    op.drop_table(TABLE)
