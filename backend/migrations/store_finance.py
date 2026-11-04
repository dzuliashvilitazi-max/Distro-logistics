"""Idempotent MongoDB migration for store credit and order payment tracking."""


async def upgrade(db):
    cursor = db.orders.find(
        {"amount_paid": {"$exists": False}},
        {
            "_id": 0,
            "id": 1,
            "total": 1,
            "payment_method": 1,
            "payment_status": 1,
            "paid_at_checkout": 1,
            "payment_ref": 1,
            "external_order": 1,
            "updated_at": 1,
            "created_at": 1,
        },
    )
    async for order in cursor:
        total = round(float(order.get("total", 0) or 0), 2)
        paid = total if (
            not order.get("external_order")
            and (order.get("paid_at_checkout") or order.get("payment_status") == "Succeeded")
        ) else 0
        entries = []
        if paid:
            entries.append({
                "id": f"migration-{order['id']}",
                "amount": paid,
                "method": order.get("payment_method") or "card",
                "reference": order.get("payment_ref") or "",
                "note": "Migrated existing confirmed checkout payment",
                "recorded_by": "system",
                "recorded_at": order.get("updated_at") or order.get("created_at") or "",
                "automatic": True,
            })
        await db.orders.update_one(
            {"id": order["id"], "amount_paid": {"$exists": False}},
            {"$set": {"amount_paid": paid, "payment_entries": entries}},
        )

    await db.credit_terms.create_index(
        [("supplier_id", 1), ("retailer_id", 1)], unique=True,
    )
    await db.orders.create_index([("retailer_id", 1), ("supplier_id", 1), ("status", 1)])
