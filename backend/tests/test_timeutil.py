from datetime import UTC, datetime, timedelta, timezone

from app.services.timeutil import as_utc


def test_a_naive_value_is_taken_as_utc():
    assert as_utc(datetime(2026, 1, 2, 3, 4)) == datetime(2026, 1, 2, 3, 4, tzinfo=UTC)


def test_an_aware_value_is_converted_to_utc():
    moment = datetime(2026, 1, 2, 3, 4, tzinfo=timezone(timedelta(hours=2)))

    converted = as_utc(moment)

    assert converted == moment
    assert converted.utcoffset() == timedelta(0)
    assert converted.hour == 1
