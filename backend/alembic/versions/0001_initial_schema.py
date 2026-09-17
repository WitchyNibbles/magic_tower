"""initial schema

Baseline: exactly the schema the old ``Base.metadata.create_all`` startup hook
produced. A ``workboard.db`` that predates Alembic already holds these tables and
carries no ``alembic_version`` row, so ``upgrade`` skips creation when every one
of them is present and only records the revision. Every later change belongs in
a new revision; this one is never edited.

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


BASELINE_TABLES = frozenset({"sources", "work_items", "agent_dispatches", "work_evidence"})


def _baseline_already_present() -> bool:
    """True for a database the pre-Alembic ``create_all`` startup already built.

    Offline (``--sql``) runs have no database to inspect and always emit the full
    DDL. A database holding only some of the tables was never produced by
    ``create_all`` and is refused rather than half-migrated.
    """
    if context.is_offline_mode():
        return False
    existing = BASELINE_TABLES & set(sa.inspect(op.get_bind()).get_table_names())
    if existing and existing != BASELINE_TABLES:
        raise RuntimeError(
            f"database holds only {sorted(existing)} of the baseline tables; "
            "repair it by hand before migrating"
        )
    return existing == BASELINE_TABLES


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
