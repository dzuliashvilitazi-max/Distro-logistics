"""Backend API tests for Distro Logistics."""
import os
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'http://localhost:8000').rstrip('/')
# Load from frontend/.env fallback
if 'REACT_APP_BACKEND_URL' not in os.environ:
    try:
        with open('/app/frontend/.env') as f:
            for line in f:
                if line.startswith('REACT_APP_BACKEND_URL='):
                    BASE_URL = line.split('=', 1)[1].strip().rstrip('/')
    except Exception:
        pass

API = f"{BASE_URL}/api"

ADMIN = ("mgv67mk2j5@privaterelay.appleid.com", "Admin@123")
SUPPLIER = ("metro@distro.com", "Password@123")
SUPPLIER2 = ("apex@distro.com", "Password@123")
RETAILER = ("cornerstore@distro.com", "Password@123")
RETAILER2 = ("freshmart@distro.com", "Password@123")
PENDING_SUPPLIER = ("newdist@distro.com", "Password@123")


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed {email}: {r.status_code} {r.text}"
    return r.json()


def _h(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def tokens():
    return {
        "admin": _login(*ADMIN),
        "supplier": _login(*SUPPLIER),
        "supplier2": _login(*SUPPLIER2),
        "retailer": _login(*RETAILER),
        "retailer2": _login(*RETAILER2),
    }


# ---------- Auth ----------
class TestAuth:
    def test_login_admin(self):
        d = _login(*ADMIN)
        assert "token" in d and d["user"]["role"] == "admin"

    def test_login_supplier(self):
        d = _login(*SUPPLIER)
        assert d["user"]["role"] == "supplier"

    def test_login_retailer(self):
        d = _login(*RETAILER)
        assert d["user"]["role"] == "retailer"

    def test_login_invalid(self):
        r = requests.post(f"{API}/auth/login", json={"email": "nope@x.com", "password": "bad"})
        assert r.status_code == 401

    def test_me(self, tokens):
        r = requests.get(f"{API}/auth/me", headers=_h(tokens["retailer"]["token"]))
        assert r.status_code == 200
        assert r.json()["email"] == RETAILER[0]

    def test_me_no_token(self):
        r = requests.get(f"{API}/auth/me")
        assert r.status_code == 401

    def test_register_retailer_and_supplier(self):
        import uuid as _uuid
        suffix = _uuid.uuid4().hex[:8]
        r_email = f"TEST_ret_{suffix}@distro.com"
        r = requests.post(f"{API}/auth/register", json={
            "email": r_email, "password": "Password@123", "name": "T Ret", "role": "retailer",
            "business_name": "TEST Retailer Co", "address": "1 Test Rd"
        })
        assert r.status_code == 200
        assert r.json()["user"]["status"] == "active"

        s_email = f"TEST_sup_{suffix}@distro.com"
        r2 = requests.post(f"{API}/auth/register", json={
            "email": s_email, "password": "Password@123", "name": "T Sup", "role": "supplier",
            "business_name": "TEST Supplier Co", "address": "2 Test Rd"
        })
        assert r2.status_code == 200
        assert r2.json()["user"]["status"] == "pending"

    def test_register_duplicate(self):
        r = requests.post(f"{API}/auth/register", json={
            "email": RETAILER[0], "password": "Password@123", "name": "x", "role": "retailer"
        })
        assert r.status_code == 400


# ---------- Products ----------
class TestProducts:
    def test_list_products(self):
        r = requests.get(f"{API}/products")
        assert r.status_code == 200
        assert len(r.json()) >= 8

    def test_filter_category(self):
        r = requests.get(f"{API}/products", params={"category": "Beverages"})
        assert r.status_code == 200
        for p in r.json():
            assert p["category"] == "Beverages"

    def test_filter_search(self):
        r = requests.get(f"{API}/products", params={"search": "Soda"})
        assert r.status_code == 200
        assert any("soda" in p["name"].lower() for p in r.json())

    def test_filter_in_stock(self):
        r = requests.get(f"{API}/products", params={"availability": "in_stock"})
        assert all(p["stock"] > 0 for p in r.json())

    def test_product_crud_supplier(self, tokens):
        tok = tokens["supplier"]["token"]
        payload = {"name": "TEST_Product", "category": "Beverages", "price_per_unit": 10.0,
                   "tier_pricing": [{"min_qty": 1, "price": 10.0}], "moq": 1, "stock": 100,
                   "image": "", "description": "TEST"}
        r = requests.post(f"{API}/products", json=payload, headers=_h(tok))
        assert r.status_code == 200
        pid = r.json()["id"]

        # Update
        payload["name"] = "TEST_Product_Updated"
        r = requests.put(f"{API}/products/{pid}", json=payload, headers=_h(tok))
        assert r.status_code == 200
        assert r.json()["name"] == "TEST_Product_Updated"

        # Other supplier can't edit
        tok2 = tokens["supplier2"]["token"]
        r = requests.put(f"{API}/products/{pid}", json=payload, headers=_h(tok2))
        assert r.status_code == 404

        # Delete by other should 404
        r = requests.delete(f"{API}/products/{pid}", headers=_h(tok2))
        assert r.status_code == 404

        # Delete by owner
        r = requests.delete(f"{API}/products/{pid}", headers=_h(tok))
        assert r.status_code == 200

    def test_product_create_retailer_forbidden(self, tokens):
        tok = tokens["retailer"]["token"]
        r = requests.post(f"{API}/products", json={
            "name": "x", "category": "a", "price_per_unit": 1.0, "moq": 1, "stock": 1
        }, headers=_h(tok))
        assert r.status_code == 403


# ---------- Orders ----------
class TestOrders:
    def _get_a_product(self):
        prods = requests.get(f"{API}/products").json()
        return next(p for p in prods if p["stock"] > p["moq"])

    def test_create_order_retailer(self, tokens):
        tok = tokens["retailer"]["token"]
        prod = self._get_a_product()
        before = prod["stock"]
        r = requests.post(f"{API}/orders", json={
            "items": [{"product_id": prod["id"], "name": prod["name"], "image": prod["image"],
                       "supplier_id": prod["supplier_id"], "quantity": prod["moq"],
                       "unit_price": prod["price_per_unit"]}],
            "delivery_address": "TEST addr", "notes": "TEST", "delivery_window": "9am"
        }, headers=_h(tok))
        assert r.status_code == 200
        orders = r.json()["orders"]
        assert len(orders) == 1
        assert orders[0]["status"] == "Pending"
        # verify stock decrement
        prod2 = next(p for p in requests.get(f"{API}/products").json() if p["id"] == prod["id"])
        assert prod2["stock"] == before - prod["moq"]
        pytest.order_id = orders[0]["id"]
        pytest.order_supplier_id = orders[0]["supplier_id"]

    def test_create_order_supplier_forbidden(self, tokens):
        tok = tokens["supplier"]["token"]
        r = requests.post(f"{API}/orders", json={
            "items": [], "delivery_address": "x"
        }, headers=_h(tok))
        assert r.status_code == 403

    def test_list_orders_retailer_isolation(self, tokens):
        r = requests.get(f"{API}/orders", headers=_h(tokens["retailer"]["token"]))
        assert r.status_code == 200
        for o in r.json():
            assert o["retailer_id"] == tokens["retailer"]["user"]["id"]

    def test_list_orders_supplier_isolation(self, tokens):
        r = requests.get(f"{API}/orders", headers=_h(tokens["supplier"]["token"]))
        assert r.status_code == 200
        for o in r.json():
            assert o["supplier_id"] == tokens["supplier"]["user"]["id"]

    def test_retailer_cannot_set_processing(self, tokens):
        tok = tokens["retailer"]["token"]
        oid = pytest.order_id
        r = requests.put(f"{API}/orders/{oid}/status", json={"status": "Processing"}, headers=_h(tok))
        assert r.status_code == 403

    def test_supplier_advances_order(self, tokens):
        # find token for the order's supplier
        sup_id = pytest.order_supplier_id
        tok = None
        for k in ("supplier", "supplier2"):
            if tokens[k]["user"]["id"] == sup_id:
                tok = tokens[k]["token"]
                break
        if not tok:
            # login via metro since product was from metro likely
            tok = tokens["supplier"]["token"]
        oid = pytest.order_id
        r = requests.put(f"{API}/orders/{oid}/status", json={"status": "Processing"}, headers=_h(tok))
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "Processing"

    def test_wrong_supplier_cannot_update(self, tokens):
        oid = pytest.order_id
        sup_id = pytest.order_supplier_id
        wrong = tokens["supplier2"] if tokens["supplier"]["user"]["id"] == sup_id else tokens["supplier"]
        r = requests.put(f"{API}/orders/{oid}/status", json={"status": "Delivered"},
                         headers=_h(wrong["token"]))
        assert r.status_code == 404

    def test_retailer_data_isolation(self, tokens):
        # retailer2 shouldn't see retailer's new order
        r = requests.get(f"{API}/orders", headers=_h(tokens["retailer2"]["token"]))
        assert r.status_code == 200
        assert pytest.order_id not in [o["id"] for o in r.json()]

    def test_invalid_status(self, tokens):
        oid = pytest.order_id
        tok = tokens["supplier"]["token"]
        r = requests.put(f"{API}/orders/{oid}/status", json={"status": "Nope"}, headers=_h(tok))
        assert r.status_code == 400


# ---------- Analytics ----------
class TestAnalytics:
    def test_supplier_analytics(self, tokens):
        r = requests.get(f"{API}/analytics/supplier", headers=_h(tokens["supplier"]["token"]))
        assert r.status_code == 200
        d = r.json()
        for k in ("revenue", "daily", "active_orders", "popular", "series", "low_stock"):
            assert k in d

    def test_admin_analytics(self, tokens):
        r = requests.get(f"{API}/analytics/admin", headers=_h(tokens["admin"]["token"]))
        assert r.status_code == 200
        d = r.json()
        for k in ("gmv", "total_orders", "fulfillment_rate", "fee_revenue"):
            assert k in d

    def test_retailer_cannot_see_admin_analytics(self, tokens):
        r = requests.get(f"{API}/analytics/admin", headers=_h(tokens["retailer"]["token"]))
        assert r.status_code == 403

    def test_supplier_cannot_see_admin_analytics(self, tokens):
        r = requests.get(f"{API}/analytics/admin", headers=_h(tokens["supplier"]["token"]))
        assert r.status_code == 403

    def test_retailer_cannot_see_supplier_analytics(self, tokens):
        r = requests.get(f"{API}/analytics/supplier", headers=_h(tokens["retailer"]["token"]))
        assert r.status_code == 403


# ---------- Admin ----------
class TestAdmin:
    def test_list_users(self, tokens):
        r = requests.get(f"{API}/admin/users", headers=_h(tokens["admin"]["token"]))
        assert r.status_code == 200
        assert len(r.json()) >= 5

    def test_filter_pending_suppliers(self, tokens):
        r = requests.get(f"{API}/admin/users", params={"role": "supplier"},
                         headers=_h(tokens["admin"]["token"]))
        pending = [u for u in r.json() if u["status"] == "pending"]
        assert len(pending) >= 1

    def test_approve_pending(self, tokens):
        r = requests.get(f"{API}/admin/users", params={"role": "supplier"},
                         headers=_h(tokens["admin"]["token"]))
        pending = [u for u in r.json() if u["email"] == "newdist@distro.com"]
        assert pending, "pending supplier not found"
        uid = pending[0]["id"]
        r = requests.put(f"{API}/admin/users/{uid}/status", json={"status": "active"},
                         headers=_h(tokens["admin"]["token"]))
        assert r.status_code == 200
        # verify
        r = requests.get(f"{API}/admin/users", headers=_h(tokens["admin"]["token"]))
        u = next(x for x in r.json() if x["id"] == uid)
        assert u["status"] == "active"
        # restore pending
        requests.put(f"{API}/admin/users/{uid}/status", json={"status": "pending"},
                     headers=_h(tokens["admin"]["token"]))

    def test_non_admin_forbidden(self, tokens):
        r = requests.get(f"{API}/admin/users", headers=_h(tokens["retailer"]["token"]))
        assert r.status_code == 403


# ---------- Messaging ----------
class TestMessaging:
    def test_contacts_retailer(self, tokens):
        r = requests.get(f"{API}/contacts", headers=_h(tokens["retailer"]["token"]))
        assert r.status_code == 200

    def test_send_and_get_message(self, tokens):
        rtok = tokens["retailer"]["token"]
        sid = tokens["supplier"]["user"]["id"]
        r = requests.post(f"{API}/messages", json={"to_id": sid, "text": "TEST hello"},
                          headers=_h(rtok))
        assert r.status_code == 200
        r = requests.get(f"{API}/messages/{sid}", headers=_h(rtok))
        assert r.status_code == 200
        assert any(m["text"] == "TEST hello" for m in r.json())


# ---------- Notifications ----------
class TestNotifications:
    def test_get_notifications(self, tokens):
        r = requests.get(f"{API}/notifications", headers=_h(tokens["supplier"]["token"]))
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_mark_read(self, tokens):
        r = requests.post(f"{API}/notifications/read", headers=_h(tokens["supplier"]["token"]))
        assert r.status_code == 200


# ---------- Profile ----------
class TestProfile:
    def test_update_profile(self, tokens):
        tok = tokens["retailer"]["token"]
        r = requests.put(f"{API}/profile",
                         json={"phone": "+1-555-9999", "address": "TEST updated"},
                         headers=_h(tok))
        assert r.status_code == 200
        d = r.json()
        assert d["phone"] == "+1-555-9999"
        assert d["address"] == "TEST updated"
