"""Freshservice sync handler: turns the owner's assigned tickets into ``Source`` rows.

Registered under ``"freshservice"`` (``SourceKind.freshservice``, ``app/models.py``)
the same way ``app/services/jira_sync.py`` registers ``"jira"`` -- importing this
module is the one side effect that makes the kind reachable, which is why
``app/main.py`` imports it even though nothing here is called directly from a route.

Reuses the generic pieces the other handlers proved: ``persist_signals`` stores a
normalized signal as a ``Source`` idempotently, and ``promote_signals`` decides
which of them belong in the actionable queue. Every ticket the search returns is
stored and browsable; only the owner's unresolved ones are promoted, which
``promotion.should_promote`` decides through its Freshservice rule (rule B).

**Who the owner is.** An agent id, resolved once per sync (:func:`owner_agent`):
the agent with ``FRESHSERVICE_AGENT_EMAIL`` when that is set, otherwise the agent
the API key belongs to (``/agents/me``). Unlike Jira, whose search says
``currentUser()`` and whose owner lookup can fail after the issues are fetched,
this connector's query *contains* the owner's id (``agent_id:<id>``), so an owner
nobody can name fails the sync before anything is fetched: nothing stored, nothing
promoted, the cursor where it was. The message names which lookup ran (the setting's name
or the key's own agent), then the client's reason, and never the email or the key.

**The window.** One query per sync, :func:`~app.integrations.freshservice.assigned_tickets_query`:
every Open or Pending ticket assigned to the owner whatever its age, plus every
assigned ticket updated since :func:`since_date`. The filter compares dates only,
and compares them in the account's timezone rather than UTC, so the cut-off is a
whole day, backed off by two more to cover both. Re-fetching a ticket is harmless
(``persist_signals`` is idempotent).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from ..config import Settings
from ..integrations.freshservice import FreshserviceAgent, FreshserviceClient, FreshserviceError, is_int
from .graph import persist_signals
from .promotion import promote_signals
from .sync import SyncError
from .sync_cursor import last_success, record_success
from .sync_registry import register_sync_handler

FRESHSERVICE_SOURCE_KIND = "freshservice"
FALLBACK_TITLE = "(no subject)"
SINCE_OVERLAP_DAYS = 2


def _utc_now() -> datetime:
    return datetime.now(UTC)


def since_date(last_success_at: datetime | None, now: datetime, lookback_days: int) -> date:
    """The day after which an assigned ticket's update makes it part of this sync.

    The day of the last successful sync's start, minus two. With no cursor (the first
    sync) it is the whole lookback instead, and so it is when the cursor is older than
    the lookback -- a long outage must not ask Freshservice for years of history -- or
    in the future, which means the clock stepped back and how long ago the last sync
    really was is unknown, so the whole lookback is searched rather than a window
    that could miss what changed in the meantime.

    The two extra days are the overlap: the filter takes ``yyyy-mm-dd`` and
    ``updated_at:>`` is strict (one day), and Freshservice may evaluate the date in the
    account's timezone rather than UTC, which for an account behind UTC can put the
    date a further day back.
    """
    lookback_start = now - timedelta(days=lookback_days)
    if last_success_at is None or last_success_at > now or last_success_at < lookback_start:
        start = lookback_start
    else:
        start = last_success_at
    return start.date() - timedelta(days=SINCE_OVERLAP_DAYS)


def _normalize_ticket(ticket: dict[str, Any], base_url: str) -> dict[str, Any]:
    """One ticket (as ``search_assigned_tickets`` returns it) into the normalized signal
    shape ``persist_signals``/``promote_signals`` know, the same shape
    ``app/services/jira_sync.py:_normalize_issue`` builds for an issue.

    ``responder_id`` (the agent the ticket is assigned to) and ``ticket_status`` are the
    two Freshservice-shaped fields promotion reads (rule B). They are carried on the
    signal and not into a column, for the reason ``assignee_account_id`` is not: ``sources``
    is pinned to its exact column set, and the verdict they produce is already durable in
    ``source_promotions`` and ``work_items``. The cost is that a backfill, which rebuilds
    signals from stored rows alone, cannot re-decide a Freshservice source and declines it.
    Either is ``None`` when the API gave anything but an integer, which rule B reads as
    "not the owner's" or "not known to be finished" respectively.

    The link is the agent-portal one, ``/a/tickets/<id>``.
    """
    ticket_id = ticket.get("id")
    subject = ticket.get("subject")
    responder_id = ticket.get("responder_id")
    status = ticket.get("status")
    return {
        "external_id": f"{FRESHSERVICE_SOURCE_KIND}:{ticket_id}",
        "source_kind": FRESHSERVICE_SOURCE_KIND,
        "title": subject.strip() if isinstance(subject, str) and subject.strip() else FALLBACK_TITLE,
        "source_url": f"{base_url}/a/tickets/{ticket_id}",
        "observed_at": ticket.get("updated_at"),
        "responder_id": responder_id if is_int(responder_id) else None,
        "ticket_status": status if is_int(status) else None,
    }


def owner_agent(client: FreshserviceClient, settings: Settings) -> FreshserviceAgent:
    """The agent whose tickets these are, or a ``SyncError`` saying the lookup failed.

    A ``FreshserviceError`` carries a message written to be shown (no URL, header, key
    or address), so it is passed on as the reason. An answer that names no agent has no
    reason of its own, and gets a fixed one that, like the others, names no value.
    """
    email = settings.freshservice_agent_email
    lookup = "by FRESHSERVICE_AGENT_EMAIL" if email else "for the API key's own agent"
    try:
        agent = client.find_agent_by_email(email) if email else client.current_agent()
    except FreshserviceError as error:
        raise SyncError(f"Freshservice agent lookup {lookup} failed: {error}") from error
    if agent is None:
        raise SyncError(f"Freshservice agent lookup {lookup} failed: no agent matched")
    return agent


def _fetch_ticket_signals(client: FreshserviceClient, owner: FreshserviceAgent, since: date) -> tuple[list[dict[str, Any]], bool]:
    """The signals, and whether the search hit its page cap.

    Normalized and de-duplicated by ``external_id`` -- mirrors
    ``app/services/jira_sync.py:_fetch_issue_signals``. Pages are fetched one request
    at a time, so a ticket updated between two of them can shift position and arrive
    twice; the dedup is defensive, and the test pins the handling, not the cause.

    A row with no integer ``id`` is skipped: it has no ticket to link to, and every such
    row would otherwise share the external id ``freshservice:None``.
    """
    tickets = client.search_assigned_tickets(owner.id, since)
    deduped: dict[str, dict[str, Any]] = {}
    for ticket in tickets:
        if not isinstance(ticket, dict) or not is_int(ticket.get("id")):
            continue
        signal = _normalize_ticket(ticket, client.base_url)
        deduped.setdefault(signal["external_id"], signal)
    return list(deduped.values()), tickets.truncated


def _sync_freshservice(settings: Settings, db: Session | None = None, limit: int = 50, client: Any = None,
                       freshservice_client: FreshserviceClient | None = None, **_: Any) -> dict[str, Any]:
    """The Freshservice counterpart to ``app/services/jira_sync.py:_sync_jira``.

    ``client`` is the Graph-only kwarg ``sync()`` always forwards; it is accepted so
    dispatch never has to know which handler it is calling, and ignored here because it
    is never a ``FreshserviceClient``. ``limit`` is accepted for the same reason -- the
    search is bounded by ``FRESHSERVICE_FILTER_MAX_PAGES``, not by a caller-supplied
    count. Tests inject a stub transport through ``freshservice_client`` instead, the
    same seam ``FreshserviceClient.from_settings``'s own ``transport`` parameter offers.

    A ``FreshserviceError`` while building the client or searching is raised as a
    ``SyncError`` with the same message, so ``POST /api/sync?kind=freshservice`` answers
    409 with the reason and ``sync_ready_sources`` reports it without a traceback.

    The cursor is when this sync *started*, and only a sync that got all the way through
    persisting and promoting moves it: anything updated while it ran lands in the next
    window, and a raised error leaves the old cursor so the retry covers the same gap.
    """
    errors = settings.freshservice_configuration_errors()
    if errors:
        raise SyncError(f"Freshservice is not configured: missing {', '.join(errors)}")
    started = _utc_now()
    previous = last_success(db, FRESHSERVICE_SOURCE_KIND) if db is not None else None
    since = since_date(previous, started, settings.freshservice_sync_lookback_days)
    try:
        freshservice = freshservice_client or FreshserviceClient.from_settings(settings)
        owner = owner_agent(freshservice, settings)
        signals, truncated = _fetch_ticket_signals(freshservice, owner, since)
    except FreshserviceError as error:
        raise SyncError(str(error)) from error
    created = promoted = 0
    if db is not None:
        created = persist_signals(db, signals)
        promoted = promote_signals(db, signals, owner_agent_id=owner.id)
        record_success(db, FRESHSERVICE_SOURCE_KIND, started)
    return {"mode": "read-only", "synced_at": _utc_now().isoformat(), "count": len(signals),
            "new_sources": created, "new_work_items": promoted, "since": since.isoformat(), "truncated": truncated}


register_sync_handler(FRESHSERVICE_SOURCE_KIND, _sync_freshservice, ready=lambda settings: not settings.freshservice_configuration_errors())
