import pytest
from fastapi import HTTPException

import server


def test_analytics_date_range_uses_inclusive_local_dates_with_exclusive_utc_end():
    date_range = server._analytics_date_range("2026-06-01", "2026-06-02")
    query = server._analytics_date_query("created_at", date_range)

    assert query == {"created_at": {
        "$gte": "2026-05-31T20:00:00+00:00",
        "$lt": "2026-06-02T20:00:00+00:00",
    }}


def test_analytics_date_range_accepts_single_bound():
    query = server._analytics_date_query(
        "created_at", server._analytics_date_range("2026-06-01", None),
    )
    assert query == {"created_at": {"$gte": "2026-05-31T20:00:00+00:00"}}


@pytest.mark.parametrize("start,end", [
    ("2026-6-01", "2026-06-02"),
    ("2026-06-03", "2026-06-02"),
    (None, "not-a-date"),
])
def test_analytics_date_range_rejects_invalid_or_incomplete_values(start, end):
    with pytest.raises(HTTPException):
        server._analytics_date_range(start, end)