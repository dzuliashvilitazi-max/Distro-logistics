import asyncio

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

import server


@pytest.fixture
def broadcast_client(monkeypatch):
    database = AsyncMongoMockClient()["admin_broadcast_test"]

    async def seed():
        await database.users.insert_many([
            {"id": "admin-1", "role": "admin", "status": "active", "name": "Admin"},
            {"id": "store-1", "role": "retailer", "status": "active"},
            {"id": "supplier-1", "role": "supplier", "status": "active"},
            {"id": "store-suspended", "role": "retailer", "status": "suspended"},
        ])

    asyncio.run(seed())
    monkeypatch.setattr(server, "db", database)
    monkeypatch.setattr(server.web_push, "schedule", lambda _db, _notification: None)
    client = TestClient(server.app)
    client.headers["Authorization"] = f"Bearer {server.create_token('admin-1', {'role': 'admin'})}"
    return client, database


def test_admin_broadcast_targets_segment_and_records_audit(broadcast_client):
    client, database = broadcast_client
    response = client.post("/api/admin/broadcast-notification", json={
        "text": "A new Distro Logistics app update is available.", "audience": "stores",
    })

    assert response.status_code == 200
    assert response.json()["recipient_count"] == 1
    broadcast_id = response.json()["id"]
    campaign = asyncio.run(database.broadcast_campaigns.find_one({"id": broadcast_id}))
    assert campaign["failed_count"] == 0, campaign
    notifications = asyncio.run(database.notifications.find({"broadcast_id": broadcast_id}).to_list(None))
    assert len(notifications) == 1
    assert notifications[0]["user_id"] == "store-1"

    history = client.get("/api/admin/broadcast-notification/history").json()
    assert history[0]["status"] == "completed"
    assert history[0]["text"] == "A new Distro Logistics app update is available."

    audit = asyncio.run(database.financial_audit_logs.find_one({"entity_id": broadcast_id}))
    assert audit["actor_id"] == "admin-1"
    assert audit["after"]["text"] == history[0]["text"]

    asyncio.run(database.broadcast_campaigns.update_one(
        {"id": broadcast_id}, {"$set": {"status": "queued"}},
    ))
    asyncio.run(server._deliver_broadcast(broadcast_id))
    retried = asyncio.run(database.notifications.find({"broadcast_id": broadcast_id}).to_list(None))
    assert len(retried) == 1


def test_broadcast_all_excludes_admins_and_suspended_users(broadcast_client):
    client, database = broadcast_client
    response = client.post("/api/admin/broadcast-notification", json={
        "text": "Platform announcement", "audience": "all",
    })

    assert response.status_code == 200
    broadcast_id = response.json()["id"]
    notifications = asyncio.run(database.notifications.find({"broadcast_id": broadcast_id}).to_list(None))
    recipients = {row["user_id"] for row in notifications}
    assert recipients == {"store-1", "supplier-1"}


def test_broadcast_endpoints_require_admin(broadcast_client):
    client, _database = broadcast_client
    client.headers["Authorization"] = f"Bearer {server.create_token('store-1', {'role': 'retailer'})}"

    response = client.post("/api/admin/broadcast-notification", json={
        "text": "Platform announcement", "audience": "all",
    })
    history = client.get("/api/admin/broadcast-notification/history")
    assert response.status_code == 403
    assert history.status_code == 403


def test_push_payload_titles_and_targets_cover_messages_and_broadcasts():
    assert server.web_push.PUSH_TITLES["broadcast"]
    assert server.web_push.PUSH_TITLES["message"]
    assert server.web_push.push_url({"type": "broadcast"}, "retailer") == "/messages"
    assert server.web_push.push_url({"type": "message"}, "supplier") == "/messages"
    assert server.web_push.push_url({"type": "support"}, "retailer") == "/support"
    assert server.web_push.push_url({"type": "support"}, "admin") == "/admin/support"