import asyncio
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from migrations.product_media import upgrade
from product_media import complete_product_media


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def __aiter__(self):
        async def iterate():
            for row in self.rows:
                yield row
        return iterate()


class _Products:
    def __init__(self, rows):
        self.rows = copy.deepcopy(rows)

    def find(self, query, projection):
        return _Cursor(self.rows)

    async def update_one(self, query, update):
        product = next(row for row in self.rows if all(row.get(key) == value for key, value in query.items()))
        product.update(copy.deepcopy(update["$set"]))


class _Database:
    def __init__(self, rows):
        self.products = _Products(rows)




def test_missing_image_is_left_pending_not_replaced_by_random_photo():
    media = complete_product_media({"name": "Snickers", "category": "Sweets", "image": ""})
    assert media["image"] == "" and media["image_status"] == "pending" and media["image_source"] is None
    assert "Snickers" in media["description"]


def test_supplied_image_is_manual_and_existing_auto_image_keeps_its_source():
    manual = complete_product_media({"name": "Tea", "category": "Beverages", "image": "https://example.test/tea.jpg"})
    assert manual["image_source"] == "manual"
    existing = {"image": "/product-images/" + "a" * 32 + ".jpg", "image_source": "auto"}
    kept = complete_product_media({"name": "Tea", "category": "Beverages", "image": existing["image"]}, existing)
    assert kept["image_source"] == "auto"
    cleared = complete_product_media({"name": "Tea", "category": "Beverages", "image": ""}, existing)
    assert cleared["image"] == existing["image"]


def test_product_media_backfill_preserves_existing_values_and_is_idempotent():
    database = _Database([
        {"id": "empty", "name": "Snickers", "category": "Sweets", "image": "", "description": ""},
        {"id": "description-only", "name": "Milk", "category": "Dairy", "image": "https://example.test/milk.jpg"},
        {"id": "legacy", "name": "Orange juice", "category": "Beverages", "image": "https://loremflickr.com/800/600/juice?lock=1", "description": "Keep this"},
        {"id": "complete", "name": "Tea", "category": "Beverages", "image": "https://example.test/tea.jpg", "description": "Existing"},
        {"id": "manual", "name": "X", "category": "Y", "image": "", "image_source": "manual", "description": "d"},
    ])

    assert asyncio.run(upgrade(database)) == 3
    rows = database.products.rows
    assert rows[0]["image_status"] == "pending" and "Snickers" in rows[0]["description"]
    assert rows[1]["image"] == "https://example.test/milk.jpg" and "Milk" in rows[1]["description"]
    assert rows[2]["image"] == "" and rows[2]["image_status"] == "pending" and rows[2]["description"] == "Keep this"
    assert rows[3]["image"] == "https://example.test/tea.jpg" and "image_status" not in rows[3]
    assert "image_status" not in rows[4]
    assert asyncio.run(upgrade(database)) == 0
