"""encrypt source excerpts at rest

Data-only: ``sources.excerpt`` stays ``TEXT``, but every value in it becomes an
AES-GCM ciphertext under ``APP_ENCRYPTION_KEY``, so rows written by releases that
stored mail and Teams bodies in cleartext are converted too.

Running it a second time is safe and is the expected operator path after restoring
a backup: a value already carrying the ciphertext prefix is decrypted as a check
and then skipped, never re-sealed. A prefixed value that will not open is a wrong
key or a damaged row, and re-encrypting it would destroy the original beyond
recovery, so the migration stops and leaves the database for repair by hand --
the same posture revision ``0001`` takes towards a drifted baseline schema.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-18 09:12:04.117420
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

from app.services.field_crypto import CIPHERTEXT_PREFIX, decrypt_text, encrypt_text

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SELECT_EXCERPTS = sa.text("SELECT id, excerpt FROM sources WHERE excerpt IS NOT NULL")
UPDATE_EXCERPT = sa.text("UPDATE sources SET excerpt = :excerpt WHERE id = :id")


def _rewrite_excerpts(convert) -> None:
    """Apply ``convert`` to every stored excerpt, row by row, on a live connection.

    ``--sql`` cannot do this: the values to rewrite are only knowable by reading the
    database, and emitting them as literals would put the very cleartext this
    revision removes into a script on disk.
    """
    if context.is_offline_mode():
        raise RuntimeError("encrypting source excerpts needs a live database; run alembic without --sql")
    connection = op.get_bind()
    for row_id, excerpt in connection.execute(SELECT_EXCERPTS).fetchall():
        if (converted := convert(excerpt)) is not None:
            connection.execute(UPDATE_EXCERPT, {"excerpt": converted, "id": row_id})


def _seal(excerpt: str) -> str | None:
    if excerpt.startswith(CIPHERTEXT_PREFIX):
        decrypt_text(excerpt)
        return None
    return encrypt_text(excerpt)


def _open(excerpt: str) -> str | None:
    return decrypt_text(excerpt) if excerpt.startswith(CIPHERTEXT_PREFIX) else None


def upgrade() -> None:
    _rewrite_excerpts(_seal)


def downgrade() -> None:
    _rewrite_excerpts(_open)
