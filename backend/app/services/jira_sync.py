"""Jira sync handler: turns the participation window into ``Source`` rows.

Registered under ``"jira"`` (``SourceKind.jira``, ``app/models.py``) the same way
``app/services/sync.py`` registers ``"graph"`` for Microsoft Graph -- importing
this module is the one side effect that makes the kind reachable, which is why
``app/main.py`` imports it even though nothing here is called directly from a
route.

Reuses the generic pieces the Graph handler already proved: ``persist_signals``
stores a normalized signal as a ``Source`` idempotently, and ``promote_signals``
decides which of them belong in the actionable queue. Promotion here is
deliberately still the *email* heuristic (``app/services/promotion.py``), which
has nothing Jira-shaped to read on a Jira signal -- no sender, no headers, no
recipients -- and so promotes every fetched issue unconditionally through its
last, permissive rule. That is a known, temporary overreach: restricting
promotion to only the issues actually assigned to the owner is T07's job, not
this task's (``.companion/plan.md``, T07 depends on T06). This handler's own
job is narrower: fetch, normalize, store, and dispatch through the same
envelope every other registered kind returns.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from ..config import Settings
from ..integrations.jira import JiraClient
from .graph import persist_signals
from .promotion import promote_signals
from .sync import SyncError
from .sync_registry import register_sync_handler

JIRA_SOURCE_KIND = "jira"
FALLBACK_TITLE = "(no summary)"


def _normalize_issue(issue: dict[str, Any], base_url: str) -> dict[str, Any]:
    """One Jira issue (as ``search_participation_issues`` returns it) into the
    normalized signal shape ``persist_signals``/``promote_signals`` already know,
    the same shape ``app/services/graph.py:normalize_email`` builds for mail.

    ``external_id`` follows the existing ``"kind:{id}"`` convention (``jira:{id}``,
    parallel to ``outlook:{id}``) -- Jira's numeric ``id`` is used rather than its
    human-editable ``key``, which a project rename or a moved issue can change.
    """
    fields = issue.get("fields") or {}
    key = issue.get("key")
    return {
        "external_id": f"{JIRA_SOURCE_KIND}:{issue.get('id')}",
        "source_kind": JIRA_SOURCE_KIND,
        "title": fields.get("summary") or FALLBACK_TITLE,
        "source_url": f"{base_url}/browse/{key}" if key else None,
        "observed_at": fields.get("updated"),
    }


def _fetch_issue_signals(client: JiraClient) -> list[dict[str, Any]]:
    """Every participation issue, normalized and de-duplicated by ``external_id``
    -- mirrors ``app/services/graph.py:fetch_signals``'s dedup. The JQL's ``OR``
    clauses are a set union and cannot themselves yield a duplicate; what can is
    the cursor walk in ``search_participation_issues``, whose pages are ordered
    by ``updated`` -- an issue updated between two page reads moves back to the
    front of that ordering and is handed out on both."""
    rows = [_normalize_issue(issue, client.base_url) for issue in client.search_participation_issues()]
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        deduped.setdefault(row["external_id"], row)
    return list(deduped.values())


def _sync_jira(settings: Settings, db: Session | None = None, limit: int = 50, client: Any = None,
               jira_client: JiraClient | None = None, **_: Any) -> dict[str, Any]:
    """The Jira counterpart to ``app/services/sync.py:_sync_graph``.

    ``client`` is the Graph-only kwarg ``sync()`` always forwards
    (``app/services/sync.py:79``); it is accepted so dispatch never has to know
    which handler it is calling, and ignored here because it is never a
    ``JiraClient``. ``limit`` is accepted for the same reason -- the participation
    query is bounded by ``JIRA_SEARCH_MAX_PAGES``, not by a caller-supplied count.
    Tests inject a stub transport through ``jira_client`` instead, the same seam
    ``JiraClient.from_settings``'s own ``transport`` parameter offers.
    """
    errors = settings.jira_configuration_errors()
    if errors:
        raise SyncError(f"Jira is not configured: missing {', '.join(errors)}")
    jira = jira_client or JiraClient.from_settings(settings)
    signals = _fetch_issue_signals(jira)
    created = persist_signals(db, signals) if db is not None else 0
    promoted = promote_signals(db, signals) if db is not None else 0
    return {"mode": "read-only", "synced_at": datetime.now(UTC).isoformat(), "count": len(signals),
            "new_sources": created, "new_work_items": promoted}


register_sync_handler(JIRA_SOURCE_KIND, _sync_jira)
