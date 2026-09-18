"""carry heuristic signal context for sources

``persist_signals`` only ever wrote ``subject``/``excerpt``/``url`` -- the fields a
human reads -- and dropped ``sender``, ``sender_kind``, ``to_recipients`` and
``headers`` on the floor. Those are exactly what ``should_promote`` decides from,
so a labeled-sample export built only from the database could never replay the
heuristic a Graph sync actually ran: without them, only the heuristic's last rule
is reachable.

A new table, not new columns on ``sources``: that table's exact column set is how
revision ``0001`` recognises a database that predates Alembic
(``BASELINE_COLUMNS``), and growing it would make every such database look
drifted. Nothing reads this table until a sync writes it; a database with no rows
in it behaves exactly as it did before this revision.

A ``workboard.db`` the pre-Alembic ``create_all`` startup hook built already holds
this table too -- it is part of ``app.models`` like everything else that hook
created -- so ``upgrade`` skips creating it the same way ``0001`` skips
recreating the baseline tables, rather than failing on a table that is already
exactly right.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-18 12:35:23.709938
"""

from collections.abc import Sequence

from alembic import context, op
import sqlalchemy as sa

revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_already_present() -> bool:
    """True only for a live database that already has this exact table.

    Offline (``--sql``) runs have no database to inspect and always emit the
    ``CREATE TABLE``, the same posture ``0001`` takes for the same reason.
    """
    if context.is_offline_mode():
        return False
    return 'source_signal_context' in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _table_already_present():
        return
    op.create_table('source_signal_context',
        sa.Column('source_id', sa.Uuid(), nullable=False),
        sa.Column('sender', sa.String(length=320), nullable=True),
        sa.Column('sender_kind', sa.String(length=32), nullable=True),
        sa.Column('to_recipients', sa.JSON(), nullable=True),
        sa.Column('headers', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['source_id'], ['sources.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('source_id'),
    )


def downgrade() -> None:
    op.drop_table('source_signal_context')
