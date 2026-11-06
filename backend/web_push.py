"""Web Push (VAPID) delivery for in-app notifications.

Keys come from VAPID_PRIVATE_KEY / VAPID_PUBLIC_KEY when configured; otherwise a key pair is generated
once and persisted in the `push_config` collection so every worker and restart shares the same identity.
"""
import asyncio
import base64
import json
import logging
import os
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
    _vapid_cache = (vapid, _public_key_b64(vapid))
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
        return "/support"
    return {"supplier": "/supplier/orders", "admin": "/admin/orders"}.get(role, "/orders")


def _send_one(subscription: dict, payload: str, vapid: Vapid01) -> Optional[int]:
    """Blocking send; returns the HTTP status when the subscription is gone, otherwise None."""
    try:
        webpush(
            subscription_info={"endpoint": subscription["endpoint"], "keys": subscription["keys"]},
            data=payload,
            vapid_private_key=vapid,
            vapid_claims={"sub": os.environ.get("VAPID_SUBJECT", "mailto:admin@distro.local")},
            ttl=86400,
            headers={"Urgency": "high"},
        )
    except WebPushException as exc:
        status = getattr(exc.response, "status_code", None)
        if status in (404, 410):
            return status
        logger.warning("Web push failed (%s): %s", status, exc)
    except Exception:
        logger.exception("Unexpected web push failure")
    return None


async def deliver(db, notification: dict) -> None:
    try:
        user_id = notification["user_id"]
        subscriptions = await db.push_subscriptions.find({"user_id": user_id}, {"_id": 0}).to_list(50)
        if not subscriptions:
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
        results = await asyncio.gather(*(asyncio.to_thread(_send_one, s, payload, vapid) for s in subscriptions))
        gone = [s["endpoint"] for s, status in zip(subscriptions, results) if status]
        if gone:
            await db.push_subscriptions.delete_many({"endpoint": {"$in": gone}})
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
