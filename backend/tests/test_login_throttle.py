import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

import login_throttle
import server

EMAIL = "owner@example.com"
PASSWORD = "correct-horse-battery"


class Clock:
    def __init__(self):
        self.now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def client(monkeypatch):
    database = AsyncMongoMockClient()["login_throttle_test"]
    asyncio.run(database.users.insert_one({
        "id": "u1", "email": EMAIL, "password_hash": server.hash_password(PASSWORD), "role": "retailer",
        "name": "Owner", "business_name": "Shop", "email_verified": True, "store_access_role": "global_admin",
    }))
    clock = Clock()
    monkeypatch.setattr(server, "db", database)
    monkeypatch.setattr(login_throttle, "_now", lambda: clock.now)
    for name, value in {
        "LOGIN_MAX_FAILURES_PER_EMAIL_IP": "5", "LOGIN_MAX_FAILURES_PER_EMAIL": "8", "LOGIN_MAX_FAILURES_PER_IP": "12",
        "LOGIN_FAILURE_WINDOW_SECONDS": "900", "LOGIN_BLOCK_SECONDS": "600", "LOGIN_MAX_BLOCK_SECONDS": "3600",
        "LOGIN_TRUSTED_PROXY_HOPS": "1", "LOGIN_RATE_LIMIT_ENABLED": "1",
    }.items():
        monkeypatch.setenv(name, value)
    test_client = TestClient(server.app)
    test_client.clock = clock
    test_client.db = database
    return test_client


def login(client, email=EMAIL, password=PASSWORD, ip="203.0.113.10", forwarded=None):
    return client.post("/api/auth/login", json={"email": email, "password": password},
                       headers={"x-forwarded-for": forwarded or ip})


def fail(client, times, **kwargs):
    return [login(client, password="wrong-password", **kwargs).status_code for _ in range(times)]


def test_normal_login_works(client):
    response = login(client)
    assert response.status_code == 200 and response.json()["token"]


def test_repeated_failures_trigger_temporary_block_even_for_correct_password(client):
    assert fail(client, 5) == [401] * 5
    blocked = login(client)
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) <= 601
    assert "Too many login attempts" in blocked.json()["detail"]


def test_block_expires_and_user_can_log_in_again(client):
    fail(client, 5)
    assert login(client).status_code == 429
    client.clock.advance(601)
    assert login(client).status_code == 200


def test_success_clears_email_counters(client):
    fail(client, 4)
    assert login(client).status_code == 200
    assert fail(client, 4) == [401] * 4
    assert login(client).status_code == 200


def test_failures_expire_after_window(client):
    fail(client, 4)
    client.clock.advance(901)
    assert fail(client, 4) == [401] * 4
    assert login(client).status_code == 200


def test_email_formatting_cannot_bypass_block(client):
    fail(client, 5)
    for variant in ("OWNER@EXAMPLE.COM", "Owner@Example.com"):
        assert login(client, email=variant).status_code == 429, variant
    for odd in ("  owner@example.com ", "owner@example.com\u200b", "ｏｗｎｅｒ@example.com"):
        assert login_throttle.normalize_email(odd) == EMAIL, odd


def test_changing_ip_cannot_bypass_email_limit(client):
    codes = [login(client, password="bad", ip=f"198.51.100.{n}").status_code for n in range(1, 9)]
    assert codes == [401] * 8
    assert login(client, ip="198.51.100.99").status_code == 429


def test_spoofed_forwarded_for_prefix_is_ignored(client):
    for n in range(5):
        login(client, password="bad", forwarded=f"10.0.0.{n}, 203.0.113.10")
    assert login(client, forwarded="172.16.0.1, 203.0.113.10").status_code == 429


def test_unknown_email_behaves_like_known_email(client):
    unknown = "nobody@example.com"
    first = login(client, email=unknown, password="x")
    assert first.status_code == 401 and first.json() == login(client, password="x").json()
    fail(client, 4, email=unknown)
    assert login(client, email=unknown, password="x").status_code == 429


def test_network_limit_blocks_many_accounts_from_one_ip(client):
    codes = [login(client, email=f"user{n}@example.com", password="x").status_code for n in range(13)]
    assert codes[:12] == [401] * 12 and codes[12] == 429
    assert login(client, ip="192.0.2.7").status_code == 200


def test_block_duration_escalates_but_is_capped(client):
    fail(client, 5)
    client.clock.advance(601)
    fail(client, 5)
    second = login(client)
    assert second.status_code == 429 and 600 < int(second.headers["Retry-After"]) <= 1200


def test_disabled_switch_turns_protection_off(client, monkeypatch):
    monkeypatch.setenv("LOGIN_RATE_LIMIT_ENABLED", "0")
    fail(client, 10)
    assert login(client).status_code == 200


def test_other_auth_flows_are_unaffected(client):
    fail(client, 5)
    response = client.post("/api/auth/resend-otp", json={"email": EMAIL})
    assert response.status_code != 429


def test_client_network_normalisation():
    assert login_throttle.client_network("1.2.3.4, 5.6.7.8", "9.9.9.9", 1) == "5.6.7.8"
    assert login_throttle.client_network(None, "9.9.9.9", 1) == "9.9.9.9"
    assert login_throttle.client_network("2001:db8::1", None, 1) == login_throttle.client_network("2001:db8::ffff", None, 1)
    assert login_throttle.client_network("garbage", None, 1) == "unknown"
