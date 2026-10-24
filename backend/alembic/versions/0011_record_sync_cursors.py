"""record when each source last synced successfully

Adds ``sync_cursors``: one row per source kind holding the start time of its last
successful sync. The Jira sync derives its search window from it, so a manual or
scheduled sync asks for what changed since the last one rather than a fixed
15 minutes.

The table is created empty; a kind with no row syncs over the configured lookback
window, which is what the first sync after this revision does. It is skipped when
already present for the same reason ``0009`` and ``0010`` skip -- a database built
by ``Base.metadata.create_all`` already has it.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-24 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = '0011'
down_revision: str | None = '0010'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "sync_cursors"


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
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('kind'),
    )


def downgrade() -> None:
    op.drop_table(TABLE)
