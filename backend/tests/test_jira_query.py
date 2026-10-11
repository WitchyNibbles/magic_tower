"""AC8: the participation query -- the five-clause JQL that finds every issue the
token owner is involved in, bounded pagination through ``nextPageToken`` on
``/rest/api/3/search/jql`` (the old ``/rest/api/3/search`` is removed and stays
removed -- CHANGE-2046), explicit ``fields`` (this endpoint defaults to ``id``
alone), and plain-text extraction from Atlassian Document Format descriptions.

Each rule is falsified individually: dropping a JQL clause, a required field, the
page bound, or the ``nextPageToken`` check reddens exactly the test that pins it.
No test here reaches the network -- everything goes through the injectable
transport from ``app/integrations/jira.py`` (mirrors ``app/integrations/graph.py``).
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

import app.integrations.jira as jira_module
from app.integrations.jira import (
    JIRA_PARTICIPATION_JQL,
    JIRA_SEARCH_FIELDS,
    JIRA_SEARCH_MAX_PAGES,
    JiraClient,
    extract_adf_plain_text,
)


def _client(transport):
    return JiraClient("https://example.atlassian.net", "owner@example.com", "token", transport=transport)


def test_jira_query_participation_jql_is_the_bounded_five_clause_query() -> None:
    assert JIRA_PARTICIPATION_JQL == (
        "(assignee = currentUser() OR reporter = currentUser() OR creator = currentUser() "
        "OR watcher = currentUser() OR voter = currentUser()) AND updated >= -15m "
        "ORDER BY updated DESC"
    )


@pytest.mark.parametrize(
    "clause",
    [
        "assignee = currentUser()",
        "reporter = currentUser()",
        "creator = currentUser()",
        "watcher = currentUser()",
        "voter = currentUser()",
    ],
)
def test_jira_query_participation_jql_contains_each_user_clause(clause: str) -> None:
    assert clause in JIRA_PARTICIPATION_JQL


def test_jira_query_participation_jql_is_bounded_by_a_relative_updated_window() -> None:
    """An absolute watermark would need the token owner's Jira profile timezone
    (not UTC) to compare correctly; a relative window sidesteps that entirely."""
    assert "updated >= -15m" in JIRA_PARTICIPATION_JQL


def test_jira_query_participation_jql_orders_by_updated_descending() -> None:
    assert JIRA_PARTICIPATION_JQL.endswith("ORDER BY updated DESC")


def test_jira_query_requests_the_search_jql_endpoint_not_the_removed_one() -> None:
    calls: list[str] = []

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        calls.append(url)
        return {"issues": []}

    _client(transport).search_participation_issues()

    assert len(calls) == 1
    parsed = urlparse(calls[0])
    assert parsed.path == "/rest/api/3/search/jql"


def test_jira_query_sends_the_participation_jql_as_a_query_parameter() -> None:
    calls: list[str] = []

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        calls.append(url)
        return {"issues": []}

    _client(transport).search_participation_issues()

    query = parse_qs(urlparse(calls[0]).query)
    assert query["jql"] == [JIRA_PARTICIPATION_JQL]


def test_jira_query_requests_fields_explicitly_instead_of_the_id_only_default() -> None:
    assert JIRA_SEARCH_FIELDS == ("summary", "status", "priority", "assignee", "reporter", "updated", "project")

    calls: list[str] = []

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        calls.append(url)
        return {"issues": []}

    _client(transport).search_participation_issues()

    query = parse_qs(urlparse(calls[0]).query)
    assert query["fields"] == [",".join(JIRA_SEARCH_FIELDS)]


def test_jira_query_follows_next_page_token_to_a_second_request() -> None:
    calls: list[str] = []

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        calls.append(url)
        query = parse_qs(urlparse(url).query)
        if "nextPageToken" not in query:
            return {"issues": [{"id": "1"}], "nextPageToken": "page-2"}
        assert query["nextPageToken"] == ["page-2"]
        return {"issues": [{"id": "2"}]}

    issues = _client(transport).search_participation_issues()

    assert len(calls) == 2
    assert [issue["id"] for issue in issues] == ["1", "2"]


def test_jira_query_stops_paging_once_a_response_has_no_next_page_token() -> None:
    calls: list[str] = []

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        calls.append(url)
        return {"issues": [{"id": "only"}]}

    issues = _client(transport).search_participation_issues()

    assert len(calls) == 1
    assert [issue["id"] for issue in issues] == ["only"]


def test_jira_query_ignores_total_and_start_at_and_uses_only_the_page_token() -> None:
    """This endpoint returns neither ``total`` nor ``startAt``; a response that
    smuggles them in with no ``nextPageToken`` must still be treated as the last
    page, not read for a count or an offset."""
    calls: list[str] = []

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        calls.append(url)
        return {"issues": [{"id": "1"}], "total": 999999, "startAt": 50}

    issues = _client(transport).search_participation_issues()

    assert len(calls) == 1
    assert [issue["id"] for issue in issues] == ["1"]


def test_jira_query_pagination_is_bounded_against_an_endless_next_page_token() -> None:
    """A server (buggy or worse) that always returns a ``nextPageToken`` must not
    be able to page this client forever."""
    call_count = 0

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        nonlocal call_count
        call_count += 1
        return {"issues": [], "nextPageToken": "always-more"}

    _client(transport).search_participation_issues()

    assert call_count == JIRA_SEARCH_MAX_PAGES


def test_jira_query_search_never_reaches_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_: object, **__: object) -> object:
        raise AssertionError("urlopen must never be called from a test")

    monkeypatch.setattr(jira_module, "urlopen", forbidden)

    _client(lambda *_: {"issues": []}).search_participation_issues()


def test_jira_query_extracts_plain_text_from_nested_adf_content() -> None:
    document = {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Top level."}]},
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": "Nested item."}]}
                        ],
                    }
                ],
            },
        ],
    }

    assert extract_adf_plain_text(document) == "Top level. Nested item."


def test_jira_query_extract_plain_text_returns_none_for_a_missing_description() -> None:
    assert extract_adf_plain_text(None) is None


def test_jira_query_treats_a_null_issues_array_as_empty_instead_of_erroring() -> None:
    """A malformed ``{"issues": null}`` response must not raise a bare ``TypeError``
    out of the connector's own exception hierarchy -- a caller wrapping a sync in
    ``except JiraError`` (T06) would not catch it."""

    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        return {"issues": None}

    issues = _client(transport).search_participation_issues()

    assert issues == []
