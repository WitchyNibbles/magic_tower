"""remove the Teams source

Teams ingestion needs Azure ``Chat.Read`` consent the owner does not have and
cannot grant (2026-09-19), so it is retired entirely: ``app.models`` drops
``SourceKind.teams_message``, ``app/services/graph.py`` stops calling
``GraphClient.chat_messages``, and ``GRAPH_SCOPES`` stops asking for
``Chat.Read``. This revision is the data half of that cut.

**Existing ``teams_message`` rows are deleted, not remapped.** Reading a row
through the ORM re-validates its ``kind``/``source_kind`` column against
today's ``SourceKind``, and a value that used to be a member is not one any
more -- so a database holding one would start raising on the first query that
touches it, the moment this ships, whichever choice is made. Remapping to
``manual`` was the alternative and is rejected: ``manual`` means the owner
typed the row in by hand, and relabeling an unattended Graph sync that way
misdescribes its provenance for good, with no way to tell the two apart again.
Nothing in the product can act on a Teams excerpt once ``Chat.Read`` is gone --
it is not re-fetchable, not re-verifiable against the source chat, and not
read by any surviving code path -- so keeping the row changes nothing it is
still useful for. Deleting is therefore the choice that loses no information
the running system can still use, and it is the only one of the two that
leaves every remaining row readable.

The cut reaches every table a promoted Teams source could have left rows in.
``work_items`` and ``work_evidence`` carry no foreign key back to ``sources``
-- they key on ``source_external_id``/``external_id`` by convention, not a
constraint (see ``app/services/promotion.py``) -- so a work item promoted from
a ``teams_message`` source needs its own delete; nothing cascades to it.
``source_signal_context`` and ``source_promotions`` do carry a real
``ON DELETE CASCADE`` to ``sources``, and ``agent_dispatches`` carries one to
``work_items``, so deleting the parent rows would be enough for those three on
a connection that enforces foreign keys; all three are deleted by hand below
anyway, because SQLite only enforces ``ON DELETE CASCADE`` when
``PRAGMA foreign_keys`` is on for the connection that issues the delete, and
this revision does not assume that pragma is set. Those four -- the two on
``sources``, plus ``agent_dispatches`` and ``work_evidence`` on ``work_items``
-- are every foreign key in the schema that reaches either parent.

Irreversible: ``downgrade`` cannot bring back content this revision deletes,
so it is a no-op rather than a lie.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-19 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0008'
down_revision: str | None = '0007'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REMOVED_KIND = "teams_message"

# Order matters: children before parents, so nothing is ever left pointing at a
# row this revision has already removed.
_STATEMENTS = (
    "DELETE FROM work_evidence WHERE work_item_id IN "
    "(SELECT id FROM work_items WHERE source_kind = :kind)",
    "DELETE FROM work_evidence WHERE source_kind = :kind",
    "DELETE FROM agent_dispatches WHERE work_item_id IN "
    "(SELECT id FROM work_items WHERE source_kind = :kind)",
    "DELETE FROM work_items WHERE source_kind = :kind",
    "DELETE FROM source_signal_context WHERE source_id IN "
    "(SELECT id FROM sources WHERE kind = :kind)",
    "DELETE FROM source_promotions WHERE source_id IN "
    "(SELECT id FROM sources WHERE kind = :kind)",
    "DELETE FROM sources WHERE kind = :kind",
)


def upgrade() -> None:
    for statement in _STATEMENTS:
        op.execute(sa.text(statement).bindparams(kind=REMOVED_KIND))


def downgrade() -> None:
    pass
