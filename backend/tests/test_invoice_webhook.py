import asyncio
import hashlib
import hmac
import json
import os

os.environ.setdefault("INVOICE_WEBHOOK_SECRET", "test-secret")

import pytest
from fastapi import HTTPException

import server


class FakeRequest:
    def __init__(self, body: bytes, signature: str):
        self._body = body
        self.headers = {"X-Signature": signature}

    async def body(self):
        return self._body


def signed(payload, secret="test-secret"):
    raw = json.dumps(payload).encode()
    return FakeRequest(raw, hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest())


class FakeInvoices:
    def __init__(self, inv):
        self.inv = inv

    async def find_one(self, q, p=None):
        return dict(self.inv) if q["id"] == self.inv["id"] else None

    async def update_one(self, q, u):
        class R:
            modified_count = 0
        if self.inv["status"] != "paid":
            self.inv.update(u["$set"])
            R.modified_count = 1
        return R


class FakeDB:
    def __init__(self, inv):
        self.invoices = FakeInvoices(inv)


@pytest.fixture
def inv(monkeypatch):
    invoice = {"id": "inv-1", "invoice_no": "N1", "supplier_id": "s1", "amount": 100.0,
              "currency": "GEL", "status": "pending"}
    monkeypatch.setattr(server, "db", FakeDB(invoice))

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(server, "recompute_freeze", noop)
    monkeypatch.setattr(server, "notify", noop)
    return invoice


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_payment_link_contains_invoice_id():
    assert "invoice_id=abc" in server.invoice_payment_link("abc")


def test_success_marks_paid_and_is_idempotent(inv):
    payload = {"invoice_id": "inv-1", "status": "success", "amount": 100, "currency": "GEL", "transaction_id": "txn-1"}
    r = run(server.invoice_payment_webhook(signed(payload)))
    assert r["status"] == "paid" and r["updated"] is True
    r = run(server.invoice_payment_webhook(signed(payload)))
    assert r["status"] == "paid" and r["updated"] is False


def test_bad_signature_rejected(inv):
    req = signed({"invoice_id": "inv-1", "status": "success"}, secret="wrong")
    with pytest.raises(HTTPException) as e:
        run(server.invoice_payment_webhook(req))
    assert e.value.status_code == 401 and inv["status"] == "pending"


def test_low_amount_and_failed_status(inv):
    with pytest.raises(HTTPException) as e:
        run(server.invoice_payment_webhook(signed({"invoice_id": "inv-1", "status": "success", "amount": 50, "currency": "GEL"})))
    assert e.value.status_code == 409
    r = run(server.invoice_payment_webhook(signed({"invoice_id": "inv-1", "status": "failed"})))
    assert r["updated"] is False and inv["status"] == "pending"


@pytest.mark.parametrize("payment", [
    {"invoice_id": "inv-1", "status": "success", "currency": "GEL"},
    {"invoice_id": "inv-1", "status": "success", "amount": 100},
    {"invoice_id": "inv-1", "status": "success", "amount": 100.01, "currency": "GEL"},
    {"invoice_id": "inv-1", "status": "success", "amount": 100, "currency": "USD"},
])
def test_success_requires_exact_amount_and_currency(inv, payment):
    with pytest.raises(HTTPException):
        run(server.invoice_payment_webhook(signed(payment)))
    assert inv["status"] == "pending"
