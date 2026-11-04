"""Idempotent MongoDB migration for store branches and POS analytics."""

import uuid


async def upgrade(db):
    retailers = db.users.find({"role": "retailer"}, {"_id": 0})
    async for retailer in retailers:
        branch = await db.store_branches.find_one(
            {"retailer_id": retailer["id"], "is_default": True}, {"_id": 0},
        )
        if not branch:
            branch_id = str(uuid.uuid4())
            branch = {
                "id": branch_id,
                "retailer_id": retailer["id"],
                "name": retailer.get("business_name") or retailer.get("name") or "Main branch",
                "address": retailer.get("address") or "",
                "phone": retailer.get("phone") or "",
                "is_default": True,
                "active": True,
                "created_at": "",
                "updated_at": "",
            }
            await db.store_branches.insert_one(branch)
        await db.users.update_one(
            {"id": retailer["id"], "default_branch_id": {"$exists": False}},
            {"$set": {"default_branch_id": branch["id"]}},
        )
        await db.orders.update_many(
            {"retailer_id": retailer["id"], "branch_id": {"$exists": False}},
            {"$set": {"branch_id": branch["id"]}},
        )

    await db.store_branches.create_index([("retailer_id", 1), ("id", 1)], unique=True)
    await db.store_integrations.create_index([("retailer_id", 1), ("id", 1)], unique=True)
    await db.store_integrations.create_index("token_hash", unique=True, sparse=True)
    await db.pos_sales.create_index([("retailer_id", 1), ("source_sale_id", 1)], unique=True)
    await db.pos_sales.create_index([("retailer_id", 1), ("branch_id", 1), ("sold_at", -1)])
    await db.pos_sales.create_index("items.product_id")
    await db.store_expenses.create_index([("retailer_id", 1), ("branch_id", 1), ("expense_date", -1)])
