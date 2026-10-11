from datetime import UTC

from app.services.graph import parse_observed_at


def test_observed_at_is_utc_when_graph_gives_a_timestamp() -> None:
    assert parse_observed_at("2026-10-11T08:30:00Z").utcoffset().total_seconds() == 0


def test_observed_at_falls_back_to_the_current_utc_time_not_local_time() -> None:
    """A naive local ``now`` would sort out of place among Graph's UTC timestamps."""
    for missing in (None, "", "not a timestamp"):
        assert parse_observed_at(missing).tzinfo is UTC
