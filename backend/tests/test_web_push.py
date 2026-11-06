import asyncio
import json
import logging

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient
from py_vapid import Vapid01

import server
import web_push


def test_deliver_uses_users_subscription_and_logs_sanitized_response(monkeypatch, caplog):
    database = AsyncMongoMockClient()["web_push_delivery_test"]
    endpoint = "https://push.example.test/subscription-secret"
    p256dh = "public-key-secret"
    auth = "auth-secret"

    async def seed():
        await database.push_subscriptions.insert_many([
            {"user_id": "recipient-1", "endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}},
            {"user_id": "another-user", "endpoint": "https://push.example.test/other", "keys": {"p256dh": "other", "auth": "other"}},
            {"user_id": "recipient-1", "endpoint": "https://push.example.test/malformed", "keys": {"p256dh": "missing-auth"}},
        ])
        await database.users.insert_one({"id": "recipient-1", "role": "retailer"})

    asyncio.run(seed())
    sent = []

    class Response:
        status_code = 201
        reason = "Created"
        text = f"accepted {endpoint} {p256dh} {auth}"

    def fake_webpush(**kwargs):
        sent.append(kwargs)
        return Response()

    async def fake_get_vapid(_database):
        return "test-vapid", "test-public-key"

    monkeypatch.setattr(web_push, "webpush", fake_webpush)
    monkeypatch.setattr(web_push, "get_vapid", fake_get_vapid)
    monkeypatch.setenv("VAPID_SUBJECT", "mailto:push@example.test")
    caplog.set_level(logging.INFO, logger="distro.push")

    asyncio.run(web_push.deliver(database, {
        "id": "notification-1", "user_id": "recipient-1", "type": "message", "text": "Hello",
    }))

    assert len(sent) == 1
    assert sent[0]["subscription_info"] == {
        "endpoint": endpoint,
        "keys": {"p256dh": p256dh, "auth": auth},
    }
    assert sent[0]["vapid_private_key"] == "test-vapid"
    assert sent[0]["vapid_claims"] == {"sub": "mailto:push@example.test"}
    payload = json.loads(sent[0]["data"])
    assert payload["title"] == web_push.PUSH_TITLES["message"]
    assert payload["body"] == "Hello"
    assert "Loaded Web Push subscriptions user=recipient-1 count=2" in caplog.text
    assert "status=201" in caplog.text
    assert "accepted" in caplog.text
    assert endpoint not in caplog.text
    assert p256dh not in caplog.text
    assert auth not in caplog.text
    assert "Skipping malformed Web Push subscription" in caplog.text


def test_push_subscribe_stores_user_endpoint_and_keys(monkeypatch):
    database = AsyncMongoMockClient()["web_push_subscribe_test"]
    asyncio.run(database.users.insert_one({"id": "recipient-1", "role": "retailer"}))
    monkeypatch.setattr(server, "db", database)
    client = TestClient(server.app)
    client.headers["Authorization"] = f"Bearer {server.create_token('recipient-1', {'role': 'retailer'})}"
    endpoint = "https://push.example.test/device-endpoint"
    payload = {
        "endpoint": endpoint,
        "expirationTime": None,
        "keys": {"p256dh": "p256dh-value", "auth": "auth-value"},
    }

    response = client.post("/api/push/subscribe", json=payload)
    stored = asyncio.run(database.push_subscriptions.find_one({"endpoint": endpoint}, {"_id": 0}))

    assert response.status_code == 200
    assert stored["user_id"] == "recipient-1"
    assert stored["endpoint"] == endpoint
    assert stored["keys"] == payload["keys"]


def test_push_subscribe_logs_sanitized_traceback_on_mongo_failure(monkeypatch, caplog):
    database = AsyncMongoMockClient()["web_push_subscribe_failure_test"]
    asyncio.run(database.users.insert_one({"id": "recipient-1", "role": "retailer"}))

    class FailingSubscriptions:
        async def update_one(self, *_args, **_kwargs):
            raise RuntimeError("write failed for https://push.example.test/private-endpoint")

    class FailingDatabase:
        users = database.users
        push_subscriptions = FailingSubscriptions()

    monkeypatch.setattr(server, "db", FailingDatabase())
    client = TestClient(server.app, raise_server_exceptions=False)
    client.headers["Authorization"] = f"Bearer {server.create_token('recipient-1', {'role': 'retailer'})}"
    caplog.set_level(logging.ERROR, logger="distro")

    response = client.post("/api/push/subscribe", json={
        "endpoint": "https://push.example.test/private-endpoint",
        "keys": {"p256dh": "private-p256dh", "auth": "private-auth"},
    })

    assert response.status_code == 500
    assert "Push subscription persistence failed" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "Traceback (most recent call last)" in caplog.text
    assert "write failed" in caplog.text
    assert "private-endpoint" not in caplog.text
    assert "private-p256dh" not in caplog.text
    assert "private-auth" not in caplog.text


def test_send_one_logs_webpush_exception_response_and_returns_expired_status(monkeypatch, caplog):
    endpoint = "https://push.example.test/expired-subscription"
    p256dh = "expired-public-key"
    auth = "expired-auth-key"
    subscription = {"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}}

    class Response:
        status_code = 410
        reason = "Gone"
        text = f"expired {endpoint} {p256dh} {auth}"

    def rejected_webpush(**_kwargs):
        raise web_push.WebPushException("provider rejected subscription", response=Response())

    monkeypatch.setattr(web_push, "webpush", rejected_webpush)
    caplog.set_level(logging.WARNING, logger="distro.push")

    status = web_push._send_one(subscription, "{}", "test-vapid")

    assert status == 410
    assert "error=WebPushException" in caplog.text
    assert "status=410" in caplog.text
    assert "Gone" in caplog.text
    assert "expired" in caplog.text
    assert endpoint not in caplog.text
    assert p256dh not in caplog.text
    assert auth not in caplog.text


def test_bad_jwt_403_removes_stale_subscription(monkeypatch, caplog):
    database = AsyncMongoMockClient()["web_push_bad_jwt_test"]
    endpoint = "https://push.example.test/bad-jwt-subscription"
    subscription = {"user_id": "recipient-1", "endpoint": endpoint,
                    "keys": {"p256dh": "public-key", "auth": "auth-key"}}

    async def seed():
        await database.push_subscriptions.insert_one(subscription)
        await database.users.insert_one({"id": "recipient-1", "role": "retailer"})

    asyncio.run(seed())

    class Response:
        status_code = 403
        reason = "Forbidden"
        text = "BadJwtToken"

    def rejected_webpush(**_kwargs):
        raise web_push.WebPushException("provider rejected JWT", response=Response())

    async def fake_get_vapid(_database):
        return "test-vapid", "test-public-key"

    monkeypatch.setattr(web_push, "webpush", rejected_webpush)
    monkeypatch.setattr(web_push, "get_vapid", fake_get_vapid)
    monkeypatch.setenv("VAPID_SUBJECT", "mailto:push@example.test")
    caplog.set_level(logging.WARNING, logger="distro.push")

    asyncio.run(web_push.deliver(database, {
        "id": "notification-bad-jwt", "user_id": "recipient-1", "type": "message", "text": "Hello",
    }))

    remaining = asyncio.run(database.push_subscriptions.count_documents({"endpoint": endpoint}))
    assert remaining == 0
    assert "BadJwtToken" in caplog.text
    assert "Removing stale Web Push subscription" in caplog.text


def test_get_vapid_validates_configured_public_key_matches_private(monkeypatch):
    signer = Vapid01()
    signer.generate_keys()
    private_pem = signer.private_pem().decode()
    public_key = web_push._public_key_b64(signer)
    monkeypatch.setattr(web_push, "_vapid_cache", None)
    monkeypatch.setenv("VAPID_PRIVATE_KEY", private_pem)
    monkeypatch.setenv("VAPID_PUBLIC_KEY", public_key)
    monkeypatch.setenv("VAPID_CLAIM_EMAIL", "push@example.test")
    monkeypatch.delenv("VAPID_SUBJECT", raising=False)

    _vapid, returned_public_key = asyncio.run(web_push.get_vapid(None))

    assert returned_public_key == public_key
    assert web_push._vapid_subject() == "mailto:push@example.test"

    monkeypatch.delenv("VAPID_SUBJECT", raising=False)
    monkeypatch.delenv("VAPID_CLAIM_EMAIL", raising=False)
    monkeypatch.setenv("APP_BASE_URL", "https://distro.example.test/")
    assert web_push._vapid_subject() == "https://distro.example.test"

    monkeypatch.setattr(web_push, "_vapid_cache", None)
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "a-different-public-key")
    with pytest.raises(RuntimeError, match="does not match"):
        asyncio.run(web_push.get_vapid(None))