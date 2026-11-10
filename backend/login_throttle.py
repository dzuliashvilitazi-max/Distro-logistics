"""Login brute-force protection shared by every backend instance through MongoDB.

Three independent counters per attempt: the client network, the (network, email) pair and the email alone.
Counters live in `login_throttle`, are updated atomically, and expire on their own (TTL index), so a block
is always temporary. Unknown and known emails are treated identically so nothing reveals whether an account exists.
"""
import ipaddress
import os
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Optional

from pymongo import ReturnDocument

_INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u200e\u200f\u2060\ufeff"), None)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def config() -> dict:
    def number(name: str, default: int) -> int:
        try:
            return max(0, int(os.environ.get(name, default)))
        except ValueError:
            return default
    return {
        "enabled": os.environ.get("LOGIN_RATE_LIMIT_ENABLED", "1") != "0",
        "max_per_ip": number("LOGIN_MAX_FAILURES_PER_IP", 30),
        "max_per_pair": number("LOGIN_MAX_FAILURES_PER_EMAIL_IP", 5),
        "max_per_email": number("LOGIN_MAX_FAILURES_PER_EMAIL", 15),
        "window": number("LOGIN_FAILURE_WINDOW_SECONDS", 900),
        "block": number("LOGIN_BLOCK_SECONDS", 900),
        "max_block": number("LOGIN_MAX_BLOCK_SECONDS", 3600),
        "proxy_hops": number("LOGIN_TRUSTED_PROXY_HOPS", 1),
    }


def normalize_email(value: str) -> str:
    """One canonical form so case, padding, full-width letters and invisible characters cannot dodge the counters."""
    return unicodedata.normalize("NFKC", str(value or "")).translate(_INVISIBLE).strip().casefold()


def client_network(forwarded_for: Optional[str], peer: Optional[str], proxy_hops: int) -> str:
    """Client address as seen by our own proxy. Only the entries our proxies appended (from the right) are trusted;
    anything the client put at the front of X-Forwarded-For is ignored. IPv6 clients are grouped by /64."""
    candidate = peer or ""
    parts = [p.strip() for p in (forwarded_for or "").split(",") if p.strip()]
    if parts and proxy_hops > 0:
        candidate = parts[-proxy_hops] if len(parts) >= proxy_hops else parts[0]
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return "unknown"
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped:
            return str(address.ipv4_mapped)
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address)


def _scopes(network: str, email: str, cfg: dict) -> list:
    return [
        (f"ip:{network}", cfg["max_per_ip"]),
        (f"pair:{network}|{email}", cfg["max_per_pair"]),
        (f"email:{email}", cfg["max_per_email"]),
    ]


async def blocked_seconds(db, network: str, email: str) -> int:
    """Seconds left on the longest active block for this attempt, or 0."""
    cfg = config()
    if not cfg["enabled"]:
        return 0
    now = _now()
    longest = 0
    for key, limit in _scopes(network, email, cfg):
        if not limit:
            continue
        doc = await db.login_throttle.find_one({"_id": key}, {"blocked_until": 1})
        until = (doc or {}).get("blocked_until")
        if until:
            remaining = (datetime.fromisoformat(until) - now).total_seconds()
            longest = max(longest, int(remaining) + 1 if remaining > 0 else 0)
    return longest


async def record_failure(db, network: str, email: str) -> None:
    cfg = config()
    if not cfg["enabled"]:
        return
    for key, limit in _scopes(network, email, cfg):
        if not limit:
            continue
        now = _now()
        now_iso = _iso(now)
        stale = await db.login_throttle.find_one({"_id": key})
        if stale and not (stale.get("blocked_until") or "") > now_iso and (
            datetime.fromisoformat(stale["window_start"]) + timedelta(seconds=cfg["window"]) <= now
        ):
            await db.login_throttle.delete_one({"_id": key, "window_start": stale["window_start"]})
        doc = await db.login_throttle.find_one_and_update(
            {"_id": key},
            {"$inc": {"failures": 1}, "$setOnInsert": {"window_start": now_iso, "blocks": 0},
             "$set": {"expires_at": now + timedelta(seconds=cfg["window"] + cfg["max_block"])}},
            upsert=True, return_document=ReturnDocument.AFTER,
        )
        if doc["failures"] < limit:
            continue
        duration = min(cfg["block"] * (2 ** int(doc.get("blocks", 0))), cfg["max_block"])
        until = now + timedelta(seconds=duration)
        await db.login_throttle.update_one(
            {"_id": key, "$or": [{"blocked_until": {"$exists": False}}, {"blocked_until": None},
                                  {"blocked_until": {"$lte": now_iso}}]},
            {"$set": {"blocked_until": _iso(until), "failures": 0, "window_start": now_iso,
                      "expires_at": until + timedelta(seconds=cfg["window"] + cfg["max_block"])},
             "$inc": {"blocks": 1}},
        )


async def record_success(db, network: str, email: str) -> None:
    """A correct password clears the email-level counters; the network counter keeps decaying on its own."""
    cfg = config()
    if cfg["enabled"]:
        await db.login_throttle.delete_many({"_id": {"$in": [f"pair:{network}|{email}", f"email:{email}"]}})
