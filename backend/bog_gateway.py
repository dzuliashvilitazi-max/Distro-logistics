import base64
import os
from contextvars import ContextVar
from typing import Any
from urllib.parse import quote, urlparse
from uuid import uuid4

import httpx


class BOGGatewayError(Exception):
    pass


BOG_CALLBACK_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAu4RUyAw3+CdkS3ZNILQh
zHI9Hemo+vKB9U2BSabppkKjzjjkf+0Sm76hSMiu/HFtYhqWOESryoCDJoqffY0Q
1VNt25aTxbj068QNUtnxQ7KQVLA+pG0smf+EBWlS1vBEAFbIas9d8c9b9sSEkTrr
TYQ90WIM8bGB6S/KLVoT1a7SnzabjoLc5Qf/SLDG5fu8dH8zckyeYKdRKSBJKvhx
tcBuHV4f7qsynQT+f2UYbESX/TLHwT5qFWZDHZ0YUOUIvb8n7JujVSGZO9/+ll/g
4ZIWhC1MlJgPObDwRkRd8NFOopgxMcMsDIZIoLbWKhHVq67hdbwpAq9K9WMmEhPn
PwIDAQAB
-----END PUBLIC KEY-----"""


# Admin-configured credentials for the current request; fall back to environment variables.
credentials_override: ContextVar[dict | None] = ContextVar("bog_credentials_override", default=None)


def _configuration() -> tuple[str, str, str, str]:
    override = credentials_override.get() or {}
    client_id = (override.get("client_id") or os.environ.get("BOG_CLIENT_ID", "")).strip()
    client_secret = (override.get("client_secret") or os.environ.get("BOG_CLIENT_SECRET", "")).strip()
    if not client_id or not client_secret:
        raise BOGGatewayError("BOG E-Commerce credentials are not configured.")
    base_url = os.environ.get("BOG_API_BASE_URL", "https://api.bog.ge").strip().rstrip("/")
    oauth_url = os.environ.get(
        "BOG_OAUTH_URL",
        "https://oauth2.bog.ge/auth/realms/bog/protocol/openid-connect/token",
    ).strip()
    if urlparse(base_url).scheme != "https" or urlparse(oauth_url).scheme != "https":
        raise BOGGatewayError("BOG API and OAuth URLs must use HTTPS.")
    return base_url, oauth_url, client_id, client_secret


def callback_url() -> str:
    configured_url = os.environ.get("BOG_CALLBACK_URL", "").strip()
    if configured_url:
        result = configured_url
    else:
        app_url = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")
        if not app_url:
            raise BOGGatewayError("Set BOG_CALLBACK_URL or APP_BASE_URL for bank callbacks.")
        result = f"{app_url}/api/payments/bog/callback"
    parsed = urlparse(result)
    if parsed.scheme != "https" or not parsed.netloc:
        raise BOGGatewayError("BOG callback URL must use HTTPS.")
    return result


def validate_configuration() -> None:
    _configuration()
    callback_url()


async def _access_token(client: httpx.AsyncClient, oauth_url: str,
                        client_id: str, client_secret: str) -> str:
    response = await client.post(
        oauth_url,
        auth=(client_id, client_secret),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "client_credentials"},
    )
    response.raise_for_status()
    try:
        token = response.json().get("access_token")
    except (ValueError, AttributeError) as error:
        raise BOGGatewayError("BOG returned an invalid access-token response.") from error
    if not token:
        raise BOGGatewayError("BOG did not return an access token.")
    return token


async def _request(method: str, path: str, payload: dict[str, Any] | None = None,
                   idempotency_key: str | None = None) -> dict[str, Any]:
    base_url, oauth_url, client_id, client_secret = _configuration()
    async with httpx.AsyncClient(timeout=20) as client:
        token = await _access_token(client, oauth_url, client_id, client_secret)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept-Language": "ka",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        response = await client.request(method, f"{base_url}{path}", headers=headers, json=payload)
        response.raise_for_status()
        try:
            data = response.json()
        except ValueError as error:
            raise BOGGatewayError("BOG returned an invalid response.") from error
        if not isinstance(data, dict):
            raise BOGGatewayError("BOG returned an invalid response.")
        return data


async def create_order(payment_id: str, amount: float, return_url: str,
                       callback: str, items: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    basket = [{
        "product_id": str(item["product_id"]),
        "description": str(item["name"])[:100],
        "quantity": item["quantity"],
        "unit_price": round(float(item["unit_price"]), 2),
    } for item in items]
    response = await _request("POST", "/payments/v1/ecommerce/orders", {
        "callback_url": callback,
        "external_order_id": payment_id,
        "application_type": "web",
        "purchase_units": {
            "currency": "GEL",
            "total_amount": round(amount, 2),
            "basket": basket,
        },
        "redirect_urls": {"success": return_url, "fail": return_url},
    }, idempotency_key=str(uuid4()))
    order_id = response.get("id")
    redirect_url = (response.get("_links") or {}).get("redirect", {}).get("href")
    if not order_id or not redirect_url:
        raise BOGGatewayError("BOG did not return a checkout URL.")
    return str(order_id), response


async def get_order(order_id: str) -> dict[str, Any]:
    return await _request("GET", f"/payments/v1/receipt/{quote(order_id, safe='')}")


def verify_callback_signature(raw_body: bytes, signature: str) -> bool:
    public_key_pem = os.environ.get("BOG_CALLBACK_PUBLIC_KEY", BOG_CALLBACK_PUBLIC_KEY).strip()
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
    except ImportError as error:
        raise BOGGatewayError("Install the cryptography package to verify BOG callbacks.") from error
    try:
        public_key = load_pem_public_key(public_key_pem.encode("ascii"))
        public_key.verify(
            base64.b64decode(signature, validate=True),
            raw_body,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return True
    except InvalidSignature:
        return False
    except Exception as error:
        raise BOGGatewayError("Could not validate BOG callback signature.") from error
