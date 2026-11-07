from product_media import complete_product_media, is_missing_media


async def upgrade(db) -> int:
    missing = {"$or": [
        {"image": {"$in": [None, "", "null", "none", "undefined"]}},
        {"image": {"$regex": r"^\s*$"}},
        {"description": {"$in": [None, "", "null", "none", "undefined"]}},
        {"description": {"$regex": r"^\s*$"}},
    ]}
    projection = {"_id": 0, "id": 1, "name": 1, "category": 1, "image": 1, "description": 1}
    fixed = 0
    async for product in db.products.find(missing, projection):
        media = complete_product_media(product)
        update = {
            field: media[field] for field in ("image", "description")
            if is_missing_media(product.get(field))
        }
        if update:
            await db.products.update_one({"id": product["id"]}, {"$set": update})
            fixed += 1
    return fixed