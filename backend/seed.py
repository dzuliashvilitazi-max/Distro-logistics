import os
import re
import uuid
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


def iso(days_ago=0):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


# Accounts created by earlier demo seeders and test runs; removed on startup.
LEGACY_DEMO_EMAILS = [
    "metro@distro.com", "apex@distro.com", "snacknation@distro.com",
    "cornerstore@distro.com", "freshmart@distro.com", "newdist@distro.com",
    "admin@distro.com", "mgv67mk2j5@privaterelay.appleid.com",
]
LEGACY_TEST_PATTERN = r"^test_.*@distro\.com$"

# collection -> fields that reference a user id
USER_LINKED_COLLECTIONS = {
    "products": ["supplier_id"],
    "orders": ["retailer_id", "supplier_id"],
    "invoices": ["supplier_id", "retailer_id", "store_id", "distributor_id"],
    "messages": ["from_id", "to_id"],
    "notifications": ["user_id"],
    "drivers": ["supplier_id"],
    "saved_contacts": ["owner_id"],
    "delivery_routes": ["supplier_id"],
}


async def purge_demo_accounts(db):
    """Delete legacy demo/test accounts and the data they own. The official admin is never touched."""
    keep = (os.environ.get("ADMIN_EMAIL") or "").strip().lower()
    emails = [e for e in LEGACY_DEMO_EMAILS if e != keep]
    query = {"$or": [{"email": {"$in": emails}}, {"email": {"$regex": LEGACY_TEST_PATTERN, "$options": "i"}}]}
    if keep:
        query = {"$and": [query, {"email": {"$ne": keep}}]}
    users = await db.users.find(query, {"id": 1, "_id": 0}).to_list(1000)
    ids = [u["id"] for u in users if u.get("id")]
    if not ids:
        return 0
    for collection, fields in USER_LINKED_COLLECTIONS.items():
        try:
            await db[collection].delete_many({"$or": [{f: {"$in": ids}} for f in fields]})
        except Exception:
            logger.exception("Could not clean %s for demo accounts", collection)
    await db.users.delete_many({"id": {"$in": ids}})
    logger.info("Removed %d demo/test accounts", len(ids))
    return len(ids)


async def ensure_admin_account(db, hash_password, verify_password):
    """Make sure the primary admin from ADMIN_EMAIL / ADMIN_PASSWORD exists with admin rights.

    Runs on every startup, so the account is also created or repaired on existing databases.
    The password is re-hashed only when it differs.
    """
    email = (os.environ.get("ADMIN_EMAIL") or "").strip().lower()
    password = os.environ.get("ADMIN_PASSWORD") or ""
    if not email or not password:
        return None
    existing = await db.users.find_one({"email": email})
    if existing is None:
        await db.users.insert_one({
            "id": str(uuid.uuid4()), "email": email, "password_hash": hash_password(password),
            "name": "Platform Admin", "role": "admin", "business_name": "Distro Logistics HQ",
            "address": "", "phone": "", "status": "active", "email_verified": True,
            "created_at": iso(0),
        })
        return "created"
    fix = {}
    if existing.get("role") != "admin":
        fix["role"] = "admin"
    if existing.get("status") not in (None, "active"):
        fix["status"] = "active"
    for flag, value in (("email_verified", True), ("must_change_password", False), ("active", True)):
        if existing.get(flag) is not value and (flag in existing or flag == "email_verified"):
            fix[flag] = value
    try:
        password_ok = verify_password(password, existing.get("password_hash", ""))
    except Exception:
        password_ok = False
    if not password_ok:
        fix["password_hash"] = hash_password(password)
    if fix:
        await db.users.update_one({"id": existing["id"]}, {"$set": fix})
        return "updated"
    return "ok"
