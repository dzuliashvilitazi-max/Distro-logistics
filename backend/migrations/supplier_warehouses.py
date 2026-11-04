"""Idempotent migration for distributor warehouses and per-warehouse inventory."""

import uuid


async def upgrade(db):
    suppliers = db.users.find({"role": "supplier"}, {"_id": 0})
    async for supplier in suppliers:
        supplier_id = supplier.get("supplier_id") or supplier["id"]
        warehouse = await db.supplier_warehouses.find_one(
            {"supplier_id": supplier_id, "is_default": True}, {"_id": 0},
        )
        if warehouse and not warehouse.get("servedCities"):
            await db.supplier_warehouses.update_one(
                {"id": warehouse["id"], "supplier_id": supplier_id},
                {"$set": {"servedCities": [warehouse.get("city") or supplier.get("city") or "Tbilisi"]}},
            )

        if not supplier.get("supplier_id"):
            await db.users.update_one(
                {"id": supplier["id"], "supplier_access_role": {"$exists": False}},
                {"$set": {"supplier_access_role": "global_admin"}},
            )
        # Warehouses are never created automatically; only the user creates them.
        if not warehouse:
            continue
        await db.products.update_many(
            {"supplier_id": supplier_id, "warehouse_id": {"$exists": False}},
            {"$set": {"warehouse_id": warehouse["id"]}},
        )
        products = db.products.find({"supplier_id": supplier_id, "warehouse_id": warehouse["id"]}, {"_id": 0})
        async for product in products:
            await db.warehouse_inventory.update_one(
                {"supplier_id": supplier_id, "product_id": product["id"], "warehouse_id": warehouse["id"]},
                {"$setOnInsert": {
                    "id": str(uuid.uuid4()), "supplier_id": supplier_id,
                    "product_id": product["id"], "warehouse_id": warehouse["id"],
                    "stock": int(product.get("stock", 0) or 0),
                }},
                upsert=True,
            )

        await db.orders.update_many(
            {"supplier_id": supplier_id, "warehouse_id": {"$exists": False}},
            {"$set": {"warehouse_id": warehouse["id"]}},
        )
        await db.drivers.update_many(
            {"supplier_id": supplier_id, "warehouse_id": {"$exists": False}},
            {"$set": {"warehouse_id": warehouse["id"]}},
        )
        await db.delivery_routes.update_many(
            {"supplier_id": supplier_id, "warehouse_id": {"$exists": False}},
            {"$set": {"warehouse_id": warehouse["id"]}},
        )

    await db.supplier_warehouses.create_index([("supplier_id", 1), ("id", 1)], unique=True)
    await db.supplier_warehouses.create_index([("supplier_id", 1), ("city_lower", 1)])
    await db.supplier_warehouses.create_index([("supplier_id", 1), ("servedCities", 1)])
    await db.warehouse_inventory.create_index(
        [("supplier_id", 1), ("product_id", 1), ("warehouse_id", 1)], unique=True,
    )
    await db.warehouse_transfers.create_index([("supplier_id", 1), ("created_at", -1)])
