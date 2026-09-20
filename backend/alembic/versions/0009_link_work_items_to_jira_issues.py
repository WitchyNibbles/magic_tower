"""link work items to the Jira issue they are about

Adds ``work_item_issue_keys``, one row per work item that is known to be about a
Jira issue. The same issue arrives twice -- as notification mail
(``outlook:{id}``) and over the participation query (``jira:{id}``) -- and the
two ``external_id``s share nothing, so the issue key is what matches them
(``app/services/jira_dedupe.py``). ``issue_key`` is unique: a second work item
for an issue that already has one is refused by the database, not only by the
promoter's lookup.

The table is created empty. Existing work items are left unlinked, and stay
so: the promoter skips a mail it has already promoted before it reads a key, so
an item promoted before this revision is never matched against its issue.
Nothing here guesses a key from stored rows, and an unlinked item is exactly
what the code before this revision already produced.

A new table cannot be confused with the pre-Alembic schema revision ``0001``
recognises: that check reads only the four baseline tables and their columns, and
this one is not among them. It is skipped when already present for the same
reason ``0005`` skips -- a database built by ``Base.metadata.create_all`` already
has it.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-20 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = '0009'
down_revision: str | None = '0008'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "work_item_issue_keys"


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
        sa.Column('work_item_id', sa.Uuid(), nullable=False),
        sa.Column('issue_key', sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(['work_item_id'], ['work_items.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('work_item_id'),
        sa.UniqueConstraint('issue_key'),
    )


def downgrade() -> None:
    op.drop_table(TABLE)
