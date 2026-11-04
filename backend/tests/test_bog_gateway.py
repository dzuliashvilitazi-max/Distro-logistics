import asyncio
import base64

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

import bog_gateway


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
                "id": "bog-order-id",
                "_links": {"redirect": {"href": "https://payment.bog.ge/?order_id=bog-order-id"}},
            })
        return FakeResponse({"order_id": "bog-order-id"})


def _configure(monkeypatch):
    monkeypatch.setenv("BOG_CLIENT_ID", "merchant-id")
    monkeypatch.setenv("BOG_CLIENT_SECRET", "merchant-secret")
    monkeypatch.setenv("BOG_API_BASE_URL", "https://bank.example")
    monkeypatch.setenv("APP_BASE_URL", "https://shop.example")
    FakeClient.requests = []
    monkeypatch.setattr(bog_gateway.httpx, "AsyncClient", lambda **kwargs: FakeClient())


def test_create_order_uses_hosted_checkout(monkeypatch):
    _configure(monkeypatch)
    order_id, response = asyncio.run(bog_gateway.create_order(
        "merchant-payment-id",
        24.5,
        "https://shop.example/orders?payment_id=merchant-payment-id",
        "https://shop.example/api/payments/bog/callback",
        [{"product_id": "product-1", "name": "Georgian product", "quantity": 2, "unit_price": 12.25}],
    ))

    assert order_id == "bog-order-id"
    assert response["_links"]["redirect"]["href"].startswith("https://payment.bog.ge/")
    token_request, order_request = FakeClient.requests
    assert token_request[1] == "https://oauth2.bog.ge/auth/realms/bog/protocol/openid-connect/token"
    assert token_request[2]["data"] == {"grant_type": "client_credentials"}
    assert order_request[1] == "https://bank.example/payments/v1/ecommerce/orders"
    assert order_request[2]["json"]["external_order_id"] == "merchant-payment-id"
    assert order_request[2]["json"]["purchase_units"] == {
        "currency": "GEL",
        "total_amount": 24.5,
        "basket": [{
            "product_id": "product-1", "description": "Georgian product",
            "quantity": 2, "unit_price": 12.25,
        }],
    }
    assert order_request[2]["json"]["callback_url"] == "https://shop.example/api/payments/bog/callback"
    assert order_request[2]["headers"]["Idempotency-Key"]


def test_get_order_quotes_order_id(monkeypatch):
    _configure(monkeypatch)
    result = asyncio.run(bog_gateway.get_order("order/id"))
    assert result["order_id"] == "bog-order-id"
    assert FakeClient.requests[-1][1] == "https://bank.example/payments/v1/receipt/order%2Fid"


def test_callback_url_requires_https(monkeypatch):
    monkeypatch.setenv("BOG_CALLBACK_URL", "http://shop.example/callback")
    with pytest.raises(bog_gateway.BOGGatewayError, match="HTTPS"):
        bog_gateway.callback_url()


def test_missing_credentials_are_reported(monkeypatch):
    monkeypatch.delenv("BOG_CLIENT_ID", raising=False)
    monkeypatch.delenv("BOG_CLIENT_SECRET", raising=False)
    with pytest.raises(bog_gateway.BOGGatewayError):
        bog_gateway.validate_configuration()


def test_callback_signature_verifies_raw_request_body(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    monkeypatch.setenv("BOG_CALLBACK_PUBLIC_KEY", public_key)
    body = b'{"event":"order_payment","body":{"order_id":"bog-order-id"}}'
    signature = private_key.sign(body, padding.PKCS1v15(), hashes.SHA256())

    assert bog_gateway.verify_callback_signature(body, base64.b64encode(signature).decode("ascii"))
    assert not bog_gateway.verify_callback_signature(
        body + b" ", base64.b64encode(signature).decode("ascii")
    )
