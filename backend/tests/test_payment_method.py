"""Focused tests for the new payment_method feature on orders."""
import os
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL')
if not BASE_URL:
    with open('/app/frontend/.env') as f:
        for line in f:
            if line.startswith('REACT_APP_BACKEND_URL='):
                BASE_URL = line.split('=', 1)[1].strip()
BASE_URL = BASE_URL.rstrip('/')
API = f"{BASE_URL}/api"

ADMIN = ("mgv67mk2j5@privaterelay.appleid.com", "Admin@123")
SUPPLIER = ("metro@distro.com", "Password@123")
RETAILER = ("cornerstore@distro.com", "Password@123")


def _login(e, p):
    r = requests.post(f"{API}/auth/login", json={"email": e, "password": p}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def _h(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def ctx():
    return {
        "admin": _login(*ADMIN),
        "supplier": _login(*SUPPLIER),
        "retailer": _login(*RETAILER),
    }


def _place_order(retailer_token, payment_method=None):
    prods = requests.get(f"{API}/products").json()
    prod = next(p for p in prods if p["stock"] > p["moq"])
    payload = {
        "items": [{"product_id": prod["id"], "name": prod["name"], "image": prod.get("image", ""),
                   "supplier_id": prod["supplier_id"], "quantity": prod["moq"],
                   "unit_price": prod["price_per_unit"]}],
        "delivery_address": "TEST pay addr",
        "notes": "TEST payment",
        "delivery_window": "9am - 12pm",
    }
    if payment_method is not None:
        payload["payment_method"] = payment_method
    r = requests.post(f"{API}/orders", json=payload, headers=_h(retailer_token))
    assert r.status_code == 200, r.text
    return r.json()["orders"][0], prod["supplier_id"]


@pytest.mark.parametrize("method", ["cash", "card", "consignment"])
def test_payment_method_persists_on_order(ctx, method):
    order, _ = _place_order(ctx["retailer"]["token"], payment_method=method)
    assert order.get("payment_method") == method
    # Verify via retailer list
    r = requests.get(f"{API}/orders", headers=_h(ctx["retailer"]["token"]))
    assert r.status_code == 200
    found = next((o for o in r.json() if o["id"] == order["id"]), None)
    assert found is not None
    assert found["payment_method"] == method


def test_payment_method_default_cash_when_omitted(ctx):
    order, _ = _place_order(ctx["retailer"]["token"], payment_method=None)
    assert order.get("payment_method") == "cash"


def test_supplier_sees_payment_method(ctx):
    order, sid = _place_order(ctx["retailer"]["token"], payment_method="card")
    # supplier token
    sup_tok = ctx["supplier"]["token"]
    # only valid if order's supplier matches metro; else re-login as any supplier that owns it
    r = requests.get(f"{API}/orders", headers=_h(sup_tok))
    assert r.status_code == 200
    orders = r.json()
    # metro should see at least some orders with payment_method set
    assert all("payment_method" in o for o in orders)
    # If this specific order belongs to metro, verify it
    mine = [o for o in orders if o["id"] == order["id"]]
    if mine:
        assert mine[0]["payment_method"] == "card"


def test_admin_sees_payment_method_on_all_orders(ctx):
    order, _ = _place_order(ctx["retailer"]["token"], payment_method="consignment")
    r = requests.get(f"{API}/orders", headers=_h(ctx["admin"]["token"]))
    assert r.status_code == 200
    orders = r.json()
    assert len(orders) >= 1
    assert all("payment_method" in o for o in orders)
    found = next((o for o in orders if o["id"] == order["id"]), None)
    assert found is not None
    assert found["payment_method"] == "consignment"
