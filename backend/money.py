"""Exact money arithmetic: every financial figure goes through Decimal with one rounding rule and one timezone."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
PLATFORM_TZ = ZoneInfo("Asia/Tbilisi")  # day/month boundaries for every report and export
DEFAULT_COMMISSION_RATE = Decimal("5")  # percent, used only when an order has no recorded fee


class MoneyError(ValueError):
    """A stored amount is missing or not a finite number."""


def dec(value) -> Decimal:
    """Convert via str() so a float like 0.1 becomes exactly 0.1, never its binary expansion."""
    if isinstance(value, Decimal):
        result = value
    else:
        if value is None or isinstance(value, bool):
            raise MoneyError(f"Invalid amount: {value!r}")
        try:
            result = Decimal(str(value).strip())
        except InvalidOperation as exc:
            raise MoneyError(f"Invalid amount: {value!r}") from exc
    if not result.is_finite():
        raise MoneyError(f"Invalid amount: {value!r}")
    return result


def q(value) -> Decimal:
    return dec(value).quantize(CENT, rounding=ROUND_HALF_UP)


def amount_or_zero(value) -> Decimal:
    """Only for fields where an absent value genuinely means 0 (e.g. an optional discount)."""
    return ZERO if value is None else q(value)


def total_sum(values: Iterable) -> Decimal:
    """Sum of per-item values, each rounded to cents first, so totals always equal the sum of displayed rows."""
    result = ZERO
    for value in values:
        result += q(value)
    return result


def percent_of(amount, percent) -> Decimal:
    return (dec(amount) * dec(percent) / Decimal(100)).quantize(CENT, rounding=ROUND_HALF_UP)


def divide(numerator, denominator) -> Optional[Decimal]:
    """None (not 0) when the average is undefined."""
    denominator = dec(denominator)
    if denominator == 0:
        return None
    return (dec(numerator) / denominator).quantize(CENT, rounding=ROUND_HALF_UP)


def as_json(value: Optional[Decimal]):
    """Serialise an already-rounded Decimal; None stays None so clients can tell 'unknown' from 0."""
    return None if value is None else float(q(value))


def order_fee(order: dict) -> Decimal:
    """Single commission formula: recorded commission_amount, else recorded service_fee, else the default rate."""
    if order.get("source") == "external" or order.get("external_order"):
        return ZERO
    for field in ("commission_amount", "service_fee"):
        if order.get(field) is not None:
            return q(order[field])
    return percent_of(order.get("total"), DEFAULT_COMMISSION_RATE)


def to_platform_day(iso_value) -> Optional[str]:
    """YYYY-MM-DD in platform time; None when the timestamp is missing or unparseable."""
    parsed = _parse(iso_value)
    return parsed.astimezone(PLATFORM_TZ).date().isoformat() if parsed else None


def to_platform_month(iso_value) -> Optional[str]:
    day = to_platform_day(iso_value)
    return day[:7] if day else None


def platform_day_start_utc(day) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=PLATFORM_TZ).astimezone(timezone.utc)


def _parse(iso_value) -> Optional[datetime]:
    if not iso_value:
        return None
    try:
        parsed = datetime.fromisoformat(str(iso_value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
