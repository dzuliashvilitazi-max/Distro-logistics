import asyncio
import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from mongomock_motor import AsyncMongoMockClient

import server


SECRET = "bank-webhook-test-secret"


class FakeRequest:
    def __init__(self, payload, secret=SECRET):
        self._body = json.dumps(payload).encode("utf-8")
        self.headers = {"X-Signature": hmac.new(secret.encode(), self._body, hashlib.sha256).hexdigest()}
        self.client = SimpleNamespace(host="127.0.0.1")

    async def body(self):
        return self._body


@pytest.fixture
def bank_invoice_db(monkeypatch):
    monkeypatch.setenv("BANK_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("APP_ENV", "test")
    database = AsyncMongoMockClient()["bank_invoice_webhook_test"]

    async def seed():
        await database.invoices.create_index("payment_reference_normalized", unique=True, sparse=True)
        await database.invoice_bank_transactions.create_index("transaction_id", unique=True)
        await database.invoices.insert_many([
            {"id": "inv-1", "invoice_no": "INV-1", "supplier_id": "supplier-1",
             "amount": 100.0, "currency": "GEL", "status": "pending",
             "payment_reference": "REF-INV-1", "payment_reference_normalized": "ref-inv-1"},
            {"id": "inv-2", "invoice_no": "INV-2", "supplier_id": "supplier-1",
             "amount": 45.0, "currency": "GEL", "status": "pending",
             "payment_reference": "REF-INV-2", "payment_reference_normalized": "ref-inv-2"},
        ])

    asyncio.run(seed())
    monkeypatch.setattr(server, "db", database)

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(server, "recompute_freeze", noop)
    monkeypatch.setattr(server, "notify", noop)
    return database


def run(coro):
    return asyncio.run(coro)


def payment(transaction_id="txn-1", reference="REF-INV-1", amount=100, currency="GEL"):
    return {"transaction_id": transaction_id, "reference": reference, "amount": amount,
            "currency": currency, "status": "completed"}


def test_bank_invoice_webhook_settles_and_deduplicates(bank_invoice_db):
    database = bank_invoice_db
    result = run(server.bank_invoice_payment_webhook(FakeRequest(payment(reference="ref-inv-1"))))
    invoice = run(database.invoices.find_one({"id": "inv-1"}))
    event = run(database.invoice_bank_transactions.find_one({"transaction_id": "txn-1"}))

    assert result["updated"] is True and result["status"] == "paid"
    assert invoice["status"] == "paid"
    assert invoice["bank_transaction_id"] == "txn-1"
    assert invoice["paid_amount"] == 100
    assert invoice["paid_currency"] == "GEL"
    assert invoice["payment_reference"] == "REF-INV-1"
    assert event["state"] == "applied"

    repeated = run(server.bank_invoice_payment_webhook(FakeRequest(payment(reference="ref-inv-1"))))
    assert repeated["duplicate"] is True and repeated["updated"] is False
    assert run(database.invoice_bank_transactions.count_documents({"transaction_id": "txn-1"})) == 1


@pytest.mark.parametrize("payload", [
    payment(amount=99.99),
    payment(currency="USD"),
])
def test_amount_or_currency_mismatch_is_rejected_without_claiming_transaction(bank_invoice_db, payload):
    with pytest.raises(HTTPException) as error:
        run(server.bank_invoice_payment_webhook(FakeRequest(payload)))
    assert error.value.status_code == 409
    assert run(bank_invoice_db.invoice_bank_transactions.count_documents({})) == 0
    invoice = run(bank_invoice_db.invoices.find_one({"id": "inv-1"}))
    assert invoice["status"] == "pending"


def test_transaction_id_cannot_be_reused_for_another_invoice(bank_invoice_db):
    run(server.bank_invoice_payment_webhook(FakeRequest(payment())))
    conflicting = payment(reference="REF-INV-2", amount=45)
    with pytest.raises(HTTPException) as error:
        run(server.bank_invoice_payment_webhook(FakeRequest(conflicting)))
    assert error.value.status_code == 409
    assert run(bank_invoice_db.invoices.find_one({"id": "inv-2"}))["status"] == "pending"


def test_bad_signature_is_rejected(bank_invoice_db):
    with pytest.raises(HTTPException) as error:
        run(server.bank_invoice_payment_webhook(FakeRequest(payment(), secret="wrong-secret")))
    assert error.value.status_code == 401