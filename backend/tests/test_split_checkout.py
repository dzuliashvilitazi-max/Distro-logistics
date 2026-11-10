import asyncio

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

import server

RETAILER = {"id": "store-1", "role": "retailer", "store_access_role": "global_admin",
            "business_name": "Corner Shop", "city": "თბილისი", "status": "active"}


def supplier(sid, iban):
    return {"id": sid, "role": "supplier", "business_name": sid.upper(), "status": "active",
            "iban": iban, "bank_name": "Bank " + sid}


BODY = {
    "items": [
        {"product_id": "chips", "name": "x", "supplier_id": "d1", "quantity": 2, "unit_price": 0.01},
        {"product_id": "juice", "name": "x", "supplier_id": "d2", "quantity": 3, "unit_price": 0.01},
    ],
    "delivery_address": "Store address", "payment_method": "online",
}


@pytest.fixture
def split_client(monkeypatch):
    database = AsyncMongoMockClient()["split_checkout_test"]

    async def seed():
        await database.users.insert_many([RETAILER, supplier("d1", "GE00AA0000000000000001"), supplier("d2", "GE00BB0000000000000002")])
        await database.products.insert_many([
            {"id": "chips", "supplier_id": "d1", "name": "Chips", "price_per_unit": 10.0, "moq": 1, "stock": 50, "tier_pricing": []},
            {"id": "juice", "supplier_id": "d2", "name": "Juice", "price_per_unit": 4.0, "moq": 1, "stock": 50, "tier_pricing": []},
        ])
        await database.store_distributor_connections.insert_many([
            {"store_id": "store-1", "distributor_id": d, "status": "APPROVED", "discount_percent": 0} for d in ("d1", "d2")
        ])

    asyncio.run(seed())
    state = {"deducted": [], "restored": [], "fail_second_order": False}

    async def deduct(lines, **_kwargs):
        state["deducted"].extend(lines)
        return list(lines)

    async def restore(lines):
        state["restored"].extend(lines)

    monkeypatch.setattr(server, "db", database)
    monkeypatch.setattr(server, "get_settings", lambda: asyncio.sleep(0, result={"fee_type": "percent", "fee_value": 3, "fee_payer": "supplier"}))
    monkeypatch.setattr(server, "resolve_store_branch", lambda *_a: asyncio.sleep(0, result="branch-1"))
    monkeypatch.setattr(server, "_store_branch_delivery_location", lambda *_a: asyncio.sleep(0, result=("Store address", {"lat": 1, "lng": 1}, None)))
    monkeypatch.setattr(server, "_store_routing_address", lambda *_a: asyncio.sleep(0, result="Store address"))
    monkeypatch.setattr(server, "_warehouse_for_supplier_location", lambda *_a: asyncio.sleep(0, result=None))
    monkeypatch.setattr(server, "deduct_inventory", deduct)
    monkeypatch.setattr(server, "restore_inventory", restore)
    monkeypatch.setattr(server, "_user_cards", lambda _user: [{"id": "c1", "sim_status": "ok"}])
    monkeypatch.setattr(server, "log_financial_event", lambda *_a, **_k: asyncio.sleep(0))
    monkeypatch.setattr(server, "notify", lambda *_a, **_k: asyncio.sleep(0))
    monkeypatch.setattr(server, "schedule_whatsapp_alert", lambda *_a, **_k: None)
    server.app.dependency_overrides[server.get_current_user] = lambda: RETAILER
    yield TestClient(server.app), database, state
    server.app.dependency_overrides.pop(server.get_current_user, None)


def test_single_checkout_splits_orders_and_routes_payouts_per_distributor(split_client):
    client, database, _state = split_client
    response = client.post("/api/orders", json=BODY)
    assert response.status_code == 200, response.text
    data = response.json()
    orders = {o["supplier_id"]: o for o in data["orders"]}
    assert set(orders) == {"d1", "d2"}
    assert orders["d1"]["total"] == 20.0 and orders["d2"]["total"] == 12.0
    assert all(i["supplier_id"] == s for s, o in orders.items() for i in o["items"])
    assert data["charged"] == 32.0

    payouts = {p["supplier_id"]: p for p in asyncio.run(database.payouts.find({}).to_list(10))}
    assert payouts["d1"]["supplier_payout"] == 19.4 and payouts["d2"]["supplier_payout"] == 11.64
    assert payouts["d1"]["bank_account_snapshot"]["iban"] != payouts["d2"]["bank_account_snapshot"]["iban"]
    stored = asyncio.run(database.orders.find({}).to_list(10))
    assert {o["checkout_id"] for o in stored} == {data["checkout_id"]}
    assert all("service_fee" not in o for o in data["orders"])


def test_failed_order_creation_restores_stock_and_removes_partial_orders(split_client, monkeypatch):
    client, database, state = split_client
    calls = {"n": 0}
    original = server.notify

    async def failing_notify(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return await original(*args, **kwargs)

    monkeypatch.setattr(server, "notify", failing_notify)
    with pytest.raises(RuntimeError):
        client.post("/api/orders", json=BODY)
    assert asyncio.run(database.orders.count_documents({})) == 0
    assert asyncio.run(database.payouts.count_documents({})) == 0
    assert len(state["restored"]) == 2
