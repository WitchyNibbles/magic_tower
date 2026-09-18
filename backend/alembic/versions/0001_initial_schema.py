"""initial schema

Baseline: exactly the schema the old ``Base.metadata.create_all`` startup hook
produced. A ``workboard.db`` that predates Alembic already holds these tables and
carries no ``alembic_version`` row, so ``upgrade`` skips creation when every one
of them is present with the columns declared below, and only records the revision.
Every later change belongs in a new revision; this one changes only if the schema
it has to recognise was misdescribed.

Revision ID: 0001
Revises: 
Create Date: 2026-09-18 01:46:46.258258
"""

from collections.abc import Sequence

from alembic import context, op
import sqlalchemy as sa

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Exactly what the ``create_table`` calls below produce. The skip check needs its
# own record of that, because it must keep recognising a pre-Alembic database long
# after later revisions have moved ``app.models`` away from this shape.
# ``tests/test_migrations.py`` fails if this stops matching the DDL beside it.
BASELINE_COLUMNS: dict[str, frozenset[str]] = {
    "sources": frozenset({
        "id", "kind", "external_id", "subject", "url", "excerpt", "observed_at",
        "created_at", "updated_at",
    }),
    "work_items": frozenset({
        "id", "title", "summary", "status", "priority", "source_kind",
        "source_external_id", "source_url", "assigned_agent", "due_at", "created_at",
        "updated_at",
    }),
    "agent_dispatches": frozenset({
        "id", "work_item_id", "client", "instruction", "status", "result",
        "created_at", "updated_at",
    }),
    "work_evidence": frozenset({
        "id", "work_item_id", "source_kind", "external_id", "excerpt", "observed_at",
    }),
}


def _column_drift(inspector: sa.Inspector) -> list[str]:
    """How the database's baseline tables differ from this revision's, as prose."""
    drift: list[str] = []
    for table, expected in BASELINE_COLUMNS.items():
        present = {column["name"] for column in inspector.get_columns(table)}
        if missing := expected - present:
            drift.append(f"{table} is missing {sorted(missing)}")
        if unexpected := present - expected:
            drift.append(f"{table} has unexpected {sorted(unexpected)}")
    return drift


def _baseline_already_present() -> bool:
    """True for a database the pre-Alembic ``create_all`` startup already built.

    Offline (``--sql``) runs have no database to inspect and always emit the full
    DDL. A database that only half matches -- missing some of the tables, or holding
    a baseline table whose columns were altered afterwards -- was never left by
    ``create_all``. Stamping one would strand the difference forever, since no later
    revision recreates what this one skipped, so it is refused instead.
    """
    if context.is_offline_mode():
        return False
    inspector = sa.inspect(op.get_bind())
    existing = BASELINE_COLUMNS.keys() & set(inspector.get_table_names())
    if not existing:
        return False
    if existing != BASELINE_COLUMNS.keys():
        raise RuntimeError(
            f"database holds only {sorted(existing)} of the baseline tables; "
            "repair it by hand before migrating"
        )
    if drift := _column_drift(inspector):
        raise RuntimeError(
            "database holds every baseline table but " + "; ".join(drift) + "; "
            "repair it by hand before migrating"
        )
    return True


def upgrade() -> None:
    if _baseline_already_present():
        return
    op.create_table('sources',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Enum('outlook_email', 'teams_message', 'manual', name='sourcekind'), nullable=False),
    sa.Column('external_id', sa.String(length=512), nullable=False),
    sa.Column('subject', sa.String(length=500), nullable=True),
    sa.Column('url', sa.String(length=2048), nullable=True),
    sa.Column('excerpt', sa.Text(), nullable=True),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('external_id')
    )
    op.create_table('work_items',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('status', sa.Enum('pending', 'in_progress', 'blocked', 'done', name='workstatus'), nullable=False),
    sa.Column('priority', sa.Enum('low', 'medium', 'high', 'urgent', name='workpriority'), nullable=False),
    sa.Column('source_kind', sa.Enum('outlook_email', 'teams_message', 'manual', name='sourcekind'), nullable=False),
    sa.Column('source_external_id', sa.String(length=512), nullable=True),
    sa.Column('source_url', sa.String(length=2048), nullable=True),
    sa.Column('assigned_agent', sa.String(length=128), nullable=True),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_external_id')
    )
    op.create_table('agent_dispatches',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('work_item_id', sa.Uuid(), nullable=False),
    sa.Column('client', sa.String(length=32), nullable=False),
    sa.Column('instruction', sa.Text(), nullable=False),
    sa.Column('status', sa.Enum('queued', 'delivered', 'completed', 'failed', name='dispatchstatus'), nullable=False),
    sa.Column('result', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['work_item_id'], ['work_items.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('work_evidence',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('work_item_id', sa.Uuid(), nullable=False),
    sa.Column('source_kind', sa.Enum('outlook_email', 'teams_message', 'manual', name='sourcekind'), nullable=False),
    sa.Column('external_id', sa.String(length=512), nullable=False),
    sa.Column('excerpt', sa.Text(), nullable=True),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['work_item_id'], ['work_items.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('work_evidence')
    op.drop_table('agent_dispatches')
    op.drop_table('work_items')
    op.drop_table('sources')
