"""record which sources the promotion heuristic has judged

Adds ``source_promotions``, one row per ``Source`` promotion has already decided
about. The backfill in ``app/services/backfill.py`` selects on the absence of that
row, because ``work_items`` cannot distinguish a source the heuristic rejected from
one it was never shown, and promoting the first kind is the defect this table
exists to prevent.

**The table is created empty, on purpose.** An existing ``Source`` row is then read
as never judged, so the first backfill offers it to the heuristic -- which is the
behaviour AC8 asks for, and the reason this revision does not stamp the rows it
finds. Stamping them all would be the safer-looking choice and would make the
backfill a no-op on precisely the databases it was written for.

That leaves one window: rows written by a build that already promoted on sync but
predates this table would be indistinguishable from pre-promotion rows, and their
rejects would be promoted once. The window is empty in practice -- promotion and
this table are unreleased work reaching an installation in the same deployment, so
no release ever promoted without recording it -- and it is bounded to a single
backfill run even if that ever stopped being true. An operator who did run the
in-between build can close it by hand before backfilling, by inserting a row here
for every source that build saw.

A new table cannot be confused with the pre-Alembic schema revision ``0001``
recognises: that check reads only the four baseline tables and their columns, and
this one is not among them. It is skipped when already present for the same reason
``0001`` skips -- a database built by ``Base.metadata.create_all`` already has it.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-18 22:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = '0005'
down_revision: str | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "source_promotions"


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
        sa.Column('source_id', sa.Uuid(), nullable=False),
        sa.Column('considered_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['source_id'], ['sources.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('source_id'),
    )


def downgrade() -> None:
    op.drop_table(TABLE)
