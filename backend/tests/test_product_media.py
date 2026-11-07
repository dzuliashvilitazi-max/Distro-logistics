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
        product = next(row for row in self.rows if row["id"] == query["id"])
        product.update(copy.deepcopy(update["$set"]))


class _Database:
    def __init__(self, rows):
        self.products = _Products(rows)


def test_product_media_fallback_uses_name_and_category():
    sneakers = complete_product_media({"name": "სნიკერსი", "category": "ტკბილეული"})
    dumplings = complete_product_media({"name": "პილმენი", "category": "გაყინული"})
    cola = complete_product_media({"name": "კოკა-კოლა", "category": "სასმელები"})
    juice = complete_product_media({"name": "ფორთოხლის წვენი", "category": "სასმელები"})
    green_tea = complete_product_media({"name": "Green tea", "category": "Beverages"})
    black_tea = complete_product_media({"name": "Black tea", "category": "Beverages"})

    assert "/chocolate?" in sneakers["image"]
    assert "/dumplings?" in dumplings["image"]
    assert "/cola?" in cola["image"]
    assert "/juice?" in juice["image"]
    assert cola["image"] != juice["image"]
    assert green_tea["image"] != black_tea["image"]
    assert green_tea["image"] == complete_product_media({"name": "Green tea", "category": "Beverages"})["image"]
    assert "სნიკერსი" in sneakers["description"]


def test_product_media_backfill_preserves_existing_values_and_is_idempotent():
    database = _Database([
        {"id": "empty", "name": "Snickers", "category": "Sweets", "image": "", "description": ""},
        {"id": "description-only", "name": "Milk", "category": "Dairy", "image": "https://example.test/milk.jpg"},
        {"id": "legacy", "name": "Orange juice", "category": "Beverages", "image": "https://images.unsplash.com/photo-1554866585-cd94860890b7?auto=format&fit=crop&w=800&q=85", "description": "Keep this"},
        {"id": "complete", "name": "Tea", "category": "Beverages", "image": "https://example.test/tea.jpg", "description": "Existing"},
    ])

    fixed = asyncio.run(upgrade(database))
    assert fixed == 3
    assert database.products.rows[0]["image"].startswith("https://loremflickr.com/")
    assert "Snickers" in database.products.rows[0]["description"]
    assert database.products.rows[1]["image"] == "https://example.test/milk.jpg"
    assert "Milk" in database.products.rows[1]["description"]
    assert "/juice?" in database.products.rows[2]["image"]
    assert database.products.rows[2]["description"] == "Keep this"
    assert database.products.rows[3]["description"] == "Existing"
    assert asyncio.run(upgrade(database)) == 0
