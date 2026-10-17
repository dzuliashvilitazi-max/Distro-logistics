"""Sandbox payment gateway for Distro Logistics.

Stripe is unavailable for Georgia-based accounts, so this is a self-contained
SANDBOX gateway that mirrors real processor behaviour (Luhn + expiry + CVC
validation, a 1 GEL authorization hold on add-card, token-only storage, and
charge simulation). No real money moves. Swap these functions for a live
Georgian processor (e.g. TBC Merchant API) to go live.
"""
import uuid
from datetime import datetime, timezone


class CardError(Exception):
    pass


# Test cards that fail at specific stages (align with common processor test data).
DECLINE_ON_ADD = {"4000000000000002"}       # declined during validation hold
DECLINE_ON_CHARGE = {"4000000000000341"}    # saves fine, declines on later charge/auto-debit


def _digits(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


def luhn_ok(num: str) -> bool:
    total, parity = 0, len(num) % 2
    for i, ch in enumerate(num):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def card_brand(num: str) -> str:
    if num.startswith("4"):
        return "visa"
    if num[:2] in {"51", "52", "53", "54", "55"} or (num[:4].isdigit() and 2221 <= int(num[:4]) <= 2720):
        return "mastercard"
    if num[:2] in {"34", "37"}:
        return "amex"
    return "card"


def validate_card(number: str, exp: str, cvc: str) -> dict:
    num = _digits(number)
    if len(num) < 13 or len(num) > 19 or not luhn_ok(num):
        raise CardError("Invalid card number")
    e = _digits(exp)
    if len(e) != 4:
        raise CardError("Invalid expiry (use MM/YY)")
    mm, yy = int(e[:2]), int(e[2:])
    if mm < 1 or mm > 12:
        raise CardError("Invalid expiry month")
    now = datetime.now(timezone.utc)
    if (2000 + yy, mm) < (now.year, now.month):
        raise CardError("Card has expired")
    if len(_digits(cvc)) not in (3, 4):
        raise CardError("Invalid CVC")
    sim = "ok"
    if num in DECLINE_ON_ADD:
        sim = "decline_add"
    elif num in DECLINE_ON_CHARGE:
        sim = "charge_decline"
    return {"brand": card_brand(num), "last4": num[-4:], "exp": f"{mm:02d}/{yy:02d}", "sim_status": sim}


def gen_token() -> str:
    return "pm_sim_" + uuid.uuid4().hex[:24]


def simulate_hold(sim_status: str, amount: float) -> str:
    """1 GEL authorization hold on add-card, then released immediately by the caller."""
    if sim_status == "decline_add":
        raise CardError("Card was declined")
    return "hold_sim_" + uuid.uuid4().hex[:16]


def simulate_charge(sim_status: str, amount: float) -> str:
    if sim_status in ("decline_add", "charge_decline"):
        raise CardError("Card was declined")
    if amount <= 0:
        raise CardError("Invalid amount")
    return "ch_sim_" + uuid.uuid4().hex[:20]
