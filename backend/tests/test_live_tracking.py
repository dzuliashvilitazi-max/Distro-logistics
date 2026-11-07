import copy
import hashlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


def value_at(document, path):
    value = document
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def matches(document, query):
    for key, expected in query.items():
        if key == "$or":
            if not any(matches(document, branch) for branch in expected):
                return False
            continue
        if key == "stops.order_id":
            stop_ids = [stop.get("order_id") for stop in document.get("stops", [])]
            if isinstance(expected, dict) and "$in" in expected:
                if not set(stop_ids).intersection(expected["$in"]):
                    return False
            elif expected not in stop_ids:
                return False
            continue
        value = value_at(document, key)
        if isinstance(expected, dict):
            if "$in" in expected and value not in expected["$in"]:
                return False
            if "$ne" in expected and value == expected["$ne"]:
                return False
            if "$lte" in expected and (value is None or value > expected["$lte"]):
                return False
        elif value != expected:
            return False
    return True


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

    async def insert_one(self, document):
        self.rows.append(copy.deepcopy(document))

    def find(self, query, _projection=None):
        return Cursor([row for row in self.rows if matches(row, query)])

    async def find_one(self, query, _projection=None):
        rows = await self.find(query).to_list(1)
        return rows[0] if rows else None

    async def update_one(self, query, update):
        for row in self.rows:
            if matches(row, query):
                for key, value in update.get("$set", {}).items():
                    if key == "stops.$.status":
                        stop_id = query.get("stops.order_id")
                        for stop in row.get("stops", []):
                            if stop.get("order_id") == stop_id:
                                stop["status"] = copy.deepcopy(value)
                                break
                    else:
                        row[key] = copy.deepcopy(value)
                for key in update.get("$unset", {}):
                    row.pop(key, None)
                return SimpleNamespace(modified_count=1)
        return SimpleNamespace(modified_count=0)


class SocketRecorder:
    def __init__(self):
        self.supplier_events = []
        self.order_events = []

    async def broadcast_supplier(self, supplier_id, warehouse_id, payload):
        self.supplier_events.append((supplier_id, warehouse_id, payload))

    async def broadcast_order(self, order_id, payload):
        self.order_events.append((order_id, payload))


TOKEN = "live-share-token"
ORDER = {
    "id": "order-1", "order_no": "ORD-1", "supplier_id": "supplier-1", "retailer_id": "store-1",
    "status": "In Transit", "total": 10.0, "route_coordinates": {"lat": 41.7, "lon": 44.8},
}
ROUTE = {
    "id": "route-1", "supplier_id": "supplier-1", "warehouse_id": "warehouse-1",
    "status": "assigned", "tracking_active": True, "started_at": "2026-10-30T10:00:00+00:00",
    "share_token_hash": hashlib.sha256(TOKEN.encode()).hexdigest(),
    "share_expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    "driver_id": "driver-1", "driver_name": "Driver One", "driver_phone": "+995555000000",
    "origin": {"lat": 41.7, "lon": 44.8},
    "geometry": [[44.8, 41.7], [44.9, 41.8]], "distance_meters": 1200,
    "duration_seconds": 300, "provider": "test", "stops": [{
        "order_id": "order-1", "order_no": "ORD-1", "lat": 41.7, "lon": 44.8, "status": "In Transit",
    }],
}


def setup(monkeypatch, order_status="In Transit"):
    route = copy.deepcopy(ROUTE)
    order = {**ORDER, "status": order_status}
    db = SimpleNamespace(
        delivery_routes=Collection([route]), orders=Collection([order]), notifications=Collection(),
    )
    sockets = SocketRecorder()
    monkeypatch.setattr(server, "db", db)
    monkeypatch.setattr(server, "location_sockets", sockets)
    monkeypatch.setattr(server.web_push, "schedule", lambda *_args: None)
    return TestClient(server.app), db, sockets


def teardown_function():
    server.app.dependency_overrides.pop(server.get_current_user, None)


def test_shared_driver_location_is_persisted_and_broadcast(monkeypatch):
    client, db, sockets = setup(monkeypatch)
    try:
        shared_route = client.get(f"/api/delivery-routes/shared/{TOKEN}")
        assert shared_route.status_code == 200, shared_route.text
        assert shared_route.json()["tracking_active"] is True

        response = client.post(f"/api/delivery-routes/shared/{TOKEN}/location", json={
            "lat": 41.71, "lon": 44.81, "accuracy_meters": 12,
        })
        assert response.status_code == 200, response.text
        saved = db.delivery_routes.rows[0]["driver_location"]
        assert (saved["lat"], saved["lon"], saved["accuracy_meters"]) == (41.71, 44.81, 12)
        assert sockets.supplier_events[0][2]["type"] == "location"
        assert sockets.order_events[0][0] == ORDER["id"]
        assert sockets.order_events[0][1]["driver_location"] == saved
    finally:
        teardown_function()


def test_location_is_rejected_when_route_has_no_in_transit_orders(monkeypatch):
    client, db, sockets = setup(monkeypatch, order_status="Delivered")
    try:
        response = client.post(f"/api/delivery-routes/shared/{TOKEN}/location", json={
            "lat": 41.71, "lon": 44.81,
        })
        assert response.status_code == 409
        assert db.delivery_routes.rows[0]["tracking_active"] is False
        assert "driver_location" not in db.delivery_routes.rows[0]
        assert db.delivery_routes.rows[0]["status"] == "completed"
        assert sockets.supplier_events[0][2]["type"] == "route_completed"
        assert sockets.order_events == []
    finally:
        teardown_function()


def test_start_route_moves_orders_in_transit_and_broadcasts_status(monkeypatch):
    client, db, sockets = setup(monkeypatch, order_status="Processing")
    try:
        response = client.post(f"/api/delivery-routes/shared/{TOKEN}/start")

        assert response.status_code == 200, response.text
        assert response.json()["in_transit"] == [ORDER["id"]]
        assert db.orders.rows[0]["status"] == "In Transit"
        assert db.delivery_routes.rows[0]["tracking_active"] is True
        assert (ORDER["id"], {"type": "status", "status": "In Transit"}) in sockets.order_events
        assert db.notifications.rows[0]["order_id"] == ORDER["id"]
    finally:
        teardown_function()


def test_geofence_delivers_nearby_stop_without_collecting_cash(monkeypatch):
    client, db, sockets = setup(monkeypatch)
    try:
        response = client.post(f"/api/delivery-routes/shared/{TOKEN}/location", json={
            "lat": 41.7001, "lon": 44.8, "accuracy_meters": 5,
        })

        assert response.status_code == 200, response.text
        assert response.json()["delivered_order_ids"] == [ORDER["id"]]
        assert response.json()["tracking_active"] is False
        assert db.orders.rows[0]["status"] == "Delivered"
        assert db.delivery_routes.rows[0]["status"] == "completed"
        assert db.delivery_routes.rows[0]["completed_at"]
        assert "amount_paid" not in db.orders.rows[0]
        assert db.orders.rows[0]["paymentStatus"] == "UNPAID"
        assert db.orders.rows[0]["balance"] == 10
        assert db.delivery_routes.rows[0]["stops"][0]["status"] == "Delivered"
        assert db.delivery_routes.rows[0]["status"] == "completed"
        assert db.delivery_routes.rows[0]["completed_at"]
        assert (ORDER["id"], {"type": "status", "status": "Delivered"}) in sockets.order_events
        assert any(event.get("type") == "route_completed" for _, _, event in sockets.supplier_events)
    finally:
        teardown_function()


def test_geofence_requires_close_and_accurate_gps(monkeypatch):
    client, db, _sockets = setup(monkeypatch)
    try:
        inaccurate = client.post(f"/api/delivery-routes/shared/{TOKEN}/location", json={
            "lat": 41.7, "lon": 44.8, "accuracy_meters": 30,
        })
        outside_radius = client.post(f"/api/delivery-routes/shared/{TOKEN}/location", json={
            "lat": 41.701, "lon": 44.8, "accuracy_meters": 5,
        })

        assert inaccurate.status_code == outside_radius.status_code == 200
        assert inaccurate.json()["delivered_order_ids"] == []
        assert outside_radius.json()["delivered_order_ids"] == []
        assert db.orders.rows[0]["status"] == "In Transit"
        assert db.delivery_routes.rows[0]["tracking_active"] is True
    finally:
        teardown_function()


def test_geofence_does_not_deliver_unpaid_bank_transfer(monkeypatch):
    client, db, _sockets = setup(monkeypatch)
    db.orders.rows[0]["payment_method"] = "bank_transfer"
    try:
        response = client.post(f"/api/delivery-routes/shared/{TOKEN}/location", json={
            "lat": 41.7, "lon": 44.8, "accuracy_meters": 5,
        })

        assert response.status_code == 200, response.text
        assert response.json()["delivered_order_ids"] == []
        assert db.orders.rows[0]["status"] == "In Transit"
    finally:
        teardown_function()


def test_manual_delivery_fallback_still_works(monkeypatch):
    client, db, _sockets = setup(monkeypatch)
    try:
        response = client.post(
            f"/api/delivery-routes/shared/{TOKEN}/orders/{ORDER['id']}/deliver",
            json={"payment": "credit"},
        )

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "Delivered"
        assert db.orders.rows[0]["status"] == "Delivered"
        assert db.orders.rows[0]["delivered_on_credit"] is True
        assert "amount_paid" not in db.orders.rows[0]
        assert db.delivery_routes.rows[0]["status"] == "completed"
        shared_route = client.get(f"/api/delivery-routes/shared/{TOKEN}")
        assert shared_route.status_code == 200
        assert shared_route.json()["status"] == "completed"
    finally:
        teardown_function()


def test_supplier_delivery_status_archives_the_assigned_route(monkeypatch):
    client, db, _sockets = setup(monkeypatch)
    supplier = {"id": "supplier-1", "role": "supplier", "supplier_access_role": "global_admin"}
    server.app.dependency_overrides[server.get_current_user] = lambda: supplier
    try:
        response = client.put(f"/api/orders/{ORDER['id']}/status", json={"status": "Delivered"})

        assert response.status_code == 200, response.text
        assert db.orders.rows[0]["status"] == "Delivered"
        assert db.delivery_routes.rows[0]["status"] == "completed"
        assert db.delivery_routes.rows[0]["stops"][0]["status"] == "Delivered"
        assert db.delivery_routes.rows[0]["completed_at"]
    finally:
        teardown_function()


def test_active_route_list_excludes_completed_and_history_contains_only_completed(monkeypatch):
    client, db, _sockets = setup(monkeypatch)
    completed_route = copy.deepcopy(ROUTE)
    completed_route.update({"id": "route-2", "status": "completed", "completed_at": "2026-11-06T10:00:00+00:00"})
    db.delivery_routes.rows.append(completed_route)
    supplier = {"id": "supplier-1", "role": "supplier", "supplier_access_role": "global_admin"}
    server.app.dependency_overrides[server.get_current_user] = lambda: supplier
    try:
        active = client.get("/api/delivery-routes")
        history = client.get("/api/delivery-routes/history")

        assert active.status_code == history.status_code == 200
        assert [route["id"] for route in active.json()] == ["route-1"]
        assert [route["id"] for route in history.json()] == ["route-2"]
    finally:
        teardown_function()


def test_active_route_list_archives_legacy_assigned_routes_with_terminal_orders(monkeypatch):
    client, db, _sockets = setup(monkeypatch, order_status="Delivered")
    supplier = {"id": "supplier-1", "role": "supplier", "supplier_access_role": "global_admin"}
    server.app.dependency_overrides[server.get_current_user] = lambda: supplier
    try:
        active = client.get("/api/delivery-routes")
        history = client.get("/api/delivery-routes/history")

        assert active.status_code == history.status_code == 200
        assert active.json() == []
        assert [route["id"] for route in history.json()] == ["route-1"]
        assert db.delivery_routes.rows[0]["status"] == "completed"
    finally:
        teardown_function()


def test_store_tracking_only_returns_own_in_transit_order(monkeypatch):
    client, db, _sockets = setup(monkeypatch)
    store = {"id": "store-1", "role": "retailer", "store_access_role": "global_admin"}
    server.app.dependency_overrides[server.get_current_user] = lambda: store
    try:
        active = client.get("/api/orders/order-1/tracking")
        assert active.status_code == 200, active.text
        assert active.json()["order_id"] == "order-1"

        db.orders.rows[0]["status"] = "Delivered"
        delivered = client.get("/api/orders/order-1/tracking")
        assert delivered.status_code == 409

        other_store = {**store, "id": "store-2"}
        server.app.dependency_overrides[server.get_current_user] = lambda: other_store
        unauthorized = client.get("/api/orders/order-1/tracking")
        assert unauthorized.status_code == 404
    finally:
        teardown_function()
