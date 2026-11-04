"""POS/ERP inventory sync adapter: idempotent stock adjustments for approved product returns."""
from datetime import datetime, timezone

from fastapi import HTTPException


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class InventorySyncAdapter:
    """Applies a return to the store's on-hand stock and the distributor warehouse; each call is safe to retry."""

    def __init__(self, database):
        self.db = database

    async def restock_distributor(self, return_request: dict) -> None:
        return_id = return_request["id"]
        quantity = int(return_request["quantity"])
        product_id = return_request["product_id"]
        inventory = getattr(self.db, "warehouse_inventory", None)
        if inventory is not None and return_request.get("warehouse_id"):
            key = {
                "supplier_id": return_request["supplier_id"], "product_id": product_id,
                "warehouse_id": return_request["warehouse_id"],
            }
            result = await inventory.update_one(
                {**key, "applied_return_ids": {"$ne": return_id}},
                {"$inc": {"stock": quantity}, "$addToSet": {"applied_return_ids": return_id},
                 "$set": {"updated_at": _now_iso()}},
            )
            if not result.modified_count:
                stock = await inventory.find_one(key, {"_id": 0, "applied_return_ids": 1})
                if not stock or return_id not in stock.get("applied_return_ids", []):
                    raise HTTPException(409, "Distributor warehouse inventory record was not found.")
            return
        result = await self.db.products.update_one(
            {"id": product_id, "supplier_id": return_request["supplier_id"],
             "applied_return_ids": {"$ne": return_id}},
            {"$inc": {"stock": quantity}, "$addToSet": {"applied_return_ids": return_id}},
        )
        if not result.modified_count:
            product = await self.db.products.find_one(
                {"id": product_id, "supplier_id": return_request["supplier_id"]},
                {"_id": 0, "applied_return_ids": 1},
            )
            if not product or return_id not in product.get("applied_return_ids", []):
                raise HTTPException(409, "Distributor product inventory record was not found.")

    async def reduce_store_on_hand(self, return_request: dict) -> bool:
        """Decrement POS-reported on-hand stock; False when the store has no on-hand record to adjust."""
        return_id = return_request["id"]
        quantity = int(return_request["quantity"])
        key = {
            "retailer_id": return_request["retailer_id"], "branch_id": return_request.get("branch_id"),
            "product_id": return_request["product_id"],
        }
        inventory = getattr(self.db, "store_inventory", None)
        if inventory is None:
            return False
        result = await inventory.update_one(
            {**key, "applied_return_ids": {"$ne": return_id}, "on_hand": {"$gte": quantity}},
            {"$inc": {"on_hand": -quantity}, "$addToSet": {"applied_return_ids": return_id},
             "$set": {"updated_at": _now_iso()}},
        )
        if result.modified_count:
            return True
        record = await inventory.find_one(key, {"_id": 0, "applied_return_ids": 1})
        if not record:
            return False
        if return_id in record.get("applied_return_ids", []):
            return True
        raise HTTPException(409, "Store on-hand inventory is lower than the returned quantity.")

    async def record_movements(self, return_request: dict, store_tracked: bool) -> None:
        movements = getattr(self.db, "inventory_movements", None)
        if movements is None:
            return
        return_id = return_request["id"]
        quantity = int(return_request["quantity"])
        sides = (
            ("store", {"retailer_id": return_request["retailer_id"], "branch_id": return_request.get("branch_id"),
                       "quantity": -quantity, "on_hand_tracked": store_tracked}),
            ("supplier", {"supplier_id": return_request["supplier_id"],
                          "warehouse_id": return_request.get("warehouse_id"), "quantity": quantity}),
        )
        for side, movement in sides:
            movement_id = f"return:{return_id}:{side}"
            await movements.update_one(
                {"id": movement_id},
                {"$setOnInsert": {
                    "id": movement_id, "type": "return", "return_id": return_id,
                    "product_id": return_request["product_id"], "order_id": return_request["order_id"],
                    **movement, "created_at": _now_iso(),
                }},
                upsert=True,
            )
