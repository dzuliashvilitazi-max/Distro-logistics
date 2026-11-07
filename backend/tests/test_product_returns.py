import asyncio

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

import server


RETAILER = {"id": "store-1", "role": "retailer", "store_access_role": "global_admin", "business_name": "Store"}
SUPPLIER = {"id": "supplier-1", "role": "supplier", "supplier_access_role": "global_admin", "business_name": "Distro"}


@pytest.fixture
def returns_client(monkeypatch):
    database = AsyncMongoMockClient()["product_returns_test"]

    async def seed():
        await database.orders.insert_one({
            "id": "order-1", "order_no": "ORD-1", "retailer_id": "store-1", "retailer_name": "Store",
            "supplier_id": "supplier-1", "supplier_name": "Distro", "warehouse_id": "warehouse-1",
            "branch_id": "branch-1", "status": "Delivered", "external_order": False,
            "total": 50, "service_fee": 2.5, "commission_status": "Active",
            "items": [{"product_id": "product-1", "name": "Tea", "quantity": 5, "unit_price": 10}],
        })
        await database.warehouse_inventory.insert_one({
            "supplier_id": "supplier-1", "product_id": "product-1", "warehouse_id": "warehouse-1", "stock": 7,
        })
        await database.products.insert_one({"id": "product-1", "supplier_id": "supplier-1", "stock": 7})

    asyncio.run(seed())
    monkeypatch.setattr(server, "db", database)

    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(server, "notify", noop)
    server.app.dependency_overrides[server.get_current_user] = lambda: RETAILER
    yield TestClient(server.app), database
    server.app.dependency_overrides.pop(server.get_current_user, None)


def test_return_request_pending_and_supplier_approval_updates_stock_once(returns_client):
    client, database = returns_client
    request = client.post("/api/returns", json={
        "order_id": "order-1", "product_id": "product-1", "quantity": 2,
        "reason": "damaged", "comment": "Two boxes were damaged.",
    })
    assert request.status_code == 201, request.text
    return_id = request.json()["id"]
    assert request.json()["status"] == "PENDING"

    server.app.dependency_overrides[server.get_current_user] = lambda: SUPPLIER
    decision = client.patch(f"/api/supplier/returns/{return_id}/decision", json={
        "decision": "APPROVED", "comment": "Checked and accepted.",
    })
    assert decision.status_code == 200, decision.text
    assert decision.json()["status"] == "APPROVED"

    stock = asyncio.run(database.warehouse_inventory.find_one({"product_id": "product-1"}))
    order = asyncio.run(database.orders.find_one({"id": "order-1"}))
    assert stock["stock"] == 9
    assert order["items"][0]["returned_quantity"] == 2
    assert asyncio.run(database.inventory_movements.count_documents({"return_id": return_id})) == 2

    repeated = client.patch(f"/api/supplier/returns/{return_id}/decision", json={"decision": "APPROVED"})
    assert repeated.status_code == 409
    assert asyncio.run(database.warehouse_inventory.find_one({"product_id": "product-1"}))["stock"] == 9


def test_post_invoice_returns_create_partial_and_full_commission_credits(returns_client):
    client, database = returns_client
    asyncio.run(database.orders.update_one(
        {"id": "order-1"}, {"$set": {"invoice_id": "invoice-1"}},
    ))

    partial = client.post("/api/returns", json={
        "order_id": "order-1", "product_id": "product-1", "quantity": 2,
        "reason": "damaged", "comment": "Two units returned.",
    })
    assert partial.status_code == 201
    server.app.dependency_overrides[server.get_current_user] = lambda: SUPPLIER
    partial_result = client.patch(f"/api/supplier/returns/{partial.json()['id']}/decision", json={
        "decision": "APPROVED", "comment": "Accepted.",
    })
    assert partial_result.status_code == 200, partial_result.text

    partial_credit = asyncio.run(database.commission_ledger.find_one({"source_id": f"return:{partial.json()['id']}"}))
    assert partial_credit["status"] == "Refunded"
    assert partial_credit["settlement_status"] == "pending"
    assert partial_credit["amount"] == 1.0
    assert asyncio.run(database.orders.find_one({"id": "order-1"}))["commission_status"] == "Active"

    server.app.dependency_overrides[server.get_current_user] = lambda: RETAILER
    full = client.post("/api/returns", json={
        "order_id": "order-1", "product_id": "product-1", "quantity": 3,
        "reason": "wrong_item", "comment": "Remaining units returned.",
    })
    assert full.status_code == 201
    server.app.dependency_overrides[server.get_current_user] = lambda: SUPPLIER
    full_result = client.patch(f"/api/supplier/returns/{full.json()['id']}/decision", json={
        "decision": "APPROVED", "comment": "Accepted.",
    })
    assert full_result.status_code == 200, full_result.text

    rows = asyncio.run(database.commission_ledger.find({"order_id": "order-1"}).to_list(None))
    assert sum(row["amount"] for row in rows) == 2.5
    assert asyncio.run(database.orders.find_one({"id": "order-1"}))["commission_status"] == "Refunded"


def test_post_invoice_cancellation_creates_one_commission_credit(returns_client):
    client, database = returns_client
    asyncio.run(database.orders.update_one(
        {"id": "order-1"}, {"$set": {"invoice_id": "invoice-1"}},
    ))
    server.app.dependency_overrides[server.get_current_user] = lambda: SUPPLIER

    first = client.put("/api/orders/order-1/status", json={"status": "Cancelled"})
    second = client.put("/api/orders/order-1/status", json={"status": "Cancelled"})

    assert first.status_code == second.status_code == 200
    order = asyncio.run(database.orders.find_one({"id": "order-1"}))
    credit = asyncio.run(database.commission_ledger.find_one({"id": "credit:cancellation:order-1"}))
    assert order["commission_status"] == "Cancelled"
    assert credit["status"] == "Cancelled"
    assert credit["settlement_status"] == "pending"
    assert credit["amount"] == 2.5
    assert asyncio.run(database.commission_ledger.count_documents({"type": "credit"})) == 1


@pytest.mark.parametrize(("credit_amount", "expected_amount", "expected_remaining"), [
    (2.5, 7.5, 0),
    (15, 0, 5),
])
def test_pending_return_credit_is_applied_to_next_commission_invoice(
    returns_client, monkeypatch, credit_amount, expected_amount, expected_remaining,
):
    _client, database = returns_client
    issued_return = "return-issued-1"
    asyncio.run(database.orders.update_one(
        {"id": "order-1"}, {"$set": {"invoice_id": "invoice-1"}},
    ))
    asyncio.run(database.commission_ledger.insert_one({
        "id": f"credit:return:{issued_return}", "type": "credit", "status": "Refunded",
        "settlement_status": "pending", "supplier_id": "supplier-1", "order_id": "order-1",
        "order_no": "ORD-1", "source_id": f"return:{issued_return}", "reason": "Approved return",
        "amount": credit_amount, "remaining_amount": credit_amount, "currency": "GEL",
        "available_period": "2026-10", "created_at": "2026-10-25T10:00:00+00:00",
    }))
    asyncio.run(database.users.insert_one({
        "id": "supplier-1", "role": "supplier", "business_name": "Distro",
        "identification_number": "123456789", "email": "",
    }))
    asyncio.run(database.orders.insert_one({
        "id": "order-2", "order_no": "ORD-2", "supplier_id": "supplier-1",
        "supplier_name": "Distro", "retailer_name": "Store", "status": "Delivered",
        "external_order": False, "total": 200, "service_fee": 10,
        "delivered_at": "2026-10-26T10:00:00+00:00", "items": [],
    }))

    async def fixed_settings():
        return {key: value for key, value in server.ISSUER_DEFAULTS.items()}

    async def no_op(*_args, **_kwargs):
        return None

    monkeypatch.setattr(server, "get_settings", fixed_settings)
    monkeypatch.setattr(server, "notify", no_op)
    invoices = asyncio.run(server.do_generate_invoices("2026-10"))

    assert len(invoices) == 1
    invoice = asyncio.run(database.invoices.find_one({"period": "2026-10"}))
    credit_line = next(line for line in invoice["line_items"] if line.get("type") == "credit_note")
    assert invoice["gross_commission"] == 10
    assert invoice["credit_adjustment"] == min(10, credit_amount)
    assert invoice["amount"] == expected_amount
    assert credit_line["commission"] == -invoice["credit_adjustment"]
    credit = asyncio.run(database.commission_ledger.find_one({"id": f"credit:return:{issued_return}"}))
    assert credit["settlement_status"] == ("applied" if expected_remaining == 0 else "pending")
    assert credit["remaining_amount"] == expected_remaining
    if expected_amount == 0:
        assert invoice["status"] == "paid"
        assert invoice["paid_via"] == "commission_credit"
        assert invoice["paid_at"]


def test_return_quantity_is_limited_and_rejection_does_not_change_stock(returns_client):
    client, database = returns_client
    invalid = client.post("/api/returns", json={
        "order_id": "order-1", "product_id": "product-1", "quantity": 6,
        "reason": "other", "comment": "Too many.",
    })
    assert invalid.status_code == 409

    request = client.post("/api/returns", json={
        "order_id": "order-1", "product_id": "product-1", "quantity": 2,
        "reason": "wrong_item", "comment": "Wrong item.",
    })
    assert request.status_code == 201
    server.app.dependency_overrides[server.get_current_user] = lambda: SUPPLIER
    rejected = client.patch(f"/api/supplier/returns/{request.json()['id']}/decision", json={
        "decision": "REJECTED", "comment": "Outside return policy.",
    })
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "REJECTED"
    assert asyncio.run(database.warehouse_inventory.find_one({"product_id": "product-1"}))["stock"] == 7


def test_return_lists_are_role_scoped(returns_client):
    client, _database = returns_client
    created = client.post("/api/returns", json={
        "order_id": "order-1", "product_id": "product-1", "quantity": 1,
        "reason": "quality_issue", "comment": "Quality concern.",
    })
    assert created.status_code == 201
    assert len(client.get("/api/returns/mine").json()) == 1
    server.app.dependency_overrides[server.get_current_user] = lambda: SUPPLIER
    rows = client.get("/api/supplier/returns", params={"status": "PENDING"})
    assert rows.status_code == 200 and len(rows.json()) == 1


def test_failed_warehouse_adjustment_is_retryable_without_store_deduction(returns_client, monkeypatch):
    client, database = returns_client
    request = client.post("/api/returns", json={
        "order_id": "order-1", "product_id": "product-1", "quantity": 2,
        "reason": "damaged", "comment": "Damaged on delivery.",
    })
    assert request.status_code == 201
    return_id = request.json()["id"]
    server.app.dependency_overrides[server.get_current_user] = lambda: SUPPLIER
    restock = server._apply_supplier_return_restock

    async def unavailable(*_args, **_kwargs):
        raise RuntimeError("temporary inventory outage")

    monkeypatch.setattr(server, "_apply_supplier_return_restock", unavailable)
    failed = client.patch(f"/api/supplier/returns/{return_id}/decision", json={"decision": "APPROVED"})
    assert failed.status_code == 503
    assert asyncio.run(database.product_returns.find_one({"id": return_id}))["status"] == "APPROVING"
    order = asyncio.run(database.orders.find_one({"id": "order-1"}))
    assert order["items"][0].get("returned_quantity", 0) == 0

    monkeypatch.setattr(server, "_apply_supplier_return_restock", restock)
    retried = client.patch(f"/api/supplier/returns/{return_id}/decision", json={"decision": "APPROVED"})
    assert retried.status_code == 200
    assert retried.json()["status"] == "APPROVED"
    assert asyncio.run(database.warehouse_inventory.find_one({"product_id": "product-1"}))["stock"] == 9


def test_approved_return_reduces_store_on_hand_once(returns_client):
    client, database = returns_client
    asyncio.run(database.store_inventory.insert_one({
        "retailer_id": "store-1", "branch_id": "branch-1", "product_id": "product-1", "on_hand": 5,
    }))
    created = client.post("/api/returns", json={
        "order_id": "order-1", "product_id": "product-1", "quantity": 2,
        "reason": "damaged", "comment": "Damaged boxes.",
    })
    return_id = created.json()["id"]
    server.app.dependency_overrides[server.get_current_user] = lambda: SUPPLIER
    assert client.patch(f"/api/supplier/returns/{return_id}/decision", json={"decision": "APPROVED"}).status_code == 200
    assert asyncio.run(database.store_inventory.find_one({"product_id": "product-1"}))["on_hand"] == 3
    assert asyncio.run(database.warehouse_inventory.find_one({"product_id": "product-1"}))["stock"] == 9
