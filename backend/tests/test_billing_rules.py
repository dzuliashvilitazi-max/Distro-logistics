from datetime import datetime, timedelta, timezone

import server


def inv(amount, days_overdue, status="pending"):
    due = datetime.now(timezone.utc) - timedelta(days=days_overdue)
    return {"id": "i", "amount": amount, "status": status, "due_date": due.isoformat()}


def test_default_blocks_on_any_overdue():
    assert server.billing_should_freeze([inv(10, 1)], {}) is True


def test_paid_or_not_due_never_blocks():
    assert server.billing_should_freeze([inv(10, 5, "paid"), inv(10, -3)], {}) is False


def test_amount_limit_rule():
    settings = {"billing_overdue_limit": 100}
    assert server.billing_should_freeze([inv(60, 2)], settings) is False
    assert server.billing_should_freeze([inv(60, 2), inv(50, 1)], settings) is True


def test_days_rule():
    settings = {"billing_overdue_days": 7}
    assert server.billing_should_freeze([inv(500, 3)], settings) is False
    assert server.billing_should_freeze([inv(5, 8)], settings) is True
