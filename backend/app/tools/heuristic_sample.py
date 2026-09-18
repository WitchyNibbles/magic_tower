"""The labeled-sample file format shared by ``heuristic_export`` and ``heuristic_eval``.

A row is exactly the fields a human needs to judge one signal -- subject and
excerpt included, in cleartext, since the owner chose to keep full content on the
machine that reads it -- plus the fields :func:`app.services.promotion.should_promote`
decides from, plus a ``label`` a human fills in by hand: ``true`` if the signal
belongs in the triage queue, ``false`` if it does not, ``null`` before it is
labeled. Never write real mail content anywhere but the gitignored sample path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models import Source

# The default lives outside the repository on purpose; ``.gitignore`` also
# excludes this path pattern in case a relative override ever lands one inside it.
DEFAULT_SAMPLE_PATH = Path.home() / ".magic-tower" / "labeled-sample.json"

REQUIRED_FIELDS = (
    "id", "source_kind", "subject", "excerpt", "sender", "sender_kind",
    "to_recipients", "headers", "url", "observed_at", "label",
)


class SampleSchemaError(ValueError):
    """A sample file is present but is not a valid labeled sample."""


def row_from_source(source: Source) -> dict[str, Any]:
    """One unlabeled row, read through the ORM so ``excerpt`` is already decrypted.

    ``signal_context`` is absent for a source a sync never populated it for (there
    is none before this feature shipped); the heuristic fields fall back to the
    same empty values ``should_promote`` treats as "unknown".
    """
    context = source.signal_context
    return {
        "id": source.external_id,
        "source_kind": source.kind.value,
        "subject": source.subject,
        "excerpt": source.excerpt,
        "sender": context.sender if context else None,
        "sender_kind": context.sender_kind if context else None,
        "to_recipients": (context.to_recipients if context else None) or [],
        "headers": (context.headers if context else None) or {},
        "url": source.url,
        "observed_at": source.observed_at.isoformat() if source.observed_at else None,
        "label": None,
    }


def signal_from_row(row: dict[str, Any]) -> dict[str, Any]:
    """Rebuild the signal shape ``should_promote`` reads, from one validated row."""
    return {
        "external_id": row["id"],
        "source_kind": row["source_kind"],
        "sender": row.get("sender"),
        "sender_kind": row.get("sender_kind"),
        "to_recipients": row.get("to_recipients") or [],
        "headers": row.get("headers") or {},
    }


def _validate_row(row: Any, index: int) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise SampleSchemaError(f"row {index} is not an object")
    if missing := [field for field in REQUIRED_FIELDS if field not in row]:
        raise SampleSchemaError(f"row {index} is missing field(s): {', '.join(missing)}")
    if not isinstance(row["id"], str) or not row["id"]:
        raise SampleSchemaError(f"row {index} has no usable \"id\"")
    if row["label"] is not None and not isinstance(row["label"], bool):
        raise SampleSchemaError(f"row {index} has a label that is not true, false, or null: {row['label']!r}")
    return row


def load_sample(path: Path) -> list[dict[str, Any]] | None:
    """The validated rows, or ``None`` when ``path`` does not exist.

    Raises :class:`SampleSchemaError` for a present file that is not a JSON array
    of valid rows -- invalid JSON, a non-array top level, or a row missing a field.
    """
    try:
        text = path.read_text()
    except FileNotFoundError:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise SampleSchemaError(f"{path} is not valid JSON: {error}") from error
    if not isinstance(data, list):
        raise SampleSchemaError(f"{path} must contain a JSON array of rows, found {type(data).__name__}")
    return [_validate_row(row, index) for index, row in enumerate(data)]
