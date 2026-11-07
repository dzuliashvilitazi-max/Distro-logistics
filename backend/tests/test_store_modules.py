import asyncio
import copy
import hashlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


def _value(document, key):
    value = document
    for part in key.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _matches(document, query):
    for key, expected in query.items():
        if key == "$or":
            if not any(_matches(document, part) for part in expected):
                return False
            continue
        value = _value(document, key)
        if isinstance(expected, dict):
            if "$in" in expected and value not in expected["$in"]:
                return False
            if "$ne" in expected and value == expected["$ne"]:
                return False
            if "$gte" in expected and (value is None or value < expected["$gte"]):
                return False
            if "$gt" in expected and (value is None or value <= expected["$gt"]):
                return False
            if "$exists" in expected and (key in document) != expected["$exists"]:
                return False
        elif value != expected:
            return False
    return True


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, field, direction=1):
        if isinstance(field, list):
            for key, order in reversed(field):
                self.rows.sort(key=lambda row: row.get(key) or "", reverse=order < 0)
            return self
        self.rows.sort(key=lambda row: row.get(field) or "", reverse=direction < 0)
        return self

    def skip(self, count):
        self.rows = self.rows[count:]
        return self

    def limit(self, count):
        self.rows = self.rows[:count]
        return self

    async def to_list(self, limit):
        return copy.deepcopy(self.rows[:limit])


class Collection:
    def __init__(self, rows=()):
        self.rows = [copy.deepcopy(row) for row in rows]

    def find(self, query, projection=None):
        rows = [row for row in self.rows if _matches(row, query)]
        if projection:
            included = {key for key, enabled in projection.items() if enabled == 1}
            if included:
                rows = [{key: value for key, value in row.items() if key in included} for row in rows]
            elif projection.get("_id") == 0:
                rows = [{key: value for key, value in row.items() if key not in projection} for row in rows]
        return Cursor(rows)

    async def find_one(self, query, projection=None):
        found = await self.find(query, projection).to_list(1)
        return found[0] if found else None

    async def count_documents(self, query):
        return sum(1 for row in self.rows if _matches(row, query))

    async def insert_one(self, document):
        self.rows.append(copy.deepcopy(document))

    async def update_one(self, query, update, upsert=False):
        for row in self.rows:
            if not _matches(row, query):
                continue
            row.update(copy.deepcopy(update.get("$set", {})))
            return type("Result", (), {"matched_count": 1, "modified_count": 1})()
        if upsert:
            row = {key: value for key, value in query.items() if not key.startswith("$")}
            row.update(copy.deepcopy(update.get("$setOnInsert", {})))
            row.update(copy.deepcopy(update.get("$set", {})))
            self.rows.append(row)
            return type("Result", (), {"matched_count": 0, "modified_count": 1})()
        return type("Result", (), {"matched_count": 0, "modified_count": 0})()

    async def delete_one(self, query):
        for index, row in enumerate(self.rows):
            if _matches(row, query):
                self.rows.pop(index)
                return type("Result", (), {"deleted_count": 1})()
        return type("Result", (), {"deleted_count": 0})()

    async def delete_many(self, query):
        self.rows = [row for row in self.rows if not _matches(row, query)]


def _install(monkeypatch, user):
    retailer_id = user["id"] if user["role"] == "retailer" else "store-1"
    supplier_id = "supplier-1"
    branch = {
        "id": "branch-1", "retailer_id": retailer_id, "name": "Main",
        "address": "Tbilisi", "active": True, "is_default": True,
    }
    orders = Collection([{
        "id": "purchase-1", "order_no": "ORD-1", "retailer_id": retailer_id,
        "retailer_name": "Store", "supplier_id": supplier_id, "supplier_name": "Supplier",
        "branch_id": "branch-1", "status": "Delivered", "external_order": False,
        "total": 20, "amount_paid": 0, "delivered_at": "2026-10-20T12:00:00+00:00",
        "updated_at": "2026-10-20T12:00:00+00:00", "created_at": "2026-10-20T12:00:00+00:00",
        "items": [{"product_id": "product-1", "name": "Tea", "sku": "TEA-1", "quantity": 2, "unit_price": 10}],
    }])
    integrations = Collection()
    integrations.rows.append({
        "id": "integration-1", "retailer_id": retailer_id, "software": "Test POS",
        "active": True, "token_hash": hashlib.sha256(b"dlpos_testtoken").hexdigest(),
    })
    db = type("MemoryDB", (), {
        "store_branches": Collection([branch]),
        "store_integrations": integrations,
        "pos_sales": Collection(),
        "store_expenses": Collection(),
        "notifications": Collection(),
        "orders": orders,
        "products": Collection([{"id": "product-1", "name": "Tea", "sku": "TEA-1"}]),
        "users": Collection([
            {"id": retailer_id, "role": "retailer", "business_name": "Store"},
            {"id": supplier_id, "role": "supplier", "business_name": "Supplier"},
        ]),
        "credit_terms": Collection(),
    })()
    monkeypatch.setattr(server, "db", db)
    server.app.dependency_overrides[server.get_current_user] = lambda: user
    return TestClient(server.app), db


def test_store_branch_create_edit_and_protect_default(monkeypatch):
    client, db = _install(monkeypatch, {"id": "store-1", "role": "retailer", "business_name": "Store"})
    try:
        response = client.post("/api/store/branches", json={
            "name": "Saburtalo", "address": "Tbilisi, Saburtalo", "phone": "+995555000001",
        })
        assert response.status_code == 200
        branch = response.json()
        assert branch["is_default"] is False

        response = client.put(f"/api/store/branches/{branch['id']}", json={
            "name": "Saburtalo 2", "address": "Updated address", "phone": "", "active": True,
        })
        assert response.status_code == 200
        assert response.json()["name"] == "Saburtalo 2"

        response = client.put("/api/store/branches/branch-1", json={
            "name": "Main", "address": "Tbilisi", "phone": "", "active": False,
        })
        assert response.status_code == 409
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_profile_contact_update_syncs_default_branch(monkeypatch):
    client, db = _install(monkeypatch, {"id": "store-1", "role": "retailer", "business_name": "Store"})
    try:
        response = client.put("/api/profile", json={
            "address": "Updated delivery address", "phone": "+995555123456",
        })

        assert response.status_code == 200
        assert response.json()["address"] == "Updated delivery address"
        assert response.json()["phone"] == "+995555123456"
        default_branch = next(branch for branch in db.store_branches.rows if branch["is_default"])
        assert default_branch["address"] == "Updated delivery address"
        assert default_branch["phone"] == "+995555123456"
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_delivery_geocoding_skips_unmatched_stop_and_continues(monkeypatch):
    db = type("MemoryDB", (), {
        "orders": Collection([{"id": "order-found", "supplier_id": "supplier-1"}]),
    })()

    async def geocode(address):
        if "unmatched" in address:
            raise server.HTTPException(422, "Address not found")
        return {"lat": 41.7, "lon": 44.8}

    monkeypatch.setattr(server, "db", db)
    monkeypatch.setattr(server, "_geocode_address", geocode)
    orders = [
        {"id": "order-missing", "order_no": "ORD-MISSING", "delivery_address": "unmatched address"},
        {"id": "order-found", "order_no": "ORD-FOUND", "delivery_address": "Tbilisi, Rustaveli"},
    ]

    stops, unrouted_stops = asyncio.run(
        server._geocode_delivery_stops(orders, {"city": "Tbilisi"}, "supplier-1")
    )

    assert [stop["order_id"] for stop in stops] == ["order-found"]
    assert [stop["order_id"] for stop in unrouted_stops] == ["order-missing"]
    assert unrouted_stops[0]["reason"] == "address_not_found"
    assert db.orders.rows[0]["route_coordinates"] == {"lat": 41.7, "lon": 44.8}


def test_pos_sales_sync_idempotently_calculates_branch_profit(monkeypatch):
    client, db = _install(monkeypatch, {"id": "store-1", "role": "retailer", "business_name": "Store"})
    headers = {"Authorization": "Bearer dlpos_testtoken"}
    sale = [{
        "sale_id": "POS-1", "branch_id": "branch-1", "sold_at": "2026-10-21T09:30:00+04:00",
        "items": [{"product_id": "product-1", "quantity": 3, "retail_price": 15}],
    }]
    try:
        response = client.post("/api/store/integrations/sales", headers=headers, json=sale)
        assert response.status_code == 200
        assert response.json()["accepted"] == ["POS-1"]

        response = client.post("/api/store/integrations/sales", headers=headers, json=sale)
        assert response.status_code == 200
        assert response.json()["duplicates"] == ["POS-1"]

        response = client.post("/api/store/branch-expenses", json={
            "branch_id": "branch-1", "category": "rent", "amount": 5,
            "expense_date": "2026-10-21T12:00:00+04:00", "note": "Daily allocation",
        })
        assert response.status_code == 200

        response = client.get("/api/store/analytics")
        assert response.status_code == 200
        branch = response.json()["branches"][0]
        assert branch["revenue"] == 45
        assert branch["cost_of_goods"] == 30
        assert branch["operating_expenses"] == 5
        assert branch["net_profit"] == 10
        assert branch["operating_margin"] == 22.22
        assert len(db.pos_sales.rows) == 1
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_store_analytics_applies_date_range_in_database_query(monkeypatch):
    client, db = _install(monkeypatch, {"id": "store-1", "role": "retailer", "business_name": "Store"})
    db.pos_sales.rows.extend([
        {"id": "sale-in", "retailer_id": "store-1", "branch_id": "branch-1",
         "sold_at": "2026-10-21T09:30:00+04:00",
         "items": [{"product_id": "product-1", "quantity": 2, "retail_price": 15, "unit_cost": 10}]},
        {"id": "sale-out", "retailer_id": "store-1", "branch_id": "branch-1",
         "sold_at": "2026-10-20T10:00:00+04:00",
         "items": [{"product_id": "product-1", "quantity": 5, "retail_price": 15, "unit_cost": 10}]},
    ])
    try:
        response = client.get("/api/store/analytics", params={
            "date_from": "2026-10-21", "date_to": "2026-10-21",
        })
        assert response.status_code == 200
        branch = response.json()["branches"][0]
        assert branch["revenue"] == 30
        assert branch["cost_of_goods"] == 20
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_pos_sync_requires_valid_integration_token(monkeypatch):
    client, _db = _install(monkeypatch, {"id": "store-1", "role": "retailer", "business_name": "Store"})
    try:
        response = client.get("/api/store/integrations/orders")
        assert response.status_code == 401
        response = client.get("/api/store/integrations/orders", headers={"Authorization": "Bearer invalid"})
        assert response.status_code == 401
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_pricing_advisor_uses_purchase_cost_and_market_baseline(monkeypatch):
    client, _db = _install(monkeypatch, {"id": "store-1", "role": "retailer", "business_name": "Store"})
    try:
        response = client.post("/api/store/pricing/advisor", json={
            "order_id": "purchase-1", "product_id": "product-1", "planned_retail_price": 15,
        })
        assert response.status_code == 200
        advice = response.json()
        assert advice["unit_cost"] == 10
        assert advice["net_profit_per_unit"] == 5
        assert advice["profit_margin_percent"] == 33.33
        assert advice["recommendation_basis"] == "target_margin_estimate"
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_pos_order_feed_is_scoped_to_connected_retailer_and_branch(monkeypatch):
    client, _db = _install(monkeypatch, {"id": "store-1", "role": "retailer", "business_name": "Store"})
    try:
        response = client.get(
            "/api/store/integrations/orders",
            params={"branch_id": "branch-1"},
            headers={"Authorization": "Bearer dlpos_testtoken"},
        )
        assert response.status_code == 200
        assert [order["id"] for order in response.json()["orders"]] == ["purchase-1"]

        response = client.get(
            "/api/store/integrations/orders",
            params={"branch_id": "another-store-branch"},
            headers={"Authorization": "Bearer dlpos_testtoken"},
        )
        assert response.status_code == 404
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_pos_order_feed_paginates_with_stable_cursor(monkeypatch):
    client, db = _install(monkeypatch, {"id": "store-1", "role": "retailer", "business_name": "Store"})
    db.orders.rows = [
        {
            "id": f"purchase-{index:04d}", "retailer_id": "store-1",
            "branch_id": "branch-1", "status": "Delivered", "external_order": False,
            "updated_at": "2026-10-20T12:00:00+00:00",
        }
        for index in range(1002)
    ]
    try:
        first = client.get(
            "/api/store/integrations/orders",
            headers={"Authorization": "Bearer dlpos_testtoken"},
        )
        assert first.status_code == 200
        first_page = first.json()
        assert len(first_page["orders"]) == 1000
        assert first_page["has_more"] is True

        second = client.get(
            "/api/store/integrations/orders",
            params={
                "updated_since": first_page["next_updated_since"],
                "after_id": first_page["next_id"],
            },
            headers={"Authorization": "Bearer dlpos_testtoken"},
        )
        assert second.status_code == 200
        second_page = second.json()
        assert [order["id"] for order in second_page["orders"]] == ["purchase-1000", "purchase-1001"]
        assert second_page["has_more"] is False
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_retailer_order_feed_defaults_to_active_branch(monkeypatch):
    client, _db = _install(monkeypatch, {
        "id": "store-1", "role": "retailer", "business_name": "Store", "default_branch_id": "branch-1",
    })
    try:
        response = client.get("/api/orders")
        assert response.status_code == 200
        assert [order["id"] for order in response.json()] == ["purchase-1"]
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_store_owner_invites_branch_staff_and_requires_password_change(monkeypatch):
    client, db = _install(monkeypatch, {"id": "store-1", "role": "retailer", "business_name": "Store"})
    try:
        response = client.post("/api/store/staff", json={
            "name": "Branch Lead", "email": "lead@example.com",
            "branch_id": "branch-1", "role": "branch_manager",
        })
        assert response.status_code == 200
        invitation = response.json()
        assert invitation["branch_id"] == "branch-1"
        assert invitation["role"] == "branch_manager"
        assert invitation["temporary_password"]

        login_response = client.post("/api/auth/login", json={
            "email": invitation["email"], "password": invitation["temporary_password"],
        })
        assert login_response.status_code == 403
        assert login_response.json()["detail"]["code"] == "PASSWORD_RESET_REQUIRED"

        reset_response = client.post("/api/auth/staff-first-password", json={
            "email": invitation["email"], "temporary_password": invitation["temporary_password"],
            "new_password": "Longer-Secure-Password-123",
        })
        assert reset_response.status_code == 200
        assert reset_response.json()["user"]["store_access_role"] == "branch_manager"
        assert reset_response.json()["user"]["assigned_branch_id"] == "branch-1"
        assert db.users.rows[-1]["must_change_password"] is False
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_store_staff_are_limited_to_assigned_branch_and_can_receive_delivered_stock(monkeypatch):
    client, db = _install(monkeypatch, {
        "id": "staff-1", "role": "retailer", "retailer_id": "store-1",
        "store_access_role": "branch_manager", "assigned_branch_id": "branch-1",
        "business_name": "Store",
    })
    for branch in db.store_branches.rows:
        branch["retailer_id"] = "store-1"
    for order in db.orders.rows:
        order["retailer_id"] = "store-1"
    db.store_branches.rows.append({
        "id": "branch-2", "retailer_id": "store-1", "name": "Other", "active": True,
    })
    db.orders.rows.append({
        **db.orders.rows[0], "id": "purchase-2", "branch_id": "branch-2",
    })
    try:
        response = client.get("/api/orders")
        assert response.status_code == 200
        assert [order["id"] for order in response.json()] == ["purchase-1"]

        response = client.get("/api/orders", params={"branch_id": "branch-2"})
        assert response.status_code == 403

        response = client.get("/api/store/branches")
        assert response.status_code == 200
        assert [branch["id"] for branch in response.json()] == ["branch-1"]

        response = client.get("/api/store/analytics")
        assert response.status_code == 403

        response = client.put("/api/orders/purchase-1/status", json={"status": "Cancelled"})
        assert response.status_code == 403

        response = client.post("/api/orders/purchase-1/receive")
        assert response.status_code == 200
        assert db.orders.rows[0]["received_by"] == "staff-1"
        assert db.orders.rows[0]["received_at"]
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)
