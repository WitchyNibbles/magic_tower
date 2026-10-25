"""store grimoire's per-item analyses and its project snapshot

Adds two tables:

* ``work_item_analyses``: one row per work item holding the encrypted summary and
  details grimoire wrote, the fingerprint of the source text they were written against,
  when, and by which analyzer. Deleting a work item deletes its analysis.
* ``grimoire_project_snapshot``: a single row (``CHECK (id = 1)``) holding grimoire's
  encrypted project snapshot and when it was replaced.

Both are created empty; the text columns are the ``EncryptedText`` type, which is
``TEXT`` on disk. Each table is skipped when already present for the same reason ``0009``
to ``0011`` skip -- a database built by ``Base.metadata.create_all`` already has it.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-24 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = '0012'
down_revision: str | None = '0011'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ANALYSES = "work_item_analyses"
SNAPSHOT = "grimoire_project_snapshot"


def _already_present(table: str) -> bool:
    """True for a database ``create_all`` already built this table in.

    Offline (``--sql``) runs have nothing to inspect and always emit the DDL.
    """
    return not context.is_offline_mode() and table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if not _already_present(ANALYSES):
        op.create_table(
            ANALYSES,
            sa.Column('work_item_id', sa.Uuid(), nullable=False),
            sa.Column('summary', sa.Text(), nullable=False),
            sa.Column('details', sa.Text(), nullable=False),
            sa.Column('source_fingerprint', sa.String(length=64), nullable=False),
            sa.Column('analyzed_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('analyzer', sa.String(length=40), nullable=False),
            sa.ForeignKeyConstraint(['work_item_id'], ['work_items.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('work_item_id'),
        )
    if not _already_present(SNAPSHOT):
        op.create_table(
            SNAPSHOT,
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('snapshot', sa.Text(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint('id = 1', name='ck_grimoire_project_snapshot_single_row'),
            sa.PrimaryKeyConstraint('id'),
        )


def downgrade() -> None:
    op.drop_table(SNAPSHOT)
    op.drop_table(ANALYSES)
