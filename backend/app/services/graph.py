"""Normalization boundary between raw Graph responses and local agent intake."""

from __future__ import annotations

from typing import Any
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..integrations.graph import GraphClient
from ..models import Source, SourceKind


def normalize_email(row: dict[str, Any]) -> dict[str, Any]:
    return {"external_id": f"outlook:{row['id']}", "source_kind": "outlook_email", "title": row.get("subject") or "(no subject)", "excerpt": row.get("bodyPreview") or "", "source_url": row.get("webLink"), "observed_at": row.get("receivedDateTime")}


def normalize_teams(row: dict[str, Any]) -> dict[str, Any]:
    body = row.get("body") or {}
    return {"external_id": f"teams:{row['id']}", "source_kind": "teams_message", "title": row.get("chatTopic") or "Teams conversation", "excerpt": body.get("content") if isinstance(body, dict) else str(body), "source_url": row.get("webUrl"), "observed_at": row.get("createdDateTime")}


def fetch_signals(client: GraphClient, limit: int = 50) -> list[dict[str, Any]]:
    rows = [*(normalize_email(row) for row in client.inbox_messages(limit)), *(normalize_teams(row) for row in client.chat_messages(limit))]
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        deduped.setdefault(row["external_id"], row)
    return list(deduped.values())


def persist_signals(db: Session, signals: list[dict[str, Any]]) -> int:
    """Store bounded source metadata idempotently; never persist Graph tokens."""
    created = 0
    for signal in signals:
        external_id = str(signal["external_id"])
        if db.scalar(select(Source.id).where(Source.external_id == external_id)) is not None:
            continue
        observed_at = signal.get("observed_at")
        try:
            parsed_time = datetime.fromisoformat(str(observed_at).replace("Z", "+00:00")) if observed_at else datetime.now()
        except ValueError:
            parsed_time = datetime.now()
        kind = SourceKind(str(signal["source_kind"]))
        db.add(Source(
            kind=kind,
            external_id=external_id,
            subject=str(signal.get("title") or "")[:500] or None,
            url=str(signal.get("source_url") or "")[:2048] or None,
            excerpt=str(signal.get("excerpt") or "")[:2_000] or None,
            observed_at=parsed_time,
        ))
        created += 1
    db.commit()
    return created
