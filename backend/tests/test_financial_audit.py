from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

import server


@pytest.fixture
def audit_client(monkeypatch):
    database = AsyncMongoMockClient()["financial_audit_test"]
    now = datetime.now(timezone.utc)
    rows = [
        {"id": "evt-success", "action": "payment_recorded", "entity": "order", "entity_id": "o1",
         "actor_id": "s1", "actor_name": "Supplier", "at": now.isoformat(), "status": "success",
         "amount": 12.5, "currency": "GEL", "before": {"iban": "GE00PRIVATE"}},
        {"id": "evt-pending", "action": "bank_payment_pending", "entity": "bank_payment", "entity_id": "p1",
         "actor_id": "r1", "actor_name": "Store", "at": (now - timedelta(seconds=1)).isoformat(),
         "status": "pending", "amount": 50.0},
        {"id": "evt-error", "action": "bank_payment_failed", "entity": "bank_payment", "entity_id": "p2",
         "actor_id": "system", "actor_name": "Payment gateway", "at": (now - timedelta(seconds=2)).isoformat(),
         "status": "error", "amount": 25.0},
        {"id": "evt-legacy", "action": "warehouse_delete_blocked", "entity": "warehouse", "entity_id": "w1",
         "actor_id": "s1", "actor_name": "Supplier", "at": (now - timedelta(seconds=3)).isoformat()},
    ]

    async def seed():
        await database.users.insert_many([
            {"id": "admin", "role": "admin"},
            {"id": "store", "role": "retailer"},
        ])
        await database.financial_audit_logs.insert_many(rows)
        await database.bank_payments.insert_many([
            {"id": "pay-success", "retailer_id": "store", "amount": 80.0, "currency": "GEL",
             "gateway": "bog", "status": "Succeeded", "created_at": now.isoformat(), "updated_at": now.isoformat()},
            {"id": "pay-pending", "retailer_id": "store", "amount": 40.0, "currency": "GEL",
             "gateway": "tbc", "status": "Pending", "created_at": (now - timedelta(seconds=4)).isoformat(),
             "updated_at": (now - timedelta(seconds=4)).isoformat()},
            {"id": "pay-error", "retailer_id": "store", "amount": 20.0, "currency": "GEL",
             "gateway": "bog", "status": "Failed", "created_at": (now - timedelta(seconds=5)).isoformat(),
             "updated_at": (now - timedelta(seconds=5)).isoformat()},
        ])

    import asyncio
    asyncio.run(seed())
    monkeypatch.setattr(server, "db", database)
    client = TestClient(server.app)
    client.headers["Authorization"] = f"Bearer {server.create_token('admin', {'role': 'admin'})}"
    return client


def test_audit_log_filters_status_and_redacts_snapshots(audit_client):
    pending = audit_client.get("/api/admin/financials/audit-log", params={"status": "pending"}).json()
    assert pending["total"] == 1
    assert pending["events"][0]["id"] == "gateway:pay-pending"

    errors = audit_client.get("/api/admin/financials/audit-log", params={"status": "error"}).json()
    assert errors["total"] == 2
    assert {event["status"] for event in errors["events"]} == {"error"}

    success = audit_client.get("/api/admin/financials/audit-log", params={"status": "success"}).json()
    assert success["total"] == 2
    payment_record = next(event for event in success["events"] if event["id"] == "evt-success")
    assert "before" not in payment_record


def test_audit_log_paginates_and_requires_admin(audit_client):
    first = audit_client.get("/api/admin/financials/audit-log", params={"page_size": 2}).json()
    second = audit_client.get("/api/admin/financials/audit-log", params={"page": 2, "page_size": 2}).json()
    assert first["total"] == 5 and len(first["events"]) == len(second["events"]) == 2
    assert set(event["id"] for event in first["events"]).isdisjoint(event["id"] for event in second["events"])

    audit_client.headers["Authorization"] = f"Bearer {server.create_token('store', {'role': 'retailer'})}"
    assert audit_client.get("/api/admin/financials/audit-log").status_code == 403


def test_financial_event_logger_sets_normalized_status(audit_client):
    import asyncio
    asyncio.run(server.log_financial_event(
        "bank_payment_pending", {"id": "store", "name": "Store"}, "bank_payment", "p3", amount=15.0,
    ))
    created = asyncio.run(server.db.financial_audit_logs.find_one({"entity_id": "p3"}))
    assert created["status"] == "pending" and created["amount"] == 15.0
