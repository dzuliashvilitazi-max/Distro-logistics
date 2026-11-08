from product_media import complete_product_media, is_legacy_fallback_image, is_missing_media


_LEGACY_IMAGE_QUERY = r"images\.unsplash\.com/photo-(1554866585-cd94860890b7|1549007994-cb92caebd54b|1563245372-f21724e3856d|1540420773420-3366772f4999|1550583724-b2692b85b150|1509440159596-0249088772ff|1607623814075-e51df1bdc82f|1542838132-92c53300491e)"


async def upgrade(db) -> int:
    missing = {"$or": [
        {"image": {"$in": [None, "", "null", "none", "undefined"]}},
        {"image": {"$regex": r"^\s*$"}},
        {"image": {"$regex": _LEGACY_IMAGE_QUERY}},
        {"description": {"$in": [None, "", "null", "none", "undefined"]}},
        {"description": {"$regex": r"^\s*$"}},
    ]}
    projection = {"_id": 1, "id": 1, "name": 1, "category": 1, "image": 1, "description": 1}
    fixed = 0
    async for product in db.products.find(missing, projection):
        media = complete_product_media(product)
        update = {
            field: media[field] for field in ("image", "description")
            if is_missing_media(product.get(field)) or (field == "image" and is_legacy_fallback_image(product.get(field)))
        }
        if update:
            product_id = product.get("id")
            product_filter = {"id": product_id} if product_id else {"_id": product.get("_id")}
            if product_filter.get("_id") is not None or product_id:
                await db.products.update_one(product_filter, {"$set": update})
                fixed += 1
    return fixed