import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from test_inventory_sync import Collection

OWNER = {"id": "owner-1", "role": "retailer", "store_access_role": "global_admin"}


def staff_user(permissions=None, role="staff"):
    user = {"id": "staff-1", "role": "retailer", "retailer_id": "owner-1", "store_access_role": role}
    if permissions is not None:
        user["permissions"] = permissions
    return user


def as_user(monkeypatch, user, db=None):
    db = db or type("MemoryDB", (), {})()
    for name in ("orders", "pos_sales", "users", "store_branches", "store_expenses"):
        if not hasattr(db, name):
            setattr(db, name, Collection())
    monkeypatch.setattr(server, "db", db)
    server.app.dependency_overrides[server.get_current_user] = lambda: user
    return TestClient(server.app), db


def teardown_function():
    server.app.dependency_overrides.pop(server.get_current_user, None)


def test_staff_blocked_without_flags(monkeypatch):
    client, _ = as_user(monkeypatch, staff_user({"canViewFinancials": False}))
    assert client.get("/api/store/finance").status_code == 403
    assert client.get("/api/store/analytics").status_code == 403
    assert client.get("/api/store/branch-expenses").status_code == 403
    assert client.get("/api/store/integrations").status_code == 403
    assert client.post("/api/store/pricing/advisor", json={
        "order_id": "o1", "product_id": "p1",
    }).status_code == 403


def test_flag_grants_only_its_own_routes(monkeypatch):
    client, _ = as_user(monkeypatch, staff_user({"canChangePrices": True}))
    allowed = client.post("/api/store/pricing/advisor", json={"order_id": "o1", "product_id": "p1"})
    assert allowed.status_code == 404
    assert client.get("/api/store/finance").status_code == 403


def test_owner_passes_and_sees_all_flags(monkeypatch):
    client, _ = as_user(monkeypatch, OWNER)
    allowed = client.post("/api/store/pricing/advisor", json={"order_id": "o1", "product_id": "p1"})
    assert allowed.status_code == 404
    assert all(server.effective_store_permissions(OWNER).values())


def test_can_manage_orders_flag(monkeypatch):
    assert "canManageOrders" in server.STORE_PERMISSION_FLAGS
    client, _ = as_user(monkeypatch, staff_user({"canManageOrders": False}))
    assert client.post("/api/orders", json={"items": [], "supplier_id": "s"}).status_code in (403,)
    client, _ = as_user(monkeypatch, staff_user({"canManageOrders": False}))
    assert client.put("/api/orders/o1/status", json={"status": "Cancelled"}).status_code in (403, 404)


def test_staff_cannot_edit_permissions(monkeypatch):
    client, _ = as_user(monkeypatch, staff_user({f: True for f in server.STORE_PERMISSION_FLAGS}))
    assert client.put("/api/store/staff/staff-1", json={"permissions": {"canManageApi": True}}).status_code == 403
    assert client.get("/api/store/staff").status_code == 403


def test_owner_updates_permissions_and_validates_flags(monkeypatch):
    member = dict(staff_user(), name="A", email="a@x.ge")
    db = type("MemoryDB", (), {"users": Collection([member])})()
    client, db = as_user(monkeypatch, OWNER, db)
    bad = client.put("/api/store/staff/staff-1", json={"permissions": {"isAdmin": True}})
    assert bad.status_code == 422
    ok = client.put("/api/store/staff/staff-1", json={"permissions": {"canViewFinancials": True}})
    assert ok.status_code == 200, ok.text
    assert db.users.rows[0]["permissions"]["canViewFinancials"] is True
    assert db.users.rows[0]["permissions"]["canChangePrices"] is False
    listed = client.get("/api/store/staff").json()
    assert listed[0]["permissions"]["canViewFinancials"] is True
