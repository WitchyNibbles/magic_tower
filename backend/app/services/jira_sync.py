"""Jira sync handler: turns the participation window into ``Source`` rows.

Registered under ``"jira"`` (``SourceKind.jira``, ``app/models.py``) the same way
``app/services/sync.py`` registers ``"graph"`` for Microsoft Graph -- importing
this module is the one side effect that makes the kind reachable, which is why
``app/main.py`` imports it even though nothing here is called directly from a
route.

Reuses the generic pieces the Graph handler already proved: ``persist_signals``
stores a normalized signal as a ``Source`` idempotently, and ``promote_signals``
decides which of them belong in the actionable queue. Every issue the
participation window returns is stored and browsable; only the ones assigned to
the owner are promoted (AC7), which ``promotion.should_promote`` decides through
its Jira rule. Reporter, creator, watcher and voter involvement is followed, not
owed, so it stays out of the queue.

**Who the owner is.** The account the configured API token belongs to, named by
its Atlassian ``accountId`` and read from ``GET /rest/api/3/myself`` once per
sync (:func:`_owner_account_id`). Nothing in this application persists an owner
identity, and Jira reports an assignee as an ``accountId`` rather than an email,
so ``JIRA_ACCOUNT_EMAIL`` cannot be compared against ``fields.assignee``. The
token owner is also what ``currentUser()`` in ``JIRA_PARTICIPATION_JQL`` already
means, so this recognises the owner by the same account that chose the window.
The lookup is not a new setting for the owner to fill in, and it fails closed:
an unreachable or unrecognisable ``/myself`` promotes nothing at all.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from ..config import Settings
from ..integrations.jira import JiraClient, JiraError
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

    ``assignee_account_id`` is the one Jira-shaped field promotion reads (AC7). It
    is carried on the signal and not into a new column: ``sources`` is pinned to
    its exact column set (``alembic/versions/0001_initial_schema.py``), and the
    verdict this field produces is already durable in ``source_promotions`` and
    ``work_items``. The cost is that a backfill, which rebuilds signals from stored
    rows alone, cannot re-decide a Jira source on its merits and declines it.
    ``fields.assignee`` is ``null`` on an unassigned issue -- a present, empty key
    -- so the ``or {}`` is what keeps this from raising on one.

    ``issue_key`` carries the human-readable key alongside, for the same reason
    ``assignee_account_id`` rides here rather than in a column: it is what matches
    this issue against the notification mail announcing it
    (``app/services/jira_dedupe.py``), and mail knows the key, never the numeric id.
    """
    fields = issue.get("fields") or {}
    key = issue.get("key")
    return {
        "external_id": f"{JIRA_SOURCE_KIND}:{issue.get('id')}",
        "source_kind": JIRA_SOURCE_KIND,
        "title": fields.get("summary") or FALLBACK_TITLE,
        "source_url": f"{base_url}/browse/{key}" if key else None,
        "observed_at": fields.get("updated"),
        "assignee_account_id": (fields.get("assignee") or {}).get("accountId"),
        "issue_key": key,
    }


def _owner_account_id(client: JiraClient) -> str | None:
    """The ``accountId`` of the account the configured API token belongs to, or
    ``None`` when Jira will not say.

    ``JiraError`` is swallowed on purpose, and only here. The issues have already
    been fetched by the time this is called, and a ``/myself`` that errors is no
    reason to throw them away or fail the sync -- they are still stored and
    browsable. It is every reason not to promote any of them: ``should_promote``'s
    Jira rule reads ``None`` as an unrecognised owner and declines, so a failed
    lookup costs the queue recall for one sync rather than filling it with issues
    nobody checked.

    A JSON *object* with no ``accountId`` needs no handling of its own here: it
    yields the same ``None`` the error path returns, and the rule treats it the
    same. A 200 whose body is not an object at all is **not** handled -- ``.get``
    raises ``AttributeError`` and the sync fails after the issues were stored.
    Promotion stays closed either way; what is unproven is the sync surviving it.
    """
    try:
        return client.myself().get("accountId")
    except JiraError:
        return None


def _fetch_issue_signals(client: JiraClient) -> list[dict[str, Any]]:
    """Every participation issue, normalized and de-duplicated by ``external_id``
    -- mirrors ``app/services/graph.py:fetch_signals``'s dedup. The JQL's ``OR``
    clauses are a set union and cannot themselves yield a duplicate. What is not
    ruled out is the cursor walk in ``search_participation_issues``: ``/search/jql``
    offers no cross-page consistency guarantee, and the ``updated >= -15m`` window
    is re-evaluated per request, so the same ``id`` can arrive on two pages. Which
    pagination mechanism would do that is not established here -- the dedup is
    defensive, and the test pins the handling, not the cause."""
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
    promoted = promote_signals(db, signals, owner_account_id=_owner_account_id(jira)) if db is not None else 0
    return {"mode": "read-only", "synced_at": datetime.now(UTC).isoformat(), "count": len(signals),
            "new_sources": created, "new_work_items": promoted}


register_sync_handler(JIRA_SOURCE_KIND, _sync_jira)
