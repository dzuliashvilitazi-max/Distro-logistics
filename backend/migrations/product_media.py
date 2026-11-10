from product_media import fallback_product_description, is_generated_placeholder, is_missing_media

_PLACEHOLDER_QUERY = r"loremflickr\.com|images\.unsplash\.com/photo-(1554866585|1549007994|1563245372|1540420773|1550583724|1509440159|1607623814|1542838132)"


async def upgrade(db) -> int:
    """Mark products without a usable image as pending (the image job fills them) and add missing descriptions.
    Valid existing images are never touched. Idempotent."""
    missing = {"$or": [
        {"image": {"$in": [None, "", "null", "none", "undefined"]}},
        {"image": {"$regex": r"^\s*$"}},
        {"image": {"$regex": _PLACEHOLDER_QUERY}},
        {"description": {"$in": [None, "", "null", "none", "undefined"]}},
        {"description": {"$regex": r"^\s*$"}},
    ]}
    projection = {
        "_id": 1, "id": 1, "name": 1, "category": 1, "image": 1, "description": 1,
        "image_source": 1, "image_status": 1,
    }
    fixed = 0
    async for product in db.products.find(missing, projection):
        update = {}
        if is_missing_media(product.get("description")):
            update["description"] = fallback_product_description(product.get("name"), product.get("category"))
        no_image = is_missing_media(product.get("image")) or is_generated_placeholder(product.get("image"))
        if no_image and product.get("image_source") != "manual":
            if product.get("image"):
                update["image"] = ""
            if product.get("image_status") not in ("pending", "no_match", "failed"):
                update.update(image_status="pending", image_attempts=0)
        if update:
            product_id = product.get("id")
            product_filter = {"id": product_id} if product_id else {"_id": product.get("_id")}
            if product_filter.get("_id") is not None or product_id:
                await db.products.update_one(product_filter, {"$set": update})
                fixed += 1
    return fixed
