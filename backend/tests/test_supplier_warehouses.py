import copy
import asyncio
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


def matches(document, query):
    for key, expected in query.items():
        if key == "$or":
            if not any(matches(document, part) for part in expected):
                return False
            continue
        value = document.get(key)
        if isinstance(expected, dict):
            if "$in" in expected and value not in expected["$in"]:
                return False
            if "$nin" in expected and value in expected["$nin"]:
                return False
            if "$ne" in expected and value == expected["$ne"]:
                return False
            if "$gte" in expected and (value is None or value < expected["$gte"]):
                return False
        elif value != expected:
            return False
    return True


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, field, direction=1):
        self.rows.sort(
            key=lambda row: (type(row.get(field)).__name__, str(row.get(field) or "")),
            reverse=direction < 0,
        )
        return self

    def skip(self, count):
        self.rows = self.rows[count:]
        return self

    def limit(self, count):
        self.rows = self.rows[:count]
        return self

    async def to_list(self, limit):
        return copy.deepcopy(self.rows if limit is None else self.rows[:limit])


class Collection:
    def __init__(self, rows):
        self.rows = copy.deepcopy(rows)

    async def count_documents(self, query):
        return len([row for row in self.rows if matches(row, query)])

    def find(self, query, projection=None):
        rows = [row for row in self.rows if matches(row, query)]
        if projection and any(enabled == 1 for enabled in projection.values()):
            included = {key for key, enabled in projection.items() if enabled == 1}
            rows = [{key: value for key, value in row.items() if key in included} for row in rows]
        elif projection and projection.get("_id") == 0:
            rows = [{key: value for key, value in row.items() if key not in projection} for row in rows]
        return Cursor(rows)

    async def find_one(self, query, projection=None):
        rows = await self.find(query, projection).to_list(1)
        return rows[0] if rows else None


def install_supplier_manager(monkeypatch):
    user = {
        "id": "manager-1", "role": "supplier", "supplier_id": "supplier-1",
        "supplier_access_role": "branch_manager", "assigned_branch_id": "warehouse-1",
        "operational_permissions": ["orders", "inventory", "drivers", "routes", "finance"],
        "business_name": "Regional Manager",
    }
    db = type("MemoryDB", (), {
        "supplier_warehouses": Collection([
            {"id": "warehouse-1", "supplier_id": "supplier-1", "name": "Tbilisi", "city": "Tbilisi", "active": True},
            {"id": "warehouse-2", "supplier_id": "supplier-1", "name": "Kutaisi", "city": "Kutaisi", "active": True},
        ]),
        "orders": Collection([
            {"id": "order-1", "supplier_id": "supplier-1", "warehouse_id": "warehouse-1",
             "status": "Pending", "external_order": False, "payment_method": "cash", "total": 10,
             "created_at": "2026-10-21T10:00:00+00:00", "items": []},
            {"id": "order-2", "supplier_id": "supplier-1", "warehouse_id": "warehouse-2",
             "status": "Pending", "external_order": False, "payment_method": "cash", "total": 20,
             "created_at": "2026-10-21T11:00:00+00:00", "items": []},
        ]),
        "drivers": Collection([
            {"id": "driver-1", "supplier_id": "supplier-1", "warehouse_id": "warehouse-1", "name": "One"},
            {"id": "driver-2", "supplier_id": "supplier-1", "warehouse_id": "warehouse-2", "name": "Two"},
        ]),
        "products": Collection([
            {"id": "product-1", "supplier_id": "supplier-1", "name": "Tea", "stock": 1},
        ]),
        "warehouse_inventory": Collection([
            {"product_id": "product-1", "supplier_id": "supplier-1", "warehouse_id": "warehouse-1", "stock": 7},
            {"product_id": "product-1", "supplier_id": "supplier-1", "warehouse_id": "warehouse-2", "stock": 19},
        ]),
    })()
    monkeypatch.setattr(server, "db", db)
    server.app.dependency_overrides[server.get_current_user] = lambda: user
    return TestClient(server.app), db, user


def test_supplier_branch_manager_is_restricted_to_assigned_warehouse(monkeypatch):
    client, _db, _user = install_supplier_manager(monkeypatch)
    try:
        assert [row["id"] for row in client.get("/api/supplier/warehouses").json()] == ["warehouse-1"]
        assert [row["id"] for row in client.get("/api/orders").json()] == ["order-1"]
        assert [row["id"] for row in client.get("/api/drivers").json()] == ["driver-1"]

        response = client.get("/api/orders", params={"warehouse_id": "warehouse-2"})
        assert response.status_code == 403
        response = client.get("/api/drivers", params={"warehouse_id": "warehouse-2"})
        assert response.status_code == 403
        response = client.get("/api/products", params={"warehouse_id": "warehouse-2"})
        assert response.status_code == 403
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_supplier_analytics_are_warehouse_scoped(monkeypatch):
    client, _db, _user = install_supplier_manager(monkeypatch)
    try:
        response = client.get("/api/analytics/supplier")
        assert response.status_code == 200
        assert response.json()["revenue"] == 10
        assert response.json()["total_orders"] == 1
        assert response.json()["low_stock"][0]["stock"] == 7
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_supplier_auth_token_includes_branch_role_and_assignment():
    token = server.create_token("manager-1", {
        "id": "manager-1", "role": "supplier", "supplier_access_role": "branch_manager",
        "assigned_branch_id": "warehouse-1",
    })
    payload = server.jwt.decode(token, server.JWT_SECRET, algorithms=[server.JWT_ALGORITHM])
    assert payload["role"] == "Branch Manager"
    assert payload["app_role"] == "supplier"
    assert payload["assigned_branch_id"] == "warehouse-1"


def test_marketplace_stock_is_taken_from_the_matching_regional_warehouse(monkeypatch):
    db = type("MemoryDB", (), {
        "supplier_warehouses": Collection([
            {"id": "warehouse-1", "supplier_id": "supplier-1", "city": "Tbilisi",
             "city_lower": "tbilisi", "servedCities": ["თბილისი"], "active": True},
            {"id": "warehouse-2", "supplier_id": "supplier-1", "city": "Kutaisi",
             "city_lower": "kutaisi", "servedCities": ["ქუთაისი"], "active": True},
        ]),
        "warehouse_inventory": Collection([
            {"product_id": "product-1", "supplier_id": "supplier-1", "warehouse_id": "warehouse-1", "stock": 7},
            {"product_id": "product-1", "supplier_id": "supplier-1", "warehouse_id": "warehouse-2", "stock": 19},
        ]),
    })()
    monkeypatch.setattr(server, "db", db)
    products = [{"id": "product-1", "supplier_id": "supplier-1", "stock": 100}]

    available = asyncio.run(server._apply_regional_product_stock(copy.deepcopy(products), "Kutaisi"))
    unavailable = asyncio.run(server._apply_regional_product_stock(copy.deepcopy(products), "Batumi"))

    assert available[0]["stock"] == 19
    assert available[0]["warehouse_id"] == "warehouse-2"
    assert unavailable[0]["stock"] == 0
    assert unavailable[0]["warehouse_id"] is None


def test_retailer_product_catalog_only_returns_stock_from_serving_warehouses(monkeypatch):
    db = type("MemoryDB", (), {
        "supplier_warehouses": Collection([
            {"id": "rustavi-warehouse", "supplier_id": "supplier-1", "city": "Tbilisi",
             "servedCities": ["თბილისი", "რუსთავი"], "active": True, "is_default": True},
            {"id": "batumi-warehouse", "supplier_id": "supplier-1", "city": "Batumi",
             "servedCities": ["ბათუმი"], "active": True},
            {"id": "tbilisi-warehouse", "supplier_id": "supplier-2", "city": "Tbilisi",
             "servedCities": ["თბილისი"], "active": True},
        ]),
        "warehouse_inventory": Collection([
            {"product_id": "product-1", "supplier_id": "supplier-1", "warehouse_id": "rustavi-warehouse", "stock": 11},
            {"product_id": "product-1", "supplier_id": "supplier-1", "warehouse_id": "batumi-warehouse", "stock": 23},
            {"product_id": "product-2", "supplier_id": "supplier-1", "warehouse_id": "batumi-warehouse", "stock": 35},
            {"product_id": "product-3", "supplier_id": "supplier-2", "warehouse_id": "tbilisi-warehouse", "stock": 35},
        ]),
        "users": Collection([
            {"id": "supplier-1", "role": "supplier", "city": "Tbilisi"},
            {"id": "supplier-2", "role": "supplier", "city": "Rustavi"},
        ]),
        "products": Collection([
            {"id": "product-1", "supplier_id": "supplier-1", "name": "Tea", "stock": 100},
            {"id": "product-2", "supplier_id": "supplier-1", "name": "Coffee", "stock": 100},
            {"id": "product-3", "supplier_id": "supplier-2", "name": "Coffee", "stock": 100},
        ]),
    })()
    monkeypatch.setattr(server, "db", db)
    monkeypatch.setattr(server, "_retailer_city", lambda _user: asyncio.sleep(0, result="რუსთავი"))
    monkeypatch.setattr(server, "_entity_type_for_user", lambda _user: asyncio.sleep(0, result=None))
    monkeypatch.setattr(server, "_allowed_categories_for_user", lambda _user: asyncio.sleep(0, result=None))
    monkeypatch.setattr(server, "_declared_category_names", lambda _ids: asyncio.sleep(0, result={}))
    monkeypatch.setattr(server, "_apply_partner_pricing", lambda products, _store_id: asyncio.sleep(0, result=products))
    monkeypatch.setattr(server, "_attach_supplier_logos", lambda products: asyncio.sleep(0, result=products))
    user = {"id": "store-1", "role": "retailer", "city": "რუსთავი"}

    products = asyncio.run(server.list_products(user=user))
    distributors = asyncio.run(server.list_distributors(user=user))

    assert [product["id"] for product in products] == ["product-1"]
    assert products[0]["warehouse_id"] == "rustavi-warehouse"
    assert products[0]["stock"] == 11
    assert [distributor["id"] for distributor in distributors] == ["supplier-1"]
    assert distributors[0]["product_count"] == 1


def test_order_routing_prefers_the_most_specific_matching_city(monkeypatch):
    db = type("MemoryDB", (), {
        "supplier_warehouses": Collection([
            {"id": "warehouse-default", "supplier_id": "supplier-1", "city": "Tbilisi",
             "active": True, "is_default": True},
            {"id": "warehouse-specific", "supplier_id": "supplier-1", "city": "Old Tbilisi",
             "active": True, "is_default": False},
        ]),
    })()
    monkeypatch.setattr(server, "db", db)

    warehouse_id = asyncio.run(server._warehouse_for_supplier_location(
        "supplier-1", "Store address in Old Tbilisi, Georgia",
    ))

    assert warehouse_id == "warehouse-specific"


def test_warehouse_served_cities_route_products_and_orders_to_the_same_stock(monkeypatch):
    db = type("MemoryDB", (), {
        "supplier_warehouses": Collection([
            {"id": "warehouse-1", "supplier_id": "supplier-1", "city": "Kutaisi",
             "servedCities": ["თბილისი", "რუსთავი"], "active": True, "is_default": True},
            {"id": "warehouse-2", "supplier_id": "supplier-1", "city": "Batumi",
             "servedCities": ["ბათუმი"], "active": True},
        ]),
        "warehouse_inventory": Collection([
            {"product_id": "product-1", "supplier_id": "supplier-1", "warehouse_id": "warehouse-1", "stock": 11},
            {"product_id": "product-1", "supplier_id": "supplier-1", "warehouse_id": "warehouse-2", "stock": 23},
        ]),
    })()
    monkeypatch.setattr(server, "db", db)
    products = [{"id": "product-1", "supplier_id": "supplier-1", "stock": 100}]

    available = asyncio.run(server._apply_regional_product_stock(copy.deepcopy(products), "Rustavi"))
    unavailable = asyncio.run(server._apply_regional_product_stock(copy.deepcopy(products), "Batumi"))
    warehouse_id = asyncio.run(server._warehouse_for_supplier_location(
        "supplier-1", "Store in Rustavi", city="რუსთავი",
    ))

    assert available[0]["stock"] == 11
    assert available[0]["warehouse_id"] == "warehouse-1"
    assert unavailable[0]["stock"] == 23
    assert unavailable[0]["warehouse_id"] == "warehouse-2"
    assert warehouse_id == available[0]["warehouse_id"]


def test_selected_warehouse_stock_does_not_fall_back_to_global_product_stock(monkeypatch):
    db = type("MemoryDB", (), {
        "warehouse_inventory": Collection([]),
    })()
    monkeypatch.setattr(server, "db", db)

    stock = asyncio.run(server.available_product_stock(
        "supplier-1", "product-1", "warehouse-1", fallback=100,
    ))

    assert stock == 0


def test_selected_warehouse_reservation_does_not_deduct_global_product_stock(monkeypatch):
    class Inventory:
        async def update_one(self, *_args, **_kwargs):
            return type("Result", (), {"modified_count": 0})()

    class Products:
        async def update_one(self, *_args, **_kwargs):
            raise AssertionError("Global product stock must not be used for warehouse reservations.")

    monkeypatch.setattr(server, "db", type("MemoryDB", (), {
        "warehouse_inventory": Inventory(),
        "products": Products(),
    })())

    reserved = asyncio.run(server.reserve_product_stock(
        "supplier-1", "product-1", "warehouse-1", quantity=1,
    ))

    assert reserved is False


def test_warehouse_served_cities_are_canonical_and_cannot_be_empty():
    warehouse = server.SupplierWarehouseIn.model_validate({
        "name": "Regional", "city": "Tbilisi", "servedCities": ["Tbilisi", "Rustavi"],
    })

    assert warehouse.servedCities == ["თბილისი", "რუსთავი"]
    assert not server._warehouse_serves_city({"city": "Tbilisi"}, "Tbilisi")
    try:
        server.SupplierWarehouseIn.model_validate({
            "name": "Regional", "city": "Tbilisi", "servedCities": [],
        })
    except ValueError:
        pass
    else:
        raise AssertionError("An empty servedCities list should be rejected.")
