import asyncio
import copy
import sys
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
            if "$ne" in expected and value == expected["$ne"]:
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

    async def delete_many(self, query):
        self.rows = [row for row in self.rows if not matches(row, query)]

    async def find_one_and_update(self, query, update, upsert=False, **_kwargs):
        for row in self.rows:
            if matches(row, query):
                row.update(copy.deepcopy(update.get("$set", {})))
                return copy.deepcopy(row)
        if not upsert:
            return None
        row = {key: value for key, value in query.items() if not isinstance(value, dict)}
        row.update(copy.deepcopy(update.get("$setOnInsert", {})))
        row.update(copy.deepcopy(update.get("$set", {})))
        self.rows.append(row)
        return copy.deepcopy(row)

    async def update_one(self, query, update):
        for row in self.rows:
            if matches(row, query):
                row.update(copy.deepcopy(update.get("$set", {})))
                return SimpleNamespace(modified_count=1)
        return SimpleNamespace(modified_count=0)


SUPPLIER = {"id": "distributor-1", "role": "supplier", "business_name": "Distro"}
RETAILER = {
    "id": "store-1", "role": "retailer", "store_access_role": "global_admin",
    "business_name": "Corner Shop", "city": "თბილისი", "status": "active",
    "establishment_type": "grocery", "entityGroup": "RETAIL",
}


def setup(monkeypatch, user, users=None):
    database = SimpleNamespace(
        users=Collection(users or [RETAILER]),
        store_distributor_connections=Collection(),
        connection_audit_logs=Collection(),
        custom_prices=Collection(),
    )
    monkeypatch.setattr(server, "db", database)
    monkeypatch.setattr(server, "notify", _notify)
    server.app.dependency_overrides[server.get_current_user] = lambda: user
    return TestClient(server.app), database


async def _notify(*_args, **_kwargs):
    return None


def teardown_function():
    server.app.dependency_overrides.pop(server.get_current_user, None)


def test_distributor_can_filter_registered_stores(monkeypatch):
    restaurant = {
        **RETAILER, "id": "store-2", "business_name": "Cafe", "city": "ბათუმი",
        "establishment_type": "restaurant_cafe_bar", "entityGroup": "SERVICE",
    }
    client, _database = setup(monkeypatch, SUPPLIER, [RETAILER, restaurant])
    try:
        response = client.get("/api/connections/discover-stores", params={
            "city": "თბილისი", "sector": "grocery", "business_type": "RETAIL",
        })
        assert response.status_code == 200, response.text
        assert [store["id"] for store in response.json()] == ["store-1"]
        assert response.json()[0]["sector"] == "grocery"
    finally:
        teardown_function()


def test_supplier_invitation_is_audited_and_store_acceptance_unlocks_catalog(monkeypatch):
    client, database = setup(monkeypatch, SUPPLIER)
    try:
        invite = client.post("/api/connections/invite", json={"store_id": "store-1"})
        assert invite.status_code == 201, invite.text
        connection = database.store_distributor_connections.rows[0]
        assert connection["status"] == "PENDING"
        assert connection["requested_by_role"] == "supplier"
        assert database.connection_audit_logs.rows[0]["action"] == "invitation_sent"
        products = [{"id": "product-1", "supplier_id": SUPPLIER["id"], "price_per_unit": 12.5, "tier_pricing": []}]
        visible_before_approval = asyncio.run(server._apply_partner_pricing(
            [dict(products[0])], RETAILER["id"],
        ))
        assert visible_before_approval[0]["price_per_unit"] == 12.5
        assert visible_before_approval[0]["can_order"] is False
        assert visible_before_approval[0]["connection_status"] == "PENDING"
        cannot_approve_own_invitation = client.patch("/api/connections/approve", json={
            "store_id": "store-1", "status": "APPROVED",
        })
        assert cannot_approve_own_invitation.status_code == 409

        server.app.dependency_overrides[server.get_current_user] = lambda: RETAILER
        response = client.patch("/api/connections/respond-invitation", json={
            "connection_id": connection["id"], "status": "APPROVED",
        })
        assert response.status_code == 200, response.text
        assert database.store_distributor_connections.rows[0]["status"] == "APPROVED"
        assert database.connection_audit_logs.rows[-1]["action"] == "invitation_accepted"

        visible = asyncio.run(server._apply_partner_pricing([dict(products[0])], RETAILER["id"]))
        assert visible[0]["isLocked"] is False
        assert visible[0]["price_per_unit"] == 12.5
        assert visible[0]["can_order"] is True
    finally:
        teardown_function()


def test_retailer_request_still_allows_supplier_decision_and_audit(monkeypatch):
    client, database = setup(monkeypatch, RETAILER, [RETAILER, SUPPLIER])
    try:
        request = client.post("/api/connections/request", json={"distributor_id": SUPPLIER["id"]})
        assert request.status_code == 201, request.text
        assert database.connection_audit_logs.rows[0]["action"] == "request_sent"

        server.app.dependency_overrides[server.get_current_user] = lambda: SUPPLIER
        decision = client.patch("/api/connections/approve", json={
            "store_id": RETAILER["id"], "status": "APPROVED",
        })
        assert decision.status_code == 200, decision.text
        assert database.store_distributor_connections.rows[0]["status"] == "APPROVED"
        assert database.connection_audit_logs.rows[-1]["action"] == "request_approved"
    finally:
        teardown_function()


def test_non_owner_cannot_accept_distributor_invitation(monkeypatch):
    client, database = setup(monkeypatch, SUPPLIER)
    try:
        client.post("/api/connections/invite", json={"store_id": "store-1"})
        staff = {**RETAILER, "id": "staff-1", "store_access_role": "branch_manager", "retailer_id": "store-1"}
        server.app.dependency_overrides[server.get_current_user] = lambda: staff
        response = client.patch("/api/connections/respond-invitation", json={
            "connection_id": database.store_distributor_connections.rows[0]["id"], "status": "APPROVED",
        })
        assert response.status_code == 403
        assert database.store_distributor_connections.rows[0]["status"] == "PENDING"
    finally:
        teardown_function()