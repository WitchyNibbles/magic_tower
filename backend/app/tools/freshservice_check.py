"""Standalone health check against the owner's real Freshservice.

Usage::

    cd backend
    uv run --env-file ../.env python -m app.tools.freshservice_check

``--env-file`` is load-bearing, not decoration: ``Settings`` resolves its
``env_file`` against the current working directory (``app/config.py``), so the
repository-root file this project keeps its settings in is invisible from
``backend/`` unless it is named. Without the flag this command reports every
required Freshservice setting as missing while correct ones sit on disk. Variables
already exported in the shell need no flag.

Reads ``FRESHSERVICE_URL``, ``FRESHSERVICE_API_KEY`` and, optionally,
``FRESHSERVICE_AGENT_EMAIL`` the same way the sync handler does
(``Settings.freshservice_configuration_errors()``,
``FreshserviceClient.from_settings`` and ``owner_agent`` --
``app/services/freshservice_sync.py``), and reports what Freshservice sent back: the
agent the tickets are assigned by, and how many tickets fall in the sync's query
(open, pending, or updated within ``FRESHSERVICE_SYNC_LOOKBACK_DAYS``, as a first sync
would fetch them).

With ``FRESHSERVICE_TICKET_FIELD`` and ``FRESHSERVICE_TICKET_FIELD_VALUE`` set it also
names the field (never the value) and counts the tickets that pass the sync's own
client-side field check, saying how many the server returned when that differs.

This never writes to the database and never promotes anything -- it reads the same
endpoints the sync handler calls, through the same injectable transport, so
``backend/tests/test_freshservice_check.py`` pins its report against a stub with no
network.

**The key, the email and the tickets' text never reach what is printed.**
``FreshserviceClient.from_settings`` is the only place that reads
``Settings.freshservice_api_key``, to build the auth header, and the agent email is
only ever sent as a query parameter. What :func:`run_check` returns and :func:`main`
prints is built from what Freshservice's *responses* contain (an agent id and name, a
ticket count) plus one setting that is a name, not a secret: the filter's field name.
Never the settings that authenticated the request, the filter's value, or a ticket's
fields.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime

from ..config import Settings, get_settings
from ..integrations.freshservice import (
    FreshserviceClient,
    FreshserviceError,
    Transport,
    default_transport,
    ticket_matches_field,
)
from ..services.freshservice_sync import owner_agent, since_date
from ..services.sync import SyncError


def run_check(settings: Settings, transport: Transport = default_transport, now: datetime | None = None) -> dict[str, object]:
    """Everything :func:`main` prints, as data, so a test can assert on the report
    without capturing stdout. Raises ``FreshserviceError`` (a configuration error is
    one) or ``SyncError`` (an owner nobody can name) rather than swallowing either --
    :func:`main` is the one place that turns them into an exit code and a message.

    ``now`` is when "the last N days" is measured from; it is a parameter so a test
    can fix it.
    """
    client = FreshserviceClient.from_settings(settings, transport=transport)
    agent = owner_agent(client, settings)
    lookback_days = settings.freshservice_sync_lookback_days
    ticket_filter = settings.freshservice_ticket_filter()
    tickets = client.search_assigned_tickets(agent.id, since_date(None, now or datetime.now(UTC), lookback_days), ticket_filter)
    if ticket_filter is None:
        server_count = ticket_count = tickets.total if tickets.total is not None else len(tickets)
    else:
        # What the sync would keep: the count of tickets in hand that pass the same
        # client-side check, against what came back (not ``total``, which can count
        # pages this run did not read).
        server_count = len(tickets)
        ticket_count = sum(ticket_matches_field(ticket, ticket_filter) for ticket in tickets)
    return {
        "base_url": client.base_url,
        "agent_id": agent.id,
        "agent_name": agent.name,
        "field_filter": ticket_filter[0] if ticket_filter else None,
        "ticket_count": ticket_count,
        "server_ticket_count": server_count,
        "lookback_days": lookback_days,
    }


def _print_report(report: dict[str, object]) -> None:
    print(f"connected to {report['base_url']} as {report['agent_name']!r} (agent id {report['agent_id']})")
    if report["field_filter"] is not None:
        print(f"ticket field filter: {report['field_filter']} (value set)")
    print(f"assigned tickets (open, pending, or updated in the last {report['lookback_days']} days): {report['ticket_count']}")
    if report["server_ticket_count"] != report["ticket_count"]:
        print(f"server returned {report['server_ticket_count']}, {report['ticket_count']} matched the field filter")


def main() -> int:
    settings = get_settings()
    try:
        report = run_check(settings, transport=default_transport)
    except (FreshserviceError, SyncError) as error:
        # One branch, no prefix: every message these raise already names itself
        # ("Freshservice is not configured: missing ...", "Freshservice request failed
        # with status 401", "Freshservice agent lookup failed: ..."), so a prefix would
        # print the subject twice.
        print(str(error), file=sys.stderr)
        return 1
    _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
