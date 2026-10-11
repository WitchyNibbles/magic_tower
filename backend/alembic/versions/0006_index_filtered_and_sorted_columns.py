"""index the columns the list endpoints filter and sort on

``GET /api/work-items`` and ``GET /api/sources`` filter on ``WorkItem.status``,
``WorkItem.source_kind`` and ``Source.kind``, and sort on ``WorkItem.updated_at``
and ``Source.observed_at`` -- none of them indexed, so every page scans the whole
table. ``Source.external_id`` already carries an index implicitly through its
unique constraint (``0001``), so it is not repeated here.

Index names match exactly what SQLAlchemy's default naming produces for
``index=True`` on these columns (``ix_<table>_<column>``), because a database
built by ``Base.metadata.create_all`` -- the pre-Alembic startup path, and the
legacy fixture in ``tests/test_migrations.py`` -- already carries indexes under
those names. ``upgrade`` skips a name it finds already present rather than
failing on a duplicate, the same posture ``0004``/``0005`` take for their tables.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-18 13:13:56.020505
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = '0006'
down_revision: str | None = '0005'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (index name, table, column)
INDEXES: tuple[tuple[str, str, str], ...] = (
    ("ix_work_items_status", "work_items", "status"),
    ("ix_work_items_source_kind", "work_items", "source_kind"),
    ("ix_work_items_updated_at", "work_items", "updated_at"),
    ("ix_sources_kind", "sources", "kind"),
    ("ix_sources_observed_at", "sources", "observed_at"),
)


def _existing_index_names() -> frozenset[str]:
    """Index names already on disk, empty for an offline (``--sql``) run."""
    if context.is_offline_mode():
        return frozenset()
    inspector = sa.inspect(op.get_bind())
    names: set[str] = set()
    for table in {table for _, table, _ in INDEXES}:
        names.update(index["name"] for index in inspector.get_indexes(table))
    return frozenset(names)


def upgrade() -> None:
    present = _existing_index_names()
    for name, table, column in INDEXES:
        if name in present:
            continue
        op.create_index(name, table, [column])


def downgrade() -> None:
    for name, table, _ in INDEXES:
        op.drop_index(name, table_name=table)
