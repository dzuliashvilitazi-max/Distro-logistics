import asyncio

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

import server


RETAILER = {"id": "store-1", "role": "retailer", "store_access_role": "global_admin",
           "business_name": "Corner Shop", "city": "თბილისი", "status": "active"}
SUPPLIER = {"id": "distributor-1", "role": "supplier", "business_name": "Distro",
            "status": "active", "identification_number": "123456789"}
ORDER_BODY = {
    "items": [{"product_id": "product-1", "name": "Forged Tea", "supplier_id": "distributor-1",
                "quantity": 5, "unit_price": 0.01}],
    "delivery_address": "Store address", "payment_method": "cash",
}


@pytest.fixture
def order_client(monkeypatch):
    database = AsyncMongoMockClient()["store_order_connections_test"]

    async def seed():
        await database.users.insert_many([dict(RETAILER), dict(SUPPLIER)])
        await database.products.insert_one({
            "id": "product-1", "supplier_id": "distributor-1", "name": "Tea",
            "image": "", "price_per_unit": 12.0, "moq": 1, "stock": 100,
            "tier_pricing": [{"min_qty": 10, "price": 10.0}],
        })
        await database.custom_prices.insert_one({
            "store_id": "store-1", "distributor_id": "distributor-1",
            "product_id": "product-1", "custom_price": 7.5,
        })

    asyncio.run(seed())
    monkeypatch.setattr(server, "db", database)
    monkeypatch.setattr(server, "get_settings", lambda: asyncio.sleep(0, result={
        "fee_type": "percent", "fee_value": 0, "fee_payer": "supplier",
    }))
    monkeypatch.setattr(server, "resolve_store_branch", lambda *_args: asyncio.sleep(0, result="branch-1"))
    monkeypatch.setattr(server, "_store_city", lambda *_args: asyncio.sleep(0, result=None))
    monkeypatch.setattr(server, "_store_routing_address", lambda *_args: asyncio.sleep(0, result="Store address"))
    monkeypatch.setattr(server, "_warehouse_for_supplier_location", lambda *_args: asyncio.sleep(0, result=None))
    monkeypatch.setattr(server, "deduct_inventory", lambda *_args, **_kwargs: asyncio.sleep(0, result=[]))
    monkeypatch.setattr(server, "log_financial_event", lambda *_args, **_kwargs: asyncio.sleep(0))
    monkeypatch.setattr(server, "notify", lambda *_args, **_kwargs: asyncio.sleep(0))
    monkeypatch.setattr(server, "schedule_whatsapp_alert", lambda *_args, **_kwargs: None)
    server.app.dependency_overrides[server.get_current_user] = lambda: RETAILER
    yield TestClient(server.app), database
    server.app.dependency_overrides.pop(server.get_current_user, None)


def test_store_cannot_create_order_before_connection_approval(order_client):
    client, database = order_client
    asyncio.run(database.store_distributor_connections.insert_one({
        "id": "connection-1", "store_id": "store-1", "distributor_id": "distributor-1",
        "status": "PENDING",
    }))

    response = client.post("/api/orders", json=ORDER_BODY)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "CONNECTION_REQUIRED"
    assert asyncio.run(database.orders.count_documents({})) == 0


def test_approved_connection_uses_custom_price_not_client_price(order_client):
    client, database = order_client
    asyncio.run(database.store_distributor_connections.insert_one({
        "id": "connection-1", "store_id": "store-1", "distributor_id": "distributor-1",
        "status": "APPROVED", "discount_percent": 0,
    }))

    response = client.post("/api/orders", json=ORDER_BODY)

    assert response.status_code == 200, response.text
    order = response.json()["orders"][0]
    assert order["items"][0]["unit_price"] == 7.5
    assert order["items"][0]["name"] == "Tea"
    assert order["total"] == 37.5
    stored = asyncio.run(database.orders.find_one({"id": order["id"]}))
    assert stored["items"][0]["unit_price"] == 7.5


@pytest.mark.parametrize("gateway", ["tbc", "bog"])
def test_hosted_bank_checkout_requires_approved_connection(order_client, monkeypatch, gateway):
    client, database = order_client
    asyncio.run(database.store_distributor_connections.insert_one({
        "id": "connection-1", "store_id": "store-1", "distributor_id": "distributor-1",
        "status": "PENDING",
    }))
    monkeypatch.setenv("APP_BASE_URL", "https://shop.example")
    monkeypatch.setattr(server, "validate_tbc_configuration", lambda: None)
    monkeypatch.setattr(server, "validate_bog_configuration", lambda: None)

    response = client.post(f"/api/payments/{gateway}/checkout", json=ORDER_BODY)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "CONNECTION_REQUIRED"
    assert asyncio.run(database.orders.count_documents({})) == 0
