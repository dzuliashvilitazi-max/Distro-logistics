from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import server


class MemoryCollection:
    def __init__(self):
        self.rows = []

    async def find_one(self, query, projection=None):
        return next((dict(row) for row in self.rows if all(row.get(key) == value for key, value in query.items())), None)

    async def insert_one(self, document):
        self.rows.append(dict(document))
        return SimpleNamespace(inserted_id=document.get("id"))


@pytest.fixture
def auth_client(monkeypatch):
    database = SimpleNamespace(
        users=MemoryCollection(),
        terms_acceptances=MemoryCollection(),
        store_branches=MemoryCollection(),
    )
    issued_emails = []

    async def no_op(*args, **kwargs):
        return None

    async def issue_email_otp(email, name):
        issued_emails.append(email)

    monkeypatch.setattr(server, "db", database)
    monkeypatch.setattr(server, "issue_otp", issue_email_otp)
    monkeypatch.setattr(server, "_ensure_admin_contacts", no_op)
    monkeypatch.setattr(server, "is_disposable_email", lambda _email: False)
    return TestClient(server.app), database, issued_emails


def _registration_payload(email, **overrides):
    return {
        "email": email,
        "password": "valid-password-123",
        "name": "Email Verified User",
        "business_name": "Email Verified Store",
        "role": "retailer",
        "identification_number": "12345678901",
        "vat_registered": False,
        "accept_terms": True,
        **overrides,
    }


def test_legacy_phone_otp_endpoints_succeed_without_phone_or_sms(auth_client):
    client, database, _issued_emails = auth_client

    requested = client.post("/api/phone-otp")
    verified = client.post("/api/verify-otp")

    assert requested.status_code == 200
    assert requested.json()["verification_required"] is False
    assert verified.status_code == 200
    assert verified.json()["verified"] is True


def test_registration_without_phone_uses_email_verification_only(auth_client):
    client, database, issued_emails = auth_client

    response = client.post("/api/auth/register", json=_registration_payload("no-phone@example.com"))

    assert response.status_code == 200, response.text
    assert response.json() == {"verification_required": True, "email": "no-phone@example.com"}
    account = database.users.rows[0]
    assert account["phone"] == ""
    assert "phone_verified" not in account
    assert issued_emails == ["no-phone@example.com"]


def test_registration_with_optional_phone_does_not_require_phone_verification(auth_client):
    client, database, issued_emails = auth_client

    response = client.post("/api/auth/register", json=_registration_payload(
        "with-phone@example.com", phone="+995555112233",
    ))

    assert response.status_code == 200, response.text
    assert database.users.rows[0]["phone"] == "+995555112233"
    assert issued_emails == ["with-phone@example.com"]
