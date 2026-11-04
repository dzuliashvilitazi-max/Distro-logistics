import asyncio
import copy
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


def matches(document, query):
    for key, expected in query.items():
        value = document.get(key)
        if isinstance(expected, dict):
            if "$in" in expected and value not in expected["$in"]:
                return False
            if "$lte" in expected and (value is None or value > expected["$lte"]):
                return False
            if "$gt" in expected and (value is None or value <= expected["$gt"]):
                return False
        elif value != expected:
            return False
    return True


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, field, direction=1):
        self.rows.sort(key=lambda row: row.get(field) or "", reverse=direction < 0)
        return self

    async def to_list(self, limit):
        return copy.deepcopy(self.rows[:limit])


class Collection:
    def __init__(self, rows=()):
        self.rows = copy.deepcopy(list(rows))

    def find(self, query, _projection=None):
        return Cursor([row for row in self.rows if matches(row, query)])

    async def find_one(self, query, _projection=None):
        rows = await self.find(query).to_list(1)
        return rows[0] if rows else None

    async def insert_one(self, document):
        self.rows.append(copy.deepcopy(document))

    async def update_one(self, query, update, upsert=False):
        for row in self.rows:
            if matches(row, query):
                row.update(copy.deepcopy(update.get("$set", {})))
                return SimpleNamespace(modified_count=1)
        if upsert:
            row = {key: value for key, value in query.items() if not isinstance(value, dict)}
            row.update(copy.deepcopy(update.get("$setOnInsert", {})))
            row.update(copy.deepcopy(update.get("$set", {})))
            self.rows.append(row)
        return SimpleNamespace(modified_count=0)


SUPPLIER = {"id": "distributor-1", "role": "supplier", "business_name": "Distro"}
STORE = {"id": "store-1", "role": "retailer"}
PRODUCT = {"id": "product-1", "supplier_id": SUPPLIER["id"], "name": "Tea", "price_per_unit": 10.0, "tier_pricing": []}


def setup(monkeypatch, existing_offers=()):
    database = SimpleNamespace(
        products=Collection([PRODUCT]),
        users=Collection([SUPPLIER, STORE]),
        store_distributor_connections=Collection([{
            "store_id": STORE["id"], "distributor_id": SUPPLIER["id"],
            "status": "APPROVED", "discount_percent": 0,
        }]),
        custom_prices=Collection(),
        product_offers=Collection(existing_offers),
        product_offer_history=Collection(),
    )
    monkeypatch.setattr(server, "db", database)
    async def fake_notify(*_args, **_kwargs):
        return None
    monkeypatch.setattr(server, "notify", fake_notify)
    server.app.dependency_overrides[server.get_current_user] = lambda: SUPPLIER
    return TestClient(server.app), database


def teardown_function():
    server.app.dependency_overrides.pop(server.get_current_user, None)


def test_offer_expiry_cancel_and_catalog_price_reversion(monkeypatch):
    client, database = setup(monkeypatch)
    try:
        response = client.post("/api/supplier/offers", json={
            "product_id": PRODUCT["id"], "offer_price": 7.5,
            "store_ids": [STORE["id"]], "duration_days": 2,
        })
        assert response.status_code == 201, response.text
        offer = database.product_offers.rows[0]
        expires_at = datetime.fromisoformat(offer["expiresAt"])
        assert timedelta(days=1, hours=23) < expires_at - datetime.now(timezone.utc) < timedelta(days=2, minutes=1)
        assert database.product_offer_history.rows[0]["action"] == "sent"

        priced = asyncio.run(server._apply_partner_pricing([dict(PRODUCT)], STORE["id"]))
        assert priced[0]["price_per_unit"] == 7.5
        assert priced[0]["active_offer"]["expiresAt"] == offer["expiresAt"]

        cancelled = client.delete(f"/api/supplier/offers/{offer['id']}")
        assert cancelled.status_code == 200, cancelled.text
        standard = asyncio.run(server._apply_partner_pricing([dict(PRODUCT)], STORE["id"]))
        assert standard[0]["price_per_unit"] == PRODUCT["price_per_unit"]
        assert database.product_offers.rows[0]["status"] == "cancelled"
        assert database.product_offer_history.rows[-1]["action"] == "cancelled"
    finally:
        teardown_function()


def test_expired_offer_is_marked_and_standard_price_is_used(monkeypatch):
    expired_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    offer = {
        "id": "offer-1", "distributor_id": SUPPLIER["id"], "store_id": STORE["id"],
        "product_id": PRODUCT["id"], "offer_price": 6.0,
        "created_at": expired_at, "updated_at": expired_at,
        "expiresAt": expired_at, "status": "active",
    }
    _client, database = setup(monkeypatch, [offer])
    try:
        priced = asyncio.run(server._apply_partner_pricing([dict(PRODUCT)], STORE["id"]))
        assert priced[0]["price_per_unit"] == PRODUCT["price_per_unit"]
        assert "active_offer" not in priced[0]
        assert database.product_offers.rows[0]["status"] == "expired"
        assert database.product_offer_history.rows[0]["action"] == "expired"
    finally:
        teardown_function()