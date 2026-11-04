import io
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

import server

NOW = datetime.now(timezone.utc)


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *args, **kwargs):
        return self

    def skip(self, n):
        return self

    def limit(self, n):
        return self

    async def to_list(self, n):
        return list(self.rows)


class Collection:
    def __init__(self, rows):
        self.rows = rows

    def find(self, query=None, projection=None):
        return Cursor(self.rows)


class FakeDB:
    def __init__(self):
        month_start = NOW.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        self.users = Collection([
            {"id": "s1", "role": "supplier", "business_name": "Distro A", "email": "a@x.ge",
             "identification_number": "123456789", "billing_frozen": False},
            {"id": "r1", "role": "retailer", "business_name": "Shop One"},
        ])
        self.invoices = Collection([
            {"id": "i1", "invoice_no": "INV-1", "supplier_id": "s1", "supplier_name": "Distro A", "amount": 50.0,
             "status": "paid", "due_date": (NOW - timedelta(days=3)).isoformat(), "paid_at": NOW.isoformat(),
             "period_label": "Last month", "created_at": NOW.isoformat()},
            {"id": "i2", "invoice_no": "INV-2", "supplier_id": "s1", "supplier_name": "Distro A", "amount": 70.0,
             "status": "pending", "due_date": (NOW - timedelta(days=3)).isoformat(),
             "period_label": "Last month", "created_at": NOW.isoformat()},
        ])
        self.orders = Collection([
            {"id": "o1", "supplier_id": "s1", "retailer_id": "r1", "retailer_name": "Shop One",
             "supplier_name": "Distro A", "status": "Delivered", "total": 200.0, "amount_paid": 50.0,
             "commission_amount": 10.0, "delivered_at": (month_start + timedelta(hours=1)).isoformat(),
             "created_at": (month_start + timedelta(hours=1)).isoformat()},
        ])


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server, "db", FakeDB())
    server.app.dependency_overrides[server.get_current_user] = lambda: {"id": "a1", "role": "admin"}
    yield TestClient(server.app)
    server.app.dependency_overrides.clear()


@pytest.mark.parametrize("path", ["/api/export-financials", "/api/admin/financials/export.xlsx"])
def test_export_returns_workbook_with_all_sheets(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert "spreadsheetml" in response.headers["content-type"]
    wb = load_workbook(io.BytesIO(response.content))
    assert wb.sheetnames == ["შეჯამება", "ინვოისები", "ბალანსები"]
    summary = [row for row in wb["შეჯამება"].iter_rows(values_only=True)]
    assert summary[0][:6] == ("ლოგო", "დისტრიბუტორი", "სას. კოდი", "ელ. ფოსტა", "თვის ბრუნვა (ლარი)",
                              "დარიცხული საკომისიო (ლარი)")
    assert summary[1][1] == "Distro A" and summary[1][4] == 200.0 and summary[1][5] == 10.0
    balances = [row for row in wb["ბალანსები"].iter_rows(values_only=True)]
    assert balances[1] == (None, "Shop One", "Distro A", 1, 200.0, 50.0, 150.0)


def test_export_status_filter_and_validation(client):
    wb = load_workbook(io.BytesIO(client.get("/api/export-financials?status=paid").content))
    assert [r[1] for r in wb["ინვოისები"].iter_rows(min_row=2, values_only=True)] == ["INV-1"]
    wb = load_workbook(io.BytesIO(client.get("/api/export-financials?status=overdue").content))
    assert [r[1] for r in wb["ინვოისები"].iter_rows(min_row=2, values_only=True)] == ["INV-2"]
    assert client.get("/api/export-financials?status=bogus").status_code == 400


def _png(color):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (400, 300), color).save(buf, format="PNG")
    return buf.getvalue()


def test_export_embeds_logos_and_placeholders(client, tmp_path, monkeypatch):
    import logos
    monkeypatch.setattr(logos, "LOGO_DIR", tmp_path)
    logos.save_logo("s1", logos.process_upload(_png("red")))  # distributor has a logo, store r1 does not
    wb = load_workbook(io.BytesIO(client.get("/api/export-financials").content))
    assert len(wb["შეჯამება"]._images) == 2  # fake DB returns both users as distributors
    assert len(wb["ინვოისები"]._images) == 2
    assert len(wb["ბალანსები"]._images) == 1  # placeholder for the store without a logo


def test_logo_processing_rejects_non_images_and_resizes():
    import logos
    from PIL import Image
    with pytest.raises(logos.LogoError):
        logos.process_upload(b"<svg onload=alert(1)></svg>")
    with pytest.raises(logos.LogoError):
        logos.process_upload(b"x" * (logos.MAX_LOGO_BYTES + 1))
    out = Image.open(io.BytesIO(logos.process_upload(_png("blue"))))
    assert out.format == "PNG" and max(out.size) <= logos.MAX_LOGO_SIDE
    assert Image.open(io.BytesIO(logos.placeholder_png("დისტრიბუტორი"))).size == (128, 128)


class UsersWithUpdate(Collection):
    async def find_one(self, query, projection=None):
        return next((r for r in self.rows if r["id"] == query["id"]), None)

    async def update_one(self, query, update):
        row = await self.find_one(query)
        row.update(update.get("$set", {}))
        for key in update.get("$unset", {}):
            row.pop(key, None)


def test_logo_upload_serve_and_delete(client, tmp_path, monkeypatch):
    import logos
    monkeypatch.setattr(logos, "LOGO_DIR", tmp_path)
    monkeypatch.setattr(server.db, "users", UsersWithUpdate([{"id": "a1", "role": "admin", "business_name": "Admin"}]))
    bad = client.post("/api/profile/logo", files={"file": ("x.png", b"not an image", "image/png")})
    assert bad.status_code == 400
    ok = client.post("/api/profile/logo", files={"file": ("logo.png", _png("green"), "image/png")})
    assert ok.status_code == 200 and ok.json()["logo_url"].startswith("/logos/a1?v=")
    served = client.get("/api/logos/a1")
    assert served.status_code == 200 and served.headers["content-type"] == "image/png"
    assert (tmp_path / "a1.png").is_file()
    removed = client.delete("/api/profile/logo")
    assert "logo_url" not in removed.json() and not (tmp_path / "a1.png").exists()
    assert client.get("/api/logos/a1").status_code == 200  # placeholder fallback
