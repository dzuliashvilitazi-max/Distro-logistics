import asyncio

import pytest

import tbc_gateway


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def post(self, url, **kwargs):
        self.requests.append(("POST", url, kwargs))
        return FakeResponse({"access_token": "test-access-token"})

    async def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        if method == "POST":
            return FakeResponse({
                "payId": "test-pay-id",
                "status": "Created",
                "links": [{"rel": "approval_url", "uri": "https://tpay.example/checkout"}],
            })
        return FakeResponse({"payId": "test-pay-id", "status": "Succeeded"})


def _configure(monkeypatch):
    monkeypatch.setenv("TBC_CLIENT_ID", "merchant-id")
    monkeypatch.setenv("TBC_CLIENT_SECRET", "merchant-secret")
    monkeypatch.setenv("TBC_API_KEY", "developer-key")
    monkeypatch.setenv("TBC_API_BASE_URL", "https://bank.example/v1")
    monkeypatch.setenv("TBC_CALLBACK_URL", "https://shop.example/api/payments/tbc/callback")
    FakeClient.requests = []
    monkeypatch.setattr(tbc_gateway.httpx, "AsyncClient", lambda **kwargs: FakeClient())


def test_create_payment_uses_bank_hosted_card_checkout(monkeypatch):
    _configure(monkeypatch)
    pay_id, response = asyncio.run(tbc_gateway.create_payment(
        "merchant-payment-id", 12.5, "https://shop.example/orders?payment_id=merchant-payment-id", "127.0.0.1"
    ))

    assert pay_id == "test-pay-id"
    assert response["status"] == "Created"
    token_request, payment_request = FakeClient.requests
    assert token_request[1] == "https://bank.example/v1/tpay/access-token"
    assert token_request[2]["data"] == {
        "client_id": "merchant-id", "client_secret": "merchant-secret",
    }
    assert payment_request[1] == "https://bank.example/v1/tpay/payments"
    assert payment_request[2]["headers"]["Authorization"] == "Bearer test-access-token"
    assert payment_request[2]["json"]["amount"] == {"currency": "GEL", "total": 12.5}
    assert payment_request[2]["json"]["methods"] == [5]
    assert payment_request[2]["json"]["callbackUrl"] == "https://shop.example/api/payments/tbc/callback"


def test_get_payment_quotes_payment_id(monkeypatch):
    _configure(monkeypatch)
    result = asyncio.run(tbc_gateway.get_payment("pay/id"))
    assert result["status"] == "Succeeded"
    assert FakeClient.requests[-1][1] == "https://bank.example/v1/tpay/payments/pay%2Fid"


def test_missing_credentials_are_reported(monkeypatch):
    monkeypatch.delenv("TBC_CLIENT_ID", raising=False)
    monkeypatch.delenv("TBC_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("TBC_API_KEY", raising=False)
    with pytest.raises(tbc_gateway.TBCGatewayError):
        tbc_gateway.validate_configuration()
