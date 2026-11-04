import copy
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


def matches(document, query):
    for key, expected in query.items():
        value = document.get(key)
        if isinstance(expected, dict):
            if "$in" in expected and value not in expected["$in"]:
                return False
            if "$ne" in expected and value == expected["$ne"]:
                return False
            if "$gte" in expected and (value is None or value < expected["$gte"]):
                return False
        elif value != expected:
            return False
    return True


class Result:
    def __init__(self, modified):
        self.modified_count = modified
        self.matched_count = modified


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *_args):
        return self

    async def to_list(self, limit):
        return copy.deepcopy(self.rows[:limit])


class Collection:
    def __init__(self, rows=()):
        self.rows = copy.deepcopy(list(rows))

    def find(self, query, projection=None):
        return Cursor([r for r in self.rows if matches(r, query)])

    async def find_one(self, query, projection=None):
        rows = await self.find(query).to_list(1)
        return rows[0] if rows else None

    async def insert_one(self, doc):
        self.rows.append(copy.deepcopy(doc))

    async def insert_many(self, docs):
        self.rows.extend(copy.deepcopy(list(docs)))

    async def delete_many(self, query):
        self.rows = [r for r in self.rows if not matches(r, query)]

    async def update_one(self, query, update, upsert=False):
        for row in self.rows:
            if matches(row, query):
                row.update(update.get("$set", {}))
                for key, amount in update.get("$inc", {}).items():
                    row[key] = row.get(key, 0) + amount
                return Result(1)
        if upsert:
            doc = {k: v for k, v in query.items() if not isinstance(v, dict)}
            doc.update(update.get("$setOnInsert", {}))
            doc.update(update.get("$set", {}))
            self.rows.append(doc)
        return Result(0)


USER = {"id": "supplier-1", "role": "supplier", "business_name": "Distro", "identification_number": "1"}


def install(monkeypatch):
    now = datetime.now(timezone.utc).isoformat()
    db = type("MemoryDB", (), {
        "products": Collection([
            {"id": "p1", "supplier_id": "supplier-1", "name": "Tea", "sku": "TEA-1", "stock": 10,
             "price_per_unit": 5.0},
            {"id": "p2", "supplier_id": "supplier-1", "name": "Coffee", "sku": "COF-1", "stock": 4,
             "price_per_unit": 8.0},
        ]),
        "orders": Collection([
            {"id": "app-1", "supplier_id": "supplier-1", "status": "Delivered", "total": 100.0,
             "service_fee": 5.0, "source": "app", "created_at": now, "items": []},
        ]),
    })()
    db.users = Collection([dict(USER, status="active")])
    db.api_keys = Collection()
    monkeypatch.setattr(server, "db", db)
    server.app.dependency_overrides[server.get_current_user] = lambda: USER
    return TestClient(server.app), db


def test_external_sale_deducts_stock_and_is_commission_free(monkeypatch):
    client, db = install(monkeypatch)
    try:
        response = client.post("/api/external-orders/sync", json={
            "external_ref": "FINA-1", "source_system": "fina",
            "items": [{"sku": "TEA-1", "quantity": 3}, {"product_id": "p2", "quantity": 1, "unit_price": 9}],
        })
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["source"] == "external" and body["total"] == 24.0 and body["service_fee"] == 0
        assert server.order_commission(body) == 0
        assert {r["id"]: r["stock"] for r in db.products.rows} == {"p1": 7, "p2": 3}

        again = client.post("/api/external-orders/sync", json={
            "external_ref": "FINA-1", "items": [{"sku": "TEA-1", "quantity": 3}],
        })
        assert again.json()["duplicate"] is True
        assert db.products.rows[0]["stock"] == 7
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_external_sale_is_all_or_nothing(monkeypatch):
    client, db = install(monkeypatch)
    try:
        response = client.post("/api/external-orders/sync", json={
            "external_ref": "X-1", "items": [{"sku": "TEA-1", "quantity": 2}, {"sku": "COF-1", "quantity": 99}],
        })
        assert response.status_code == 409
        assert {r["id"]: r["stock"] for r in db.products.rows} == {"p1": 10, "p2": 4}
        missing = client.post("/api/external-orders/sync", json={
            "external_ref": "X-2", "items": [{"sku": "NOPE", "quantity": 1}],
        })
        assert missing.status_code == 404
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_inventory_sync_set_and_add(monkeypatch):
    client, db = install(monkeypatch)
    try:
        response = client.post("/api/inventory/sync", json={
            "source_system": "excel", "mode": "set",
            "items": [{"sku": "TEA-1", "quantity": 50}, {"sku": "UNKNOWN", "quantity": 1}],
        })
        assert response.status_code == 200, response.text
        assert response.json()["updated_count"] == 1 and response.json()["not_found"] == [1]
        assert db.products.rows[0]["stock"] == 50
        client.post("/api/inventory/sync", json={"mode": "add", "items": [{"product_id": "p2", "quantity": 6}]})
        assert db.products.rows[1]["stock"] == 10
        assert client.post("/api/inventory/sync", json={"mode": "bad", "items": [{"sku": "A", "quantity": 1}]}
                           ).status_code == 422
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_dashboard_separates_app_and_external_sales(monkeypatch):
    client, _db = install(monkeypatch)
    try:
        client.post("/api/external-orders/sync", json={"external_ref": "E1", "items": [{"sku": "TEA-1", "quantity": 2}]})
        data = client.get("/api/analytics/supplier").json()
        assert data["app_sales"]["revenue"] == 100.0 and data["app_sales"]["commission"] == 5.0
        assert data["external_sales"]["revenue"] == 10.0 and data["external_sales"]["commission"] == 0.0
        assert data["revenue"] == 110.0
        assert data["total_inventory"] == 8 + 4

        monthly = client.get("/api/analytics/supplier", params={
            "granularity": "monthly", "start_date": "2026-01-01", "end_date": "2026-12-31",
        }).json()
        assert monthly["granularity"] == "monthly" and len(monthly["series"]) == 12
        assert monthly["revenue"] == 110.0
        assert monthly["status_counts"]["Delivered"] == 1
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_platform_split_only_for_app_orders():
    settings = {"payment_split_enabled": True}
    assert server.compute_platform_split(100, settings, "app")["platform_amount"] == 3.0
    assert server.compute_platform_split(100, settings, "external") is None


def test_manual_endpoint_and_api_key_webhook(monkeypatch):
    client, db = install(monkeypatch)
    try:
        manual = client.post("/api/orders/external", json={
            "customer_name": "Shop", "items": [{"product_id": "p1", "quantity": 2}],
        })
        assert manual.status_code == 200 and manual.json()["source"] == "external"
        assert db.products.rows[0]["stock"] == 8

        assert client.post("/api/v1/sync/external-sale", json={
            "storeName": "Nikora", "items": [{"productId": "p1", "quantity": 1}],
        }).status_code == 401

        key = client.post("/api/supplier/integrations/api-key").json()["api_key"]
        assert key.startswith("dk_")
        assert "api_key" not in client.get("/api/supplier/integrations").json()
        assert key not in str(db.api_keys.rows)

        payload = {"storeName": "Nikora", "externalRef": "R1",
                   "items": [{"productId": "TEA-1", "quantity": 3, "price": 4.5}]}
        response = client.post("/api/v1/sync/external-sale", json=payload, headers={"X-API-Key": key})
        assert response.status_code == 200, response.text
        assert response.json()["source"] == "external" and response.json()["total"] == 13.5
        assert db.products.rows[0]["stock"] == 5
        client.post("/api/v1/sync/external-sale", json=payload, headers={"X-API-Key": key})
        assert db.products.rows[0]["stock"] == 5

        client.delete("/api/supplier/integrations/api-key")
        assert client.post("/api/v1/sync/external-sale", json=payload, headers={"X-API-Key": key}).status_code == 401
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)
