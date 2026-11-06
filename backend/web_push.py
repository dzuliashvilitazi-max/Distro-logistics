"""Web Push (VAPID) delivery for in-app notifications.

Keys come from VAPID_PRIVATE_KEY / VAPID_PUBLIC_KEY when configured; otherwise a key pair is generated
once and persisted in the `push_config` collection so every worker and restart shares the same identity.
"""
import asyncio
import base64
import hashlib
import json
import logging
import os
import re
from typing import Optional
from urllib.parse import quote

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid01
from pywebpush import WebPushException, webpush

logger = logging.getLogger("distro.push")

NEGOTIATION_TYPES = {"negotiation_request", "negotiation_counter", "negotiation_rejected", "negotiation_accepted"}
CONNECTION_TYPES = {"connection_request", "connection_approved", "connection_declined", "connection_removed"}

PUSH_TITLES = {
    "negotiation_request": "ფასის მოთხოვნა",
    "negotiation_counter": "საპასუხო შეთავაზება",
    "negotiation_accepted": "ფასზე შეთანხმება",
    "negotiation_rejected": "ფასის მოთხოვნა უარყოფილია",
    "product_offer": "სპეციალური შეთავაზება",
    "connection_request": "პარტნიორობის მოთხოვნა",
    "connection_approved": "პარტნიორობა დადასტურდა",
    "connection_declined": "პარტნიორობა უარყოფილია",
    "connection_removed": "პარტნიორობა გაუქმდა",
    "order": "შეკვეთა",
    "broadcast": "მნიშვნელოვანი შეტყობინება",
    "message": "ახალი შეტყობინება",
    "support": "მხარდაჭერის პასუხი",
}

_vapid_cache: Optional[tuple] = None
_tasks: set = set()


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _public_key_b64(vapid: Vapid01) -> str:
    raw = vapid.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint,
    )
    return _b64url(raw)


def _normalize_public_key(value: str) -> str:
    return value.strip().rstrip("=").replace("+", "-").replace("/", "_")


def _vapid_subject() -> str:
    subject = os.environ.get("VAPID_SUBJECT", "").strip()
    if not subject:
        subject = os.environ.get("VAPID_CLAIM_EMAIL", "admin@distro.local").strip()
    if subject.startswith("mailto:") or subject.startswith("https://"):
        return subject
    if ":" in subject or not subject:
        raise ValueError("VAPID_SUBJECT must be a mailto: address or HTTPS URL.")
    return f"mailto:{subject}"


async def get_vapid(db) -> tuple:
    """Return (Vapid01 signer, public application-server key as base64url)."""
    global _vapid_cache
    if _vapid_cache:
        return _vapid_cache
    private = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    if private:
        vapid = Vapid01.from_pem(private.replace("\\n", "\n").encode()) if "BEGIN" in private \
            else Vapid01.from_string(private)
    else:
        doc = await db.push_config.find_one({"id": "vapid"}, {"_id": 0})
        if not doc:
            fresh = Vapid01()
            fresh.generate_keys()
            await db.push_config.update_one(
                {"id": "vapid"},
                {"$setOnInsert": {"id": "vapid", "private_pem": fresh.private_pem().decode()}},
                upsert=True,
            )
            doc = await db.push_config.find_one({"id": "vapid"}, {"_id": 0})
        vapid = Vapid01.from_pem(doc["private_pem"].encode())
    public_key = _public_key_b64(vapid)
    configured_public_key = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
    if configured_public_key and _normalize_public_key(configured_public_key) != _normalize_public_key(public_key):
        logger.error("VAPID_PUBLIC_KEY does not match the public key derived from the configured private key.")
        raise RuntimeError("VAPID_PUBLIC_KEY does not match VAPID_PRIVATE_KEY.")
    subject = _vapid_subject()
    logger.info(
        "VAPID signer ready source=%s public_key_configured=%s subject_scheme=%s",
        "environment" if private else "database",
        bool(configured_public_key),
        subject.split(":", 1)[0],
    )
    _vapid_cache = (vapid, public_key)
    return _vapid_cache


def push_url(notification: dict, role: str) -> str:
    """Deep link opened when the user taps the push notification."""
    ntype = notification.get("type")
    if ntype in NEGOTIATION_TYPES and notification.get("negotiation_id"):
        base = "/supplier/price-negotiations" if role == "supplier" else "/store/price-negotiations"
        return f"{base}?negotiation_id={quote(notification['negotiation_id'], safe='')}"
    distributor_id = notification.get("distributor_id")
    product_id = notification.get("product_id")
    if ntype == "product_offer" and role == "retailer" and distributor_id and product_id:
        return f"/catalog?distributor_id={quote(distributor_id, safe='')}&product_id={quote(product_id, safe='')}"
    if ntype in CONNECTION_TYPES:
        return "/distributor/stores" if role == "supplier" else "/store/distributors"
    if notification.get("order_id"):
        base = {"supplier": "/supplier/orders", "admin": "/admin/orders"}.get(role, "/orders")
        return f"{base}?order={quote(notification['order_id'], safe='')}"
    if notification.get("invoice_id") and role == "supplier":
        return f"/supplier/invoices?invoice={quote(notification['invoice_id'], safe='')}"
    if ntype == "approval" and role == "admin":
        return "/admin/users"
    if ntype in {"message", "broadcast"}:
        return "/messages"
    if ntype == "support":
        return "/admin/support" if role == "admin" else "/support"
    return {"supplier": "/supplier/orders", "admin": "/admin/orders"}.get(role, "/orders")


def _subscription_ref(subscription: dict) -> str:
    endpoint = str(subscription.get("endpoint", ""))
    return hashlib.sha256(endpoint.encode()).hexdigest()[:12] if endpoint else "missing"


def _safe_push_detail(value, subscription: dict, limit: int = 500) -> str:
    detail = str(value or "").replace("\r", " ").replace("\n", " ")
    keys = subscription.get("keys") or {}
    for secret in (subscription.get("endpoint"), keys.get("p256dh"), keys.get("auth")):
        if secret:
            detail = detail.replace(str(secret), "[REDACTED]")
    detail = re.sub(
        r"(?i)(authorization|token|secret|p256dh|auth)(\s*[:=]\s*)[^\s,;]+",
        r"\1\2[REDACTED]", detail,
    )
    return detail[:limit]


def _send_one(subscription: dict, payload: str, vapid: Vapid01) -> Optional[int]:
    """Blocking send; returns the HTTP status when the subscription is gone, otherwise None."""
    subscription_ref = _subscription_ref(subscription)
    try:
        response = webpush(
            subscription_info={"endpoint": subscription["endpoint"], "keys": subscription["keys"]},
            data=payload,
            vapid_private_key=vapid,
            vapid_claims={"sub": _vapid_subject()},
            ttl=86400,
            headers={"Urgency": "high"},
        )
        logger.info(
            "Web push response subscription=%s status=%s reason=%s body=%r",
            subscription_ref,
            getattr(response, "status_code", None),
            getattr(response, "reason", None),
            _safe_push_detail(getattr(response, "text", ""), subscription),
        )
    except WebPushException as exc:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        logger.warning(
            "Web push rejected subscription=%s error=%s status=%s reason=%s body=%r detail=%r",
            subscription_ref,
            type(exc).__name__,
            status,
            getattr(response, "reason", None),
            _safe_push_detail(getattr(response, "text", ""), subscription),
            _safe_push_detail(exc, subscription),
        )
        if status in (404, 410):
            return status
    except Exception as exc:
        logger.error(
            "Unexpected web push error subscription=%s error=%s detail=%r",
            subscription_ref, type(exc).__name__, _safe_push_detail(exc, subscription),
        )
    return None


async def deliver(db, notification: dict) -> None:
    try:
        user_id = notification["user_id"]
        subscriptions = await db.push_subscriptions.find({"user_id": user_id}, {"_id": 0}).to_list(50)
        logger.info("Loaded Web Push subscriptions user=%s count=%d", user_id, len(subscriptions))
        if not subscriptions:
            return
        valid_subscriptions = []
        for subscription in subscriptions:
            keys = subscription.get("keys") or {}
            if not subscription.get("endpoint") or not keys.get("p256dh") or not keys.get("auth"):
                logger.warning(
                    "Skipping malformed Web Push subscription user=%s ref=%s endpoint=%s p256dh=%s auth=%s",
                    user_id, _subscription_ref(subscription), bool(subscription.get("endpoint")),
                    bool(keys.get("p256dh")), bool(keys.get("auth")),
                )
                continue
            valid_subscriptions.append(subscription)
        logger.info("Valid Web Push subscriptions user=%s count=%d", user_id, len(valid_subscriptions))
        if not valid_subscriptions:
            return
        user = await db.users.find_one({"id": user_id}, {"_id": 0, "role": 1}) or {}
        vapid, _ = await get_vapid(db)
        payload = json.dumps({
            "title": PUSH_TITLES.get(notification.get("type"), "Distro Logistics"),
            "body": notification.get("text", ""),
            "url": push_url(notification, user.get("role", "")),
            "tag": f"n-{notification['id']}",
            "notification_id": notification["id"],
        }, ensure_ascii=False)
        results = await asyncio.gather(
            *(asyncio.to_thread(_send_one, subscription, payload, vapid) for subscription in valid_subscriptions)
        )
        gone = [subscription["endpoint"] for subscription, status in zip(valid_subscriptions, results) if status]
        if gone:
            await db.push_subscriptions.delete_many({"endpoint": {"$in": gone}})
        logger.info(
            "Web Push delivery finished user=%s attempted=%d expired=%d",
            user_id, len(valid_subscriptions), len(gone),
        )
    except Exception:
        logger.exception("Could not deliver web push")


def schedule(db, notification: dict) -> None:
    """Fire-and-forget so a slow push service never delays the API response."""
    try:
        task = asyncio.get_running_loop().create_task(deliver(db, dict(notification)))
    except RuntimeError:
        return
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
