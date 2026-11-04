import os
from contextvars import ContextVar
from typing import Any
from urllib.parse import quote

import httpx


class TBCGatewayError(Exception):
    pass


# Admin-configured credentials for the current request; fall back to environment variables.
credentials_override: ContextVar[dict | None] = ContextVar("tbc_credentials_override", default=None)


def _configuration() -> tuple[str, str, str, str]:
    override = credentials_override.get() or {}
    client_id = (override.get("client_id") or os.environ.get("TBC_CLIENT_ID", "")).strip()
    client_secret = (override.get("client_secret") or os.environ.get("TBC_CLIENT_SECRET", "")).strip()
    api_key = (override.get("api_key") or os.environ.get("TBC_API_KEY", "")).strip()
    if not client_id or not client_secret or not api_key:
        raise TBCGatewayError("TBC E-Commerce credentials are not configured.")
    base_url = os.environ.get("TBC_API_BASE_URL", "https://api.tbcbank.ge/v1").strip().rstrip("/")
    return base_url, client_id, client_secret, api_key


def callback_url() -> str:
    configured_url = os.environ.get("TBC_CALLBACK_URL", "").strip()
    if configured_url:
        return configured_url
    app_url = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")
    if not app_url:
        raise TBCGatewayError("Set TBC_CALLBACK_URL or APP_BASE_URL for bank callbacks.")
    return f"{app_url}/api/payments/tbc/callback"


def validate_configuration() -> None:
    _configuration()
    callback_url()


async def _access_token(client: httpx.AsyncClient, base_url: str, client_id: str,
                        client_secret: str, api_key: str) -> str:
    response = await client.post(
        f"{base_url}/tpay/access-token",
        headers={"apikey": api_key, "Content-Type": "application/x-www-form-urlencoded"},
        data={"client_id": client_id, "client_secret": client_secret},
    )
    response.raise_for_status()
    try:
        token = response.json().get("access_token")
    except (ValueError, AttributeError) as error:
        raise TBCGatewayError("TBC returned an invalid access-token response.") from error
    if not token:
        raise TBCGatewayError("TBC did not return an access token.")
    return token


async def _request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    base_url, client_id, client_secret, api_key = _configuration()
    async with httpx.AsyncClient(timeout=20) as client:
        token = await _access_token(client, base_url, client_id, client_secret, api_key)
        response = await client.request(
            method, f"{base_url}{path}",
            headers={"apikey": api_key, "Authorization": f"Bearer {token}"},
            json=payload,
        )
        response.raise_for_status()
        try:
            data = response.json()
        except ValueError as error:
            raise TBCGatewayError("TBC returned an invalid response.") from error
        if not isinstance(data, dict):
            raise TBCGatewayError("TBC returned an invalid response.")
        return data


async def create_payment(payment_id: str, amount: float, return_url: str, user_ip: str) -> tuple[str, dict[str, Any]]:
    callback = callback_url()
    description = f"Distro Logistics {payment_id[:12]}"
    response = await _request("POST", "/tpay/payments", {
        "amount": {"currency": "GEL", "total": round(amount, 2)},
        "returnurl": return_url,
        "callbackUrl": callback,
        "preAuth": False,
        "language": "KA",
        "merchantPaymentId": payment_id,
        "userIpAddress": user_ip,
        "expirationMinutes": 12,
        "methods": [5],
        "description": description[:30],
    })
    links = response.get("links") or []
    approval_url = next(
        (link.get("uri") for link in links if isinstance(link, dict) and link.get("rel") == "approval_url"),
        None,
    )
    pay_id = response.get("payId")
    if not pay_id or not approval_url:
        raise TBCGatewayError("TBC did not return a checkout URL.")
    return str(pay_id), response


async def get_payment(pay_id: str) -> dict[str, Any]:
    return await _request("GET", f"/tpay/payments/{quote(pay_id, safe='')}")
