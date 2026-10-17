"""Tests for sandbox payment gateway, online checkout split, smart invoicing and auto-debit."""
import os
import pytest
import requests

BASE_URL = (os.environ.get('REACT_APP_BACKEND_URL') or '').rstrip('/')
if not BASE_URL:
    with open('/app/frontend/.env') as f:
        for line in f:
            if line.startswith('REACT_APP_BACKEND_URL='):
                BASE_URL = line.split('=', 1)[1].strip().rstrip('/')
API = f"{BASE_URL}/api"

WEBHOOK_CRON_SECRET = ""
with open('/app/backend/.env') as f:
    for line in f:
        if line.startswith('WEBHOOK_CRON_SECRET='):
            WEBHOOK_CRON_SECRET = line.split('=', 1)[1].strip().strip('"').strip("'")

ADMIN = ("mgv67mk2j5@privaterelay.appleid.com", "Admin@123")
RETAILER = ("cornerstore@distro.com", "Password@123")
RETAILER2 = ("freshmart@distro.com", "Password@123")
SUPPLIER_METRO = ("metro@distro.com", "Password@123")
SUPPLIER_SNACK = ("snacknation@distro.com", "Password@123")

VALID_CARD = {"number": "4242424242424242", "exp": "11/30", "cvc": "123", "name": "Test User"}
DECLINE_ADD = {"number": "4000000000000002", "exp": "11/30", "cvc": "123"}
BAD_LUHN = {"number": "4242424242424241", "exp": "11/30", "cvc": "123"}


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
        "retailer": _login(*RETAILER),
        "retailer2": _login(*RETAILER2),
        "metro": _login(*SUPPLIER_METRO),
        "snack": _login(*SUPPLIER_SNACK),
    }


# ---------- Card CRUD / validation ----------

class TestCardCRUD:
    def test_invalid_luhn_returns_400(self, ctx):
        r = requests.post(f"{API}/payments/cards", json=BAD_LUHN, headers=_h(ctx["retailer2"]["token"]))
        assert r.status_code == 400, r.text

    def test_decline_on_add_returns_402(self, ctx):
        r = requests.post(f"{API}/payments/cards", json=DECLINE_ADD, headers=_h(ctx["retailer2"]["token"]))
        assert r.status_code == 402, r.text

    def test_add_valid_card_returns_card_metadata(self, ctx):
        r = requests.post(f"{API}/payments/cards", json=VALID_CARD, headers=_h(ctx["retailer2"]["token"]))
        assert r.status_code == 200, r.text
        card = r.json()["card"]
        assert card["brand"] == "visa"
        assert card["last4"] == "4242"
        assert card["exp"] == "11/30"
        assert card["verified"] is True
        # No raw PAN/CVC
        assert "number" not in card and "cvc" not in card and "card_token" not in card

    def test_get_card_returns_only_current_user_card(self, ctx):
        r = requests.get(f"{API}/payments/cards", headers=_h(ctx["retailer2"]["token"]))
        assert r.status_code == 200
        card = r.json()["card"]
        assert card and card["last4"] == "4242" and card["verified"] is True

    def test_delete_card_clears_it(self, ctx):
        r = requests.delete(f"{API}/payments/cards", headers=_h(ctx["retailer2"]["token"]))
        assert r.status_code == 200
        g = requests.get(f"{API}/payments/cards", headers=_h(ctx["retailer2"]["token"]))
        assert g.status_code == 200
        assert g.json()["card"] is None

    def test_expired_card_rejected(self, ctx):
        r = requests.post(f"{API}/payments/cards",
                          json={"number": "4242424242424242", "exp": "01/20", "cvc": "123"},
                          headers=_h(ctx["retailer2"]["token"]))
        assert r.status_code == 400

    def test_bad_cvc_rejected(self, ctx):
        r = requests.post(f"{API}/payments/cards",
                          json={"number": "4242424242424242", "exp": "11/30", "cvc": "1"},
                          headers=_h(ctx["retailer2"]["token"]))
        assert r.status_code == 400


# ---------- Online checkout + split ----------

def _get_metro_product():
    prods = requests.get(f"{API}/products").json()
    metro_id = None
    users = requests.get(f"{API}/products").json()
    for p in prods:
        if "metro" in (p.get("supplier_name") or "").lower() and p["stock"] > p["moq"]:
            return p
    # fallback: any product
    return next(p for p in prods if p["stock"] > p["moq"])


def _place_order(retailer_token, product, payment_method="cash"):
    payload = {
        "items": [{"product_id": product["id"], "name": product["name"], "image": product.get("image", ""),
                   "supplier_id": product["supplier_id"], "quantity": product["moq"],
                   "unit_price": product["price_per_unit"]}],
        "delivery_address": "TEST online checkout",
        "notes": "TEST",
        "delivery_window": "9am - 12pm",
        "payment_method": payment_method,
    }
    return requests.post(f"{API}/orders", json=payload, headers=_h(retailer_token))


class TestOnlineCheckout:
    def test_online_without_verified_card_returns_400(self, ctx):
        # Ensure retailer2 has no card
        requests.delete(f"{API}/payments/cards", headers=_h(ctx["retailer2"]["token"]))
        prod = _get_metro_product()
        r = _place_order(ctx["retailer2"]["token"], prod, payment_method="online")
        assert r.status_code == 400, r.text

    def test_online_checkout_success_splits_and_creates_payout(self, ctx):
        # cornerstore has seeded verified card
        prod = _get_metro_product()
        total_expected = round(prod["price_per_unit"] * prod["moq"], 2)
        r = _place_order(ctx["retailer"]["token"], prod, payment_method="online")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["paid"] is True
        assert abs(data["charged"] - total_expected) < 0.01
        order = data["orders"][0]
        assert order["paid_at_checkout"] is True
        assert "commission_amount" in order and order["commission_amount"] > 0
        assert "supplier_payout" in order
        assert abs(order["supplier_payout"] - (order["total"] - order["commission_amount"])) < 0.01
        # Payouts ledger (supplier view)
        sup_prod_supplier_id = order["supplier_id"]
        # Login as that supplier to see ledger
        sup_token = ctx["metro"]["token"] if sup_prod_supplier_id == ctx["metro"]["user"]["id"] else None
        if sup_token:
            p = requests.get(f"{API}/payments/payouts", headers=_h(sup_token))
            assert p.status_code == 200
            payouts = p.json()
            found = next((x for x in payouts if x.get("order_id") == order["id"]), None)
            assert found is not None
            assert abs(found["order_total"] - order["total"]) < 0.01
            assert abs(found["commission"] - order["commission_amount"]) < 0.01
            assert abs(found["supplier_payout"] - order["supplier_payout"]) < 0.01

    def test_retailer_cannot_see_payouts(self, ctx):
        r = requests.get(f"{API}/payments/payouts", headers=_h(ctx["retailer"]["token"]))
        assert r.status_code == 403

    def test_frozen_supplier_rejects_order(self, ctx):
        # snacknation is seeded frozen; placing order with it (any method) should 403.
        # NOTE: if a previous auto-debit test paid off snack's invoice, snack becomes unfrozen -
        # in that case we re-freeze directly via mongo to validate the enforcement path.
        fin = requests.get(f"{API}/admin/financials", headers=_h(ctx["admin"]["token"])).json()
        snack = next((s for s in fin["suppliers"] if "snack" in s["supplier_name"].lower()), None)
        if not snack or not snack.get("frozen"):
            # Force-freeze via mongo for test determinism
            try:
                import motor.motor_asyncio, asyncio, os as _os
                async def _freeze():
                    cli = motor.motor_asyncio.AsyncIOMotorClient(_os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
                    await cli[_os.environ.get("DB_NAME", "test_database")].users.update_one(
                        {"email": "snacknation@distro.com"}, {"$set": {"billing_frozen": True}})
                    cli.close()
                asyncio.run(_freeze())
            except Exception as e:
                pytest.skip(f"Cannot force-freeze snack: {e}")
        prods = requests.get(f"{API}/products").json()
        snack_prod = next((p for p in prods if "snack" in (p.get("supplier_name") or "").lower() and p["stock"] > p["moq"]), None)
        if not snack_prod:
            pytest.skip("No snacknation product available")
        r = _place_order(ctx["retailer"]["token"], snack_prod, payment_method="online")
        assert r.status_code == 403, r.text
        # Also cash path
        r2 = _place_order(ctx["retailer"]["token"], snack_prod, payment_method="cash")
        assert r2.status_code == 403


# ---------- Admin financials excludes paid_at_checkout from accrued ----------

class TestFinancialsExcludesCheckout:
    def test_checkout_collected_appears_and_not_in_accrued(self, ctx):
        # Place one more online order
        prod = _get_metro_product()
        before = requests.get(f"{API}/admin/financials", headers=_h(ctx["admin"]["token"]))
        assert before.status_code == 200
        before_data = before.json()["suppliers"]
        metro_before = next((s for s in before_data if "metro" in s["supplier_name"].lower()), None)
        assert metro_before is not None
        acc_before = metro_before["accrued_commission"]
        chk_before = metro_before.get("checkout_collected", 0)

        r = _place_order(ctx["retailer"]["token"], prod, payment_method="online")
        assert r.status_code == 200
        fee = r.json()["orders"][0]["commission_amount"]

        after = requests.get(f"{API}/admin/financials", headers=_h(ctx["admin"]["token"]))
        metro_after = next(s for s in after.json()["suppliers"] if "metro" in s["supplier_name"].lower())
        # Accrued should NOT have grown by the online fee
        assert abs(metro_after["accrued_commission"] - acc_before) < 0.01, \
            f"accrued grew after online checkout: {acc_before} -> {metro_after['accrued_commission']}"
        # Checkout collected should include this fee
        assert metro_after["checkout_collected"] >= chk_before + fee - 0.01


# ---------- Authorization ----------

class TestAuthorization:
    def test_non_admin_auto_debit_run_403(self, ctx):
        r = requests.post(f"{API}/admin/auto-debit/run", headers=_h(ctx["retailer"]["token"]))
        assert r.status_code == 403

    def test_cron_auto_debit_without_secret_401(self):
        r = requests.post(f"{API}/cron/auto-debit")
        assert r.status_code == 401

    def test_cron_auto_debit_with_secret_accepted(self):
        r = requests.post(f"{API}/cron/auto-debit",
                          headers={"Authorization": f"Bearer {WEBHOOK_CRON_SECRET}"})
        assert r.status_code == 200
        assert r.json().get("accepted") is True

    def test_cron_auto_debit_bad_secret_401(self):
        r = requests.post(f"{API}/cron/auto-debit",
                          headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 401


# ---------- Admin auto-debit run end-to-end (SnackNation seeded overdue+card) ----------

class TestAutoDebit:
    def test_admin_run_auto_debit_pays_snacknation(self, ctx):
        # Confirm snack has overdue invoice & frozen before
        inv_before = requests.get(f"{API}/invoices", headers=_h(ctx["admin"]["token"]))
        assert inv_before.status_code == 200
        snack_invs_before = [i for i in inv_before.json() if "snack" in i["supplier_name"].lower()
                              and i["effective_status"] != "paid"]

        r = requests.post(f"{API}/admin/auto-debit/run", headers=_h(ctx["admin"]["token"]))
        assert r.status_code == 200, r.text
        data = r.json()
        assert "charged" in data and "count" in data

        # Verify snacknation unfrozen & invoices paid
        fin = requests.get(f"{API}/admin/financials", headers=_h(ctx["admin"]["token"]))
        assert fin.status_code == 200
        snack = next((s for s in fin.json()["suppliers"] if "snack" in s["supplier_name"].lower()), None)
        if snack and snack_invs_before:
            # outstanding should drop to 0 (or at least decrease)
            assert snack["outstanding"] == 0 or snack["outstanding"] < sum(i["amount"] for i in snack_invs_before)
