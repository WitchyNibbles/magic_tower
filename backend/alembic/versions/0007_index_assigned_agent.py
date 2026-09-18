"""index work_items.assigned_agent

``GET /api/work-items?assigned_agent=`` filters on ``WorkItem.assigned_agent``, but
``0006`` -- which indexed every other column the list endpoints filter and sort
on -- named only ``status``, ``source_kind`` and ``updated_at`` and missed this
one, so a query filtered on it still plans as a full table scan (AC9's carried
gap, backlog B47). ``0006`` has already shipped, so this ships as its own
revision rather than an edit to it.

Same posture as ``0006``: the index name matches exactly what SQLAlchemy's
default naming produces for ``index=True`` (``ix_work_items_assigned_agent``),
because a database built by ``Base.metadata.create_all`` already carries it under
that name, and ``upgrade`` skips it if already present rather than failing on a
duplicate.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-18 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = '0007'
down_revision: str | None = '0006'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ix_work_items_assigned_agent"
TABLE = "work_items"
COLUMN = "assigned_agent"


def _already_present() -> bool:
    """True for a database ``create_all`` already built this index in.

    Offline (``--sql``) runs have nothing to inspect and always emit the DDL.
    """
    if context.is_offline_mode():
        return False
    return any(index["name"] == INDEX_NAME for index in sa.inspect(op.get_bind()).get_indexes(TABLE))


def upgrade() -> None:
    if _already_present():
        return
    op.create_index(INDEX_NAME, TABLE, [COLUMN])


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name=TABLE)
