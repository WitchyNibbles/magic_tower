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

**Management visibility (T09, AC10).** ``JIRA_MANAGEMENT_PROJECT_KEY`` -- read
here from ``Settings.jira_management_project_key``, never a new column on
``sources`` (``alembic/versions/0001_initial_schema.py`` pins that set) -- names
one project a sync also fetches from, through
``JiraClient.search_project_issues``, alongside the participation window. That
fetch is not the whole project: it is capped at the 2000 most recently updated
issues. Past that it stops, logs a WARNING, and the sync envelope reports
``truncated`` (also set when the participation search hit its cap). Every
issue it does return is stored and browsable the same way, and never promoted
on that ground alone: the assignee rule above is the only thing that decides a
Jira signal either way, so an issue assigned to the owner still
promotes once even when the project fetch is the only query that found it. The
setting is optional; when it is unset, this call is skipped and nothing about
the participation-only sync changes.

**Who the owner is.** The account the configured API token belongs to, named by
its Atlassian ``accountId`` and read from ``GET /rest/api/3/myself`` once per
sync (:func:`_owner_account_id`). Nothing in this application persists an owner
identity, and Jira reports an assignee as an ``accountId`` rather than an email,
so ``JIRA_ACCOUNT_EMAIL`` cannot be compared against ``fields.assignee``. The
token owner is also what ``currentUser()`` in the participation query already
means, so this recognises the owner by the same account that chose the window.
The lookup is not a new setting for the owner to fill in, and it fails closed:
an unreachable or unrecognisable ``/myself`` promotes nothing at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from ..config import Settings
from ..integrations.jira import JiraClient, JiraError, extract_adf_plain_text
from .graph import persist_signals, single_line_excerpt
from .promotion import promote_signals
from .sync import SyncError
from .sync_cursor import last_success, record_success
from .sync_registry import register_sync_handler

JIRA_SOURCE_KIND = "jira"
FALLBACK_TITLE = "(no summary)"
# Extra minutes searched beyond the gap since the last success. Jira's search index
# is eventually consistent (seconds to minutes), so an issue updated just before the
# previous sync started may only have become searchable after it ran; the overlap
# lets the next sync catch it. Re-fetching an issue is harmless (``persist_signals``
# is idempotent).
WINDOW_OVERLAP_MINUTES = 5


def _utc_now() -> datetime:
    return datetime.now(UTC)


def lookback_window_minutes(lookback_days: int) -> int:
    """The whole lookback, in minutes: what a first sync (and ``jira_check``) searches."""
    return lookback_days * 1440


def participation_window_minutes(last_success_at: datetime | None, now: datetime, lookback_days: int) -> int:
    """How many minutes back the participation search should look.

    The whole lookback with no cursor (the first sync). Otherwise the minutes since
    the last successful sync started, rounded up, plus :data:`WINDOW_OVERLAP_MINUTES`
    -- but never more than the lookback, so a long outage cannot ask Jira for years
    of history. A cursor in the future means the clock stepped back, so how long
    ago the last sync really was is unknown: the whole lookback is searched rather
    than a window that could miss what changed in the meantime.

    The result is a *duration*, not a timestamp: ``participation_jql`` sends it as
    ``updated >= -{N}m``, which Jira measures from its own clock in the owner's
    profile timezone, so nothing here depends on the timezone of either side.
    """
    lookback_minutes = lookback_window_minutes(lookback_days)
    if last_success_at is None or last_success_at > now:
        return lookback_minutes
    gap = now - last_success_at
    minutes_since = -(-gap // timedelta(minutes=1))  # ceiling division
    return min(minutes_since + WINDOW_OVERLAP_MINUTES, lookback_minutes)


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
        "excerpt": single_line_excerpt(extract_adf_plain_text(fields.get("description"))),
        "source_url": f"{base_url}/browse/{key}" if key else None,
        "observed_at": fields.get("updated"),
        "assignee_account_id": (fields.get("assignee") or {}).get("accountId"),
        "issue_key": key,
    }


def _owner_account_id(client: JiraClient) -> str | None:
    """The ``accountId`` of the account the configured API token belongs to, or
    ``None`` when Jira will not say.

    ``JiraError`` is swallowed on purpose, and only here (the search's own is turned
    into a ``SyncError`` by :func:`_sync_jira`). The issues have already
    been fetched by the time this is called, and a ``/myself`` that errors is no
    reason to throw them away or fail the sync -- they are still stored and
    browsable. It is every reason not to promote any of them: ``should_promote``'s
    Jira rule reads ``None`` as an unrecognised owner and declines, so a failed
    lookup costs the queue recall for one sync rather than filling it with issues
    nobody checked. It is also a reason not to move the sync cursor
    (:func:`_sync_jira`): the window was fetched but never judged, so the next
    sync must cover it again.

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


def _fetch_issue_signals(client: JiraClient, window_minutes: int, project_key: str | None = None) -> tuple[list[dict[str, Any]], bool]:
    """The signals, and whether either search hit its page cap.

    Every participation issue in the last ``window_minutes`` minutes, plus the capped project fetch
    (:meth:`JiraClient.search_project_issues`, at most the 2000 most recently
    updated issues) when ``project_key`` is configured (T09, AC10), normalized
    and de-duplicated by ``external_id`` --
    mirrors ``app/services/graph.py:fetch_signals``'s dedup. The JQL's ``OR``
    clauses are a set union and cannot themselves yield a duplicate. What is not
    ruled out is the cursor walk in ``search_participation_issues``: ``/search/jql``
    offers no cross-page consistency guarantee, and the ``updated >= -{N}m`` window
    is re-evaluated per request, so the same ``id`` can arrive on two pages. Which
    pagination mechanism would do that is not established here -- the dedup is
    defensive, and the test pins the handling, not the cause.

    An issue both assigned to the owner and inside the visible project may arrive
    from either query, or from only one. ``participation_jql`` bounds all of
    its clauses, ``assignee = currentUser()`` included, with ``AND updated >= -{N}m``
    (``app/integrations/jira.py``); the project clause carries no such window. So an
    owner-assigned issue last updated outside that window is returned by the project
    fetch alone, and the copy ``setdefault`` keeps is then the project copy -- the
    project fetch is not merely a duplicate of something participation already found.
    That costs the promotion decision nothing either way: both queries ask ``_search``
    for the same ``JIRA_SEARCH_FIELDS``, so both copies normalize to the same
    ``assignee_account_id``, and ``promotion.should_promote``'s Jira rule reads that
    field on whichever copy survives dedup rather than which query merged it.
    Dedup is what keeps it to one promotion; the assignee is what makes it a
    promotion at all (``backend/tests/test_jira_project_visibility.py``).
    """
    participation = client.search_participation_issues(window_minutes)
    issues = list(participation)
    truncated = participation.truncated
    if project_key:
        project = client.search_project_issues(project_key)
        issues.extend(project)
        truncated = truncated or project.truncated
    rows = [_normalize_issue(issue, client.base_url) for issue in issues]
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        deduped.setdefault(row["external_id"], row)
    return list(deduped.values()), truncated


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

    A ``JiraError`` while building the client or searching is raised as a
    ``SyncError`` with the same message, so ``POST /api/sync?kind=jira`` answers 409
    with the reason and ``sync_ready_sources`` reports it without a traceback.
    """
    errors = settings.jira_configuration_errors()
    if errors:
        raise SyncError(f"Jira is not configured: missing {', '.join(errors)}")
    started = _utc_now()
    previous = last_success(db, JIRA_SOURCE_KIND) if db is not None else None
    window_minutes = participation_window_minutes(previous, started, settings.jira_sync_lookback_days)
    try:
        jira = jira_client or JiraClient.from_settings(settings)
        signals, truncated = _fetch_issue_signals(jira, window_minutes, settings.jira_management_project_key)
    except JiraError as error:
        # ``JiraError`` messages are written to be shown (no URL, header or token), so
        # the owner gets the reason; as a ``SyncError`` it is a known failure, not a bug.
        raise SyncError(str(error)) from error
    created = promoted = 0
    if db is not None:
        created = persist_signals(db, signals)
        owner_account_id = _owner_account_id(jira)
        promoted = promote_signals(db, signals, owner_account_id=owner_account_id)
        if owner_account_id is not None:
            # The cursor is when this sync *started*, and only a sync that got this far
            # moves it: anything updated while it ran lands in the next window, and a
            # raised error above leaves the old cursor so the retry covers the same gap.
            # Without the owner's id nothing could be judged for promotion, so the window
            # is not covered either: the cursor stays and the next sync re-fetches it.
            record_success(db, JIRA_SOURCE_KIND, started)
    return {"mode": "read-only", "synced_at": _utc_now().isoformat(), "count": len(signals),
            "new_sources": created, "new_work_items": promoted, "window_minutes": window_minutes, "truncated": truncated}


register_sync_handler(JIRA_SOURCE_KIND, _sync_jira, ready=lambda settings: not settings.jira_configuration_errors())
