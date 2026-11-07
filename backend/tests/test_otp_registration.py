"""Backend tests for registration persistence bug fix and OTP email verification flow."""
import os
import re
import time
import uuid
import subprocess
import pytest
import requests

def _load_backend_url():
    url = os.environ.get('REACT_APP_BACKEND_URL')
    if not url:
        env_path = os.path.join(os.path.dirname(__file__), '..', '..', 'frontend', '.env')
        with open(env_path) as f:
            for line in f:
                if line.startswith('REACT_APP_BACKEND_URL='):
                    url = line.split('=', 1)[1].strip()
                    break
    assert url, "REACT_APP_BACKEND_URL not set"
    return url.rstrip('/')


BASE_URL = _load_backend_url()
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "mgv67mk2j5@privaterelay.appleid.com"
ADMIN_PASSWORD = "Admin@123"
DEMO_SUPPLIER = "metro@distro.com"
DEMO_PASSWORD = "Password@123"


def _unique_email(prefix="qa_user"):
    return f"{prefix}_{uuid.uuid4().hex[:10]}@realbiz.com"


def _read_otp_from_logs(email: str, timeout: float = 6.0) -> str:
    """Grep OTP from /var/log/supervisor/backend.*.log. Takes latest occurrence."""
    deadline = time.time() + timeout
    pattern = re.compile(rf"OTP\] Verification code for {re.escape(email)}: (\d{{6}})")
    code = None
    while time.time() < deadline:
        try:
            out = subprocess.check_output(
                "grep -ah 'OTP] Verification code' /var/log/supervisor/backend.*.log | tail -200",
                shell=True, stderr=subprocess.DEVNULL
            ).decode()
            matches = pattern.findall(out)
            if matches:
                code = matches[-1]
                break
        except Exception:
            pass
        time.sleep(0.3)
    assert code, f"Could not find OTP for {email} in backend logs"
    return code


def _register_supplier(payload):
    return requests.post(f"{API}/auth/register", json=payload)


@pytest.fixture
def supplier_payload():
    email = _unique_email()
    return {
        "email": email,
        "password": "SuperSecret@123",
        "name": "QA Supplier",
        "role": "supplier",
        "business_name": "QA Bev Co",
        "identification_number": "TAX-9988776",
        "phone": "+995555112233",
        "address": "123 Rustaveli Ave",
        "city": "Tbilisi",
        "category": "Beverages",
        "bank_name": "Bank of Georgia",
        "iban": "GE29NB0000000101904917",
        "accept_terms": True,
    }


# -------------------- Registration persistence + token gating --------------------

class TestRegistration:
    def test_register_returns_verification_required_no_token(self, supplier_payload):
        r = _register_supplier(supplier_payload)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("verification_required") is True
        assert data.get("email") == supplier_payload["email"].lower()
        assert "token" not in data

    def test_disposable_email_rejected(self, supplier_payload):
        supplier_payload["email"] = f"qa_{uuid.uuid4().hex[:6]}@mailinator.com"
        r = requests.post(f"{API}/auth/register", json=supplier_payload)
        assert r.status_code == 400
        assert "disposable" in r.json().get("detail", "").lower() or "temporary" in r.json().get("detail", "").lower()

    def test_malformed_email_rejected(self, supplier_payload):
        supplier_payload["email"] = "not-an-email"
        r = requests.post(f"{API}/auth/register", json=supplier_payload)
        assert r.status_code == 422

    def test_unverified_login_returns_403(self, supplier_payload):
        rr = _register_supplier(supplier_payload)
        assert rr.status_code == 200
        r = requests.post(f"{API}/auth/login", json={
            "email": supplier_payload["email"], "password": supplier_payload["password"]
        })
        assert r.status_code == 403
        assert "EMAIL_NOT_VERIFIED" in r.json().get("detail", "")


# -------------------- OTP verify + resend + bug-fix persistence --------------------

class TestOtpVerifyAndPersistence:
    @pytest.fixture
    def registered_supplier(self, supplier_payload):
        r = _register_supplier(supplier_payload)
        assert r.status_code == 200, r.text
        return supplier_payload

    def test_verify_wrong_code_then_success_and_fields_persist(self, registered_supplier):
        email = registered_supplier["email"].lower()

        # Wrong code -> 400
        bad = requests.post(f"{API}/auth/verify-otp", json={"email": email, "code": "000001"})
        assert bad.status_code == 400
        assert "Invalid" in bad.json().get("detail", "")

        code = _read_otp_from_logs(email)
        ok = requests.post(f"{API}/auth/verify-otp", json={"email": email, "code": code})
        assert ok.status_code == 200, ok.text
        data = ok.json()
        assert "token" in data and data.get("user", {}).get("email_verified") is True

        token = data["token"]
        headers = {"Authorization": f"Bearer {token}"}
        me = requests.get(f"{API}/auth/me", headers=headers)
        assert me.status_code == 200
        u = me.json()

        # BUG FIX persistence assertions — all registration fields must be stored
        assert u["email"] == email
        assert u["phone"] == registered_supplier["phone"]           # was dropped before fix
        assert u["category"] == registered_supplier["category"]     # didn't exist before fix
        assert u["business_name"] == registered_supplier["business_name"]
        assert u["identification_number"] == registered_supplier["identification_number"]
        assert u["address"] == registered_supplier["address"]
        assert u["city"] == registered_supplier["city"]
        assert u["bank_name"] == registered_supplier["bank_name"]
        assert u["iban"] == registered_supplier["iban"]
        assert u["role"] == "supplier"
        assert u["email_verified"] is True

    def test_profile_update_persists_phone_category_and_others(self, registered_supplier):
        email = registered_supplier["email"].lower()
        code = _read_otp_from_logs(email)
        ok = requests.post(f"{API}/auth/verify-otp", json={"email": email, "code": code})
        assert ok.status_code == 200
        token = ok.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        new_data = {
            "phone": "+995599998888",
            "category": "Snacks & Sweets",
            "business_name": "QA Bev Co UPDATED",
            "iban": "GE00NEWIBAN0000001234",
            "address": "456 New Address St",
        }
        pu = requests.put(f"{API}/profile", json=new_data, headers=headers)
        assert pu.status_code == 200

        me = requests.get(f"{API}/auth/me", headers=headers)
        u = me.json()
        for k, v in new_data.items():
            assert u[k] == v, f"profile update field {k} did not persist (got {u.get(k)})"

    def test_verify_wrong_5_times_returns_429(self, supplier_payload):
        _register_supplier(supplier_payload)
        email = supplier_payload["email"].lower()
        last = None
        for _ in range(5):
            last = requests.post(f"{API}/auth/verify-otp", json={"email": email, "code": "000000"})
        # 5th call: attempts was 4, increments to 5 and returns 400 Invalid. 6th call -> 429.
        r6 = requests.post(f"{API}/auth/verify-otp", json={"email": email, "code": "000000"})
        assert r6.status_code == 429, f"expected 429 after >=5 bad attempts, got {r6.status_code} {r6.text}"

    def test_verify_nonexistent_email_400(self):
        r = requests.post(f"{API}/auth/verify-otp", json={
            "email": f"nobody_{uuid.uuid4().hex[:6]}@realbiz.com", "code": "123456"
        })
        assert r.status_code == 400


class TestResendOtp:
    def test_resend_throttled_and_already_verified(self, supplier_payload):
        _register_supplier(supplier_payload)
        email = supplier_payload["email"].lower()

        # Register just issued an OTP (<45s ago) -> immediate resend should 429
        r1 = requests.post(f"{API}/auth/resend-otp", json={"email": email})
        assert r1.status_code == 429, r1.text

        # Verify to flip to verified
        code = _read_otp_from_logs(email)
        v = requests.post(f"{API}/auth/verify-otp", json={"email": email, "code": code})
        assert v.status_code == 200

        # Resend for already-verified -> 400
        r2 = requests.post(f"{API}/auth/resend-otp", json={"email": email})
        assert r2.status_code == 400


# -------------------- Seeded users regression (no OTP) --------------------

class TestSeededAccounts:
    def test_admin_login_without_otp(self):
        r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert r.status_code == 200, r.text
        assert "token" in r.json()
        assert r.json()["user"].get("email_verified") is True

    def test_demo_supplier_login_without_otp(self):
        r = requests.post(f"{API}/auth/login", json={"email": DEMO_SUPPLIER, "password": DEMO_PASSWORD})
        assert r.status_code == 200, r.text
        assert "token" in r.json()
