"""Normalization boundary between raw Graph responses and local agent intake."""

from __future__ import annotations

from typing import Any
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..integrations.graph import GraphClient
from ..models import Source, SourceKind, SourceSignalContext


def _heuristic_headers(headers: Any) -> dict[str, str]:
    """Only the headers ``should_promote`` reads, so nothing else is kept on disk.

    Graph returns the whole ``internetMessageHeaders`` block -- routing chains,
    authentication results, the subject line again, tenant bookkeeping -- and none of
    it is an input to any rule. ``HEURISTIC_HEADERS`` is imported here rather than at
    module scope because ``promotion`` imports ``parse_observed_at`` from this module.
    """
    from .promotion import HEURISTIC_HEADERS

    return {str(name): str(value) for name, value in dict(headers or {}).items()
            if str(name).lower() in HEURISTIC_HEADERS}


def parse_observed_at(value: Any) -> datetime:
    """Graph's ISO-8601 timestamp, or now if it is missing or unparseable."""
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else datetime.now()
    except ValueError:
        return datetime.now()


def _address(entry: Any) -> str | None:
    """The plain address inside a Graph ``emailAddress`` wrapper, if there is one."""
    email_address = entry.get("emailAddress") if isinstance(entry, dict) else None
    address = email_address.get("address") if isinstance(email_address, dict) else None
    return str(address) if address else None


def _addresses(entries: Any) -> list[str]:
    return [address for entry in entries if (address := _address(entry))] if isinstance(entries, list) else []


def _headers(entries: Any) -> dict[str, str]:
    """Internet message headers as a name-keyed mapping; promotion reads bulk markers from it."""
    if not isinstance(entries, list):
        return {}
    return {str(entry["name"]): str(entry.get("value") or "") for entry in entries
            if isinstance(entry, dict) and entry.get("name")}


def normalize_email(row: dict[str, Any]) -> dict[str, Any]:
    return {"external_id": f"outlook:{row['id']}", "source_kind": "outlook_email", "title": row.get("subject") or "(no subject)", "excerpt": row.get("bodyPreview") or "", "source_url": row.get("webLink"), "observed_at": row.get("receivedDateTime"),
            "sender": _address(row.get("from")), "sender_kind": "user", "to_recipients": _addresses(row.get("toRecipients")), "headers": _headers(row.get("internetMessageHeaders"))}


def fetch_signals(client: GraphClient, limit: int = 50) -> list[dict[str, Any]]:
    rows = [normalize_email(row) for row in client.inbox_messages(limit)]
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
        parsed_time = parse_observed_at(signal.get("observed_at"))
        kind = SourceKind(str(signal["source_kind"]))
        source = Source(
            kind=kind,
            external_id=external_id,
            subject=str(signal.get("title") or "")[:500] or None,
            url=str(signal.get("source_url") or "")[:2048] or None,
            excerpt=str(signal.get("excerpt") or "")[:2_000] or None,
            observed_at=parsed_time,
        )
        # Carried across so a labeled-sample export can rebuild the exact signal
        # shape ``should_promote`` decided from -- otherwise a sample read back
        # from the database could only ever hit the heuristic's default rule.
        # Headers are narrowed to the ones a rule reads: that is the whole reason
        # they are stored, and the rest of the block is content-bearing metadata.
        source.signal_context = SourceSignalContext(
            sender=str(signal["sender"])[:320] if signal.get("sender") else None,
            sender_kind=str(signal.get("sender_kind") or "") or None,
            to_recipients=list(signal.get("to_recipients") or []) or None,
            headers=_heuristic_headers(signal.get("headers")) or None,
        )
        db.add(source)
        created += 1
    db.commit()
    return created
