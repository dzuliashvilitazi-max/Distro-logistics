from decimal import Decimal

import pytest

import money


def test_float_artifacts_do_not_leak_into_totals():
    assert money.total_sum([0.1] * 10) == Decimal("1.00")
    assert 0.1 + 0.2 != 0.3  # the bug this module prevents (builtin sum() is compensated on Python 3.12+)


@pytest.mark.parametrize("value,expected", [("2.675", "2.68"), (2.675, "2.68"), ("1.005", "1.01"), (0.125, "0.13")])
def test_rounding_is_half_up(value, expected):
    assert money.q(value) == Decimal(expected)


def test_percent_and_average_use_half_up():
    assert money.percent_of(10.05, 5) == Decimal("0.50")
    assert money.percent_of(10.10, 5) == Decimal("0.51")
    assert money.divide(10, 3) == Decimal("3.33")
    assert money.divide(0, 0) is None  # undefined average is not 0


@pytest.mark.parametrize("bad", [None, "abc", float("nan"), float("inf"), True])
def test_invalid_amounts_raise(bad):
    with pytest.raises(money.MoneyError):
        money.q(bad)


def test_order_fee_precedence_and_external():
    assert money.order_fee({"total": 100, "commission_amount": 7, "service_fee": 5}) == Decimal("7.00")
    assert money.order_fee({"total": 100, "service_fee": 5}) == Decimal("5.00")
    assert money.order_fee({"total": 100.10}) == Decimal("5.01")
    assert money.order_fee({"total": 100, "service_fee": 5, "external_order": True}) == Decimal("0.00")
    assert money.order_fee({"total": 100, "service_fee": 5, "source": "external"}) == Decimal("0.00")


def test_platform_day_uses_tbilisi_time():
    # 21:30 UTC on Jan 31 is already Feb 1 in Asia/Tbilisi (UTC+4)
    assert money.to_platform_day("2026-01-31T21:30:00+00:00") == "2026-02-01"
    assert money.to_platform_month("2026-01-31T21:30:00+00:00") == "2026-02"
    assert money.to_platform_day("not a date") is None
    assert money.to_platform_day(None) is None
