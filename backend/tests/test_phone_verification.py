from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import server


class MemoryCollection:
    def __init__(self, rows=None):
        self.rows = rows or []

    async def find_one(self, query, projection=None):
        for row in self.rows:
            if all(row.get(key) == value for key, value in query.items()):
                return dict(row)
        return None

    async def update_one(self, query, update, upsert=False):
        row = next((
            item for item in self.rows
            if all(item.get(key) == value for key, value in query.items())
        ), None)
        if row is None:
            if not upsert:
                return SimpleNamespace(matched_count=0, modified_count=0)
            row = {key: value for key, value in query.items() if not key.startswith("$")}
            row.update(update.get("$setOnInsert", {}))
            self.rows.append(row)
        row.update(update.get("$set", {}))
        for key, amount in update.get("$inc", {}).items():
            row[key] = row.get(key, 0) + amount
        return SimpleNamespace(matched_count=1, modified_count=1)

    async def insert_one(self, document):
        self.rows.append(dict(document))
        return SimpleNamespace(inserted_id=document.get("id"))

    async def delete_one(self, query):
        for index, row in enumerate(self.rows):
            if all(row.get(key) == value for key, value in query.items()):
                self.rows.pop(index)
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)


@pytest.fixture
def phone_client(monkeypatch):
    database = SimpleNamespace(
        phone_otps=MemoryCollection(),
        users=MemoryCollection(),
        terms_acceptances=MemoryCollection(),
        store_branches=MemoryCollection(),
    )
    sent_codes = {}

    async def fake_send_sms(phone, code):
        sent_codes[phone] = code

    async def no_op(*args, **kwargs):
        return None

    monkeypatch.setattr(server, "db", database)
    monkeypatch.setattr(server, "send_phone_sms", fake_send_sms)
    monkeypatch.setattr(server, "issue_otp", no_op)
    monkeypatch.setattr(server, "_ensure_admin_contacts", no_op)
    monkeypatch.setattr(server, "is_disposable_email", lambda _email: False)
    return TestClient(server.app), database, sent_codes


def _registration_payload(email, phone, token=None):
    return {
        "email": email,
        "password": "valid-password-123",
        "name": "Phone Verified User",
        "business_name": "Phone Verified Store",
        "role": "retailer",
        "identification_number": "12345678901",
        "vat_registered": False,
        "accept_terms": True,
        "phone": phone,
        "phone_verification_token": token,
    }


def test_phone_otp_validates_georgian_mobile_format(phone_client):
    client, _database, _sent_codes = phone_client

    response = client.post("/api/phone-otp", json={"phone": "+1 415 555 0100"})

    assert response.status_code == 422


def test_registration_requires_verified_phone_and_consumes_proof_once(phone_client):
    client, database, sent_codes = phone_client
    phone = "+995555112233"
    payload = _registration_payload("phone-user@example.com", phone)

    bypass = client.post("/api/auth/register", json=payload)
    assert bypass.status_code == 400
    assert not database.users.rows

    sent = client.post("/api/phone-otp", json={"phone": "+995 555 112233"})
    assert sent.status_code == 200
    assert sent.json()["expires_in"] == 240
    assert sent_codes[phone]

    wrong_code = f"{(int(sent_codes[phone]) + 1) % 1_000_000:06d}"
    wrong = client.post("/api/verify-otp", json={"phone": phone, "code": wrong_code})
    assert wrong.status_code == 400
    assert database.phone_otps.rows[0]["attempts"] == 1

    verified = client.post("/api/verify-otp", json={"phone": phone, "code": sent_codes[phone]})
    assert verified.status_code == 200
    payload["phone_verification_token"] = verified.json()["verification_token"]
    registered = client.post("/api/auth/register", json=payload)
    assert registered.status_code == 200

    account = database.users.rows[0]
    assert account["phone"] == phone
    assert account["phone_verified"] is True
    assert account["otp_code_hash"] is None
    assert database.phone_otps.rows[0]["otp_code_hash"] is None

    replay = client.post("/api/auth/register", json=_registration_payload(
        "another-user@example.com", phone, verified.json()["verification_token"],
    ))
    assert replay.status_code == 400
    assert len(database.users.rows) == 1


def test_phone_otp_expires_after_four_minutes(phone_client):
    client, database, sent_codes = phone_client
    phone = "+995599998888"
    assert client.post("/api/phone-otp", json={"phone": phone}).status_code == 200

    database.phone_otps.rows[0]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    expired = client.post("/api/verify-otp", json={"phone": phone, "code": sent_codes[phone]})
    assert expired.status_code == 400

def test_phone_otp_locks_after_five_wrong_attempts(phone_client):
    client, database, sent_codes = phone_client
    phone = "+995599998889"
    assert client.post("/api/phone-otp", json={"phone": phone}).status_code == 200
    wrong_code = f"{(int(sent_codes[phone]) + 1) % 1_000_000:06d}"

    for _ in range(server.PHONE_OTP_MAX_ATTEMPTS):
        response = client.post("/api/verify-otp", json={"phone": phone, "code": wrong_code})
        assert response.status_code == 400
    locked = client.post("/api/verify-otp", json={"phone": phone, "code": sent_codes[phone]})
    assert locked.status_code == 429
    assert database.phone_otps.rows[0]["attempts"] == server.PHONE_OTP_MAX_ATTEMPTS
    assert client.post("/api/phone-otp", json={"phone": phone}).status_code == 429


def test_verified_challenge_lives_for_registration_token_window(phone_client):
    client, database, sent_codes = phone_client
    phone = "+995599998887"
    assert client.post("/api/phone-otp", json={"phone": phone}).status_code == 200
    verified = client.post("/api/verify-otp", json={"phone": phone, "code": sent_codes[phone]})

    assert verified.status_code == 200
    assert database.phone_otps.rows[0]["expires_at"] > datetime.now(timezone.utc)