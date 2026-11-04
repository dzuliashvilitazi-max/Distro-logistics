import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient
from bson.decimal128 import Decimal128

import server


@pytest.fixture
def pricing_client(monkeypatch):
    database = AsyncMongoMockClient()["smart_pricing_test"]
    now = datetime.now(timezone.utc)

    async def seed():
        await database.products.insert_one({"id": "product-1", "name": "Tea"})
        await database.orders.insert_one({
            "id": "purchase-1", "retailer_id": "store-1", "status": "Delivered",
            "external_order": False, "items": [{"product_id": "product-1", "unit_price": "10.00"}],
        })
        await database.pos_sales.insert_many([
            {"retailer_id": f"store-{index}", "items": [{
                "product_id": "product-1", "retail_price": Decimal128(str(price)),
            }]} for index, price in enumerate((20, 20, 20), start=2)
        ])
        await database.pos_sales.insert_many([
            {"retailer_id": "store-2", "items": [{
                "product_id": "product-1", "retail_price": Decimal128("100"),
            }]}
            for _ in range(5)
        ])
        await database.market_price_benchmarks.insert_many([
            {"fingerprint": f"external-{index}", "product_id": "product-1", "source": f"shop-{index}",
             "source_url": f"https://market{index}.example/item/tea", "price": Decimal128(str(price)),
             "currency": "GEL", "confidence": Decimal128("0.95"),
             "observed_at": now - timedelta(days=2), "status": "active"}
            for index, price in enumerate((28, 30, 32), start=1)
        ])

    asyncio.run(seed())
    monkeypatch.setattr(server, "db", database)
    client = TestClient(server.app)
    return client, database


@pytest.fixture(autouse=True)
def clear_actor_override():
    yield
    server.app.dependency_overrides.pop(server.get_current_user, None)


def set_actor(actor):
    server.app.dependency_overrides[server.get_current_user] = lambda: actor


def test_smart_price_blends_internal_and_external_market_data(pricing_client):
    client, _database = pricing_client
    set_actor({"id": "store-1", "role": "retailer", "store_access_role": "global_admin"})
    response = client.post("/api/store/pricing/advisor", json={
        "order_id": "purchase-1", "product_id": "product-1",
    })
    try:
        assert response.status_code == 200
        advice = response.json()
        assert advice["unit_cost"] == 10
        assert advice["internal_market_median_retail_price"] == 20
        assert advice["internal_market_sample_retailers"] == 3
        assert advice["external_market_median_retail_price"] == 30
        assert advice["external_market_sample_sources"] == 3
        assert advice["market_reference_price"] == 23
        assert advice["target_margin_floor"] == 13.33
        assert advice["recommended_retail_price"] == 22.54
        assert advice["recommendation_basis"] == "market_benchmark"
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_external_benchmark_ingestion_is_admin_only_and_validates_source(pricing_client):
    client, database = pricing_client
    payload = {"benchmarks": [{
        "product_id": "product-1", "source": "marketplace-x",
        "source_url": "https://marketplace.example/products/tea",
        "price": "31.25", "currency": "GEL", "confidence": "0.95",
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }]}
    set_actor({"id": "store-1", "role": "retailer", "store_access_role": "global_admin"})
    denied = client.post("/api/admin/pricing/benchmarks", json=payload)
    assert denied.status_code == 403

    set_actor({"id": "admin-1", "role": "admin"})
    accepted = client.post("/api/admin/pricing/benchmarks", json=payload)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["accepted"] == 1
    stored = asyncio.run(database.market_price_benchmarks.find_one({"source": "marketplace-x"}))
    assert stored["price"] == Decimal128("31.25")

    insecure = {"benchmarks": [{**payload["benchmarks"][0], "source_url": "http://marketplace.example/item"}]}
    assert client.post("/api/admin/pricing/benchmarks", json=insecure).status_code == 422