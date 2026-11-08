import asyncio
import copy
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from invoices import _invoice_totals, build_invoice_pdf
from migrations.store_finance import upgrade


def _matches(document, query):
    for key, expected in query.items():
        if key == "$or":
            if not any(_matches(document, branch) for branch in expected):
                return False
            continue
        if key == "$expr":
            amount = expected["$lte"][0]["$add"][1]
            if float(document.get("amount_paid", 0) or 0) + amount > float(document.get("total", 0)):
                return False
            continue
        value = document.get(key)
        if isinstance(expected, dict):
            if "$in" in expected and value not in expected["$in"]:
                return False
            if "$ne" in expected and value == expected["$ne"]:
                return False
            if "$gte" in expected and (value is None or value < expected["$gte"]):
                return False
            if "$lt" in expected and (value is None or value >= expected["$lt"]):
                return False
            if "$exists" in expected and (key in document) != expected["$exists"]:
                return False
            if "$regex" in expected:
                flags = re.IGNORECASE if expected.get("$options") == "i" else 0
                if not re.search(expected["$regex"], str(value or ""), flags):
                    return False
        elif value != expected:
            return False
    return True


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, field, direction=1):
        self.rows.sort(key=lambda row: row.get(field) or "", reverse=direction < 0)
        return self

    async def to_list(self, limit):
        return copy.deepcopy(self.rows[:limit])

    def __aiter__(self):
        self.index = 0
        return self

    async def __anext__(self):
        if self.index >= len(self.rows):
            raise StopAsyncIteration
        row = self.rows[self.index]
        self.index += 1
        return copy.deepcopy(row)


class _Collection:
    def __init__(self, rows=()):
        self.rows = [copy.deepcopy(row) for row in rows]

    def find(self, query, projection=None):
        rows = [row for row in self.rows if _matches(row, query)]
        if projection:
            included = {key for key, flag in projection.items() if flag == 1}
            if included:
                rows = [{key: value for key, value in row.items() if key in included} for row in rows]
            elif projection.get("_id") == 0:
                rows = [{key: value for key, value in row.items() if key not in projection} for row in rows]
        return _Cursor(rows)

    async def find_one(self, query, projection=None):
        rows = await self.find(query, projection).to_list(1)
        return rows[0] if rows else None

    async def update_one(self, query, update, upsert=False):
        for row in self.rows:
            if not _matches(row, query):
                continue
            row.update(copy.deepcopy(update.get("$set", {})))
            for key, value in update.get("$inc", {}).items():
                row[key] = row.get(key, 0) + value
            for key, value in update.get("$push", {}).items():
                row.setdefault(key, []).append(copy.deepcopy(value))
            return type("UpdateResult", (), {"matched_count": 1, "modified_count": 1})()
        if upsert:
            row = {key: value for key, value in query.items() if not key.startswith("$")}
            row.update(copy.deepcopy(update.get("$setOnInsert", {})))
            row.update(copy.deepcopy(update.get("$set", {})))
            self.rows.append(row)
            return type("UpdateResult", (), {"matched_count": 0, "modified_count": 1})()
        return type("UpdateResult", (), {"matched_count": 0, "modified_count": 0})()

    async def create_index(self, *_args, **_kwargs):
        return None

    async def insert_one(self, document):
        self.rows.append(copy.deepcopy(document))
        return type("InsertOneResult", (), {"inserted_id": document.get("id")})()


def _setup(monkeypatch, role):
    now = datetime.now(timezone.utc)
    older = (now - timedelta(days=20)).isoformat()
    recent = (now - timedelta(days=2)).isoformat()
    orders = _Collection([
        {
            "id": "order-unpaid", "order_no": "ORD-UNPAID", "retailer_id": "store-1",
            "retailer_name": "Corner Store", "supplier_id": "supplier-1", "supplier_name": "North",
            "total": 100, "amount_paid": 0, "payment_entries": [], "status": "Delivered",
            "delivered_at": older, "created_at": older, "payment_method": "consignment",
            "items": [{"name": "Tea", "quantity": 2, "unit_price": 50}],
        },
        {
            "id": "order-paid", "order_no": "ORD-PAID", "retailer_id": "store-1",
            "retailer_name": "Corner Store", "supplier_id": "supplier-2", "supplier_name": "South",
            "total": 50, "paid_at_checkout": True, "status": "Delivered", "delivered_at": recent,
            "created_at": recent, "payment_method": "card", "items": [],
        },
        {
            "id": "order-external", "external_order": True, "supplier_id": "supplier-1",
            "retailer_id": "store-1", "total": 900, "status": "Delivered",
        },
    ])
    terms = _Collection([{
        "supplier_id": "supplier-1", "retailer_id": "store-1",
        "credit_limit": 300, "payment_due_days": 7,
    }])
    users = _Collection([
        {"id": "store-1", "role": "retailer", "business_name": "Corner Store"},
        {"id": "supplier-1", "role": "supplier", "business_name": "North"},
        {"id": "supplier-2", "role": "supplier", "business_name": "South"},
    ])
    current_user = {
        "id": "supplier-1" if role == "supplier" else "store-1",
        "role": role,
        "business_name": "North" if role == "supplier" else "Corner Store",
    }
    monkeypatch.setattr(server, "db", type("MemoryDB", (), {
        "orders": orders, "credit_terms": terms, "users": users,
        "financial_audit_logs": _Collection(),
    })())
    server.app.dependency_overrides[server.get_current_user] = lambda: current_user
    return TestClient(server.app), orders, terms


def test_retailer_finance_summarizes_credit_and_excludes_external_orders(monkeypatch):
    client, _orders, _terms = _setup(monkeypatch, "retailer")
    try:
        response = client.get("/api/store/finance")
        assert response.status_code == 200
        data = response.json()
        north = next(account for account in data["accounts"] if account["supplier_id"] == "supplier-1")
        assert north["outstanding_balance"] == 100
        assert north["credit_limit"] == 300
        assert north["available_credit"] == 200
        unpaid = next(order for order in data["orders"] if order["id"] == "order-unpaid")
        assert unpaid["payment_status"] == "overdue"
        paid = next(order for order in data["orders"] if order["id"] == "order-paid")
        assert paid["payment_status"] == "paid"
        assert all(order["id"] != "order-external" for order in data["orders"])
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_retailer_date_range_filters_history_but_keeps_lifetime_receivables(monkeypatch):
    client, _orders, _terms = _setup(monkeypatch, "retailer")
    today = datetime.now(timezone.utc).date()
    start = (today - timedelta(days=5)).isoformat()
    end = today.isoformat()
    try:
        response = client.get("/api/store/finance", params={"start_date": start, "end_date": end})
        assert response.status_code == 200
        data = response.json()
        assert [order["id"] for order in data["orders"]] == ["order-paid"]
        north = next(account for account in data["accounts"] if account["supplier_id"] == "supplier-1")
        assert north["outstanding_balance"] == 100
        assert data["due_calendar"][0]["order_id"] == "order-unpaid"
        assert data["date_range"] == {"start_date": start, "end_date": end}
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_supplier_credit_range_filters_store_orders_but_keeps_lifetime_receivables(monkeypatch):
    client, _orders, _terms = _setup(monkeypatch, "supplier")
    today = datetime.now(timezone.utc).date()
    start = (today - timedelta(days=5)).isoformat()
    end = today.isoformat()
    try:
        response = client.get("/api/supplier/credit-accounts", params={"start_date": start, "end_date": end})
        assert response.status_code == 200
        account = next(row for row in response.json() if row["retailer_id"] == "store-1")
        assert account["orders"] == []
        assert account["period_sales"] == 0
        assert account["outstanding_balance"] == 100
        assert account["due_calendar"][0]["order_id"] == "order-unpaid"
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_supplier_can_update_terms_and_record_partial_payments(monkeypatch):
    client, orders, _terms = _setup(monkeypatch, "supplier")
    try:
        response = client.put("/api/supplier/stores/store-1/credit", json={
            "credit_limit": 500, "payment_due_days": 30,
        })
        assert response.status_code == 200
        assert response.json()["payment_due_days"] == 30

        response = client.post("/api/supplier/orders/order-unpaid/payments", json={
            "amount": 40, "method": "bank_transfer", "reference": "TRX-1", "note": "First part",
        })
        assert response.status_code == 200
        assert response.json()["payment_status"] == "partially_paid"
        assert response.json()["balance_due"] == 60

        response = client.post("/api/supplier/orders/order-unpaid/payments", json={
            "amount": 60, "method": "cash",
        })
        assert response.status_code == 200
        assert response.json()["payment_status"] == "paid"
        assert response.json()["balance_due"] == 0
        assert len(next(order for order in orders.rows if order["id"] == "order-unpaid")["payment_entries"]) == 2

        response = client.post("/api/supplier/orders/order-unpaid/payments", json={
            "amount": 1, "method": "cash",
        })
        assert response.status_code == 409
        response = client.post("/api/supplier/orders/order-paid/payments", json={
            "amount": 1, "method": "cash",
        })
        assert response.status_code == 404
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_order_invoice_pdf_respects_staff_branch_and_finance_permission(monkeypatch):
    client, orders, _terms = _setup(monkeypatch, "retailer")
    orders.rows[0]["branch_id"] = "branch-1"
    orders.rows[1]["branch_id"] = "branch-2"
    staff = {"id": "staff-1", "role": "retailer", "retailer_id": "store-1", "store_access_role": "staff", "assigned_branch_id": "branch-1", "permissions": {"canViewFinancials": True}}
    server.app.dependency_overrides[server.get_current_user] = lambda: staff
    try:
        assert client.get("/api/orders/order-unpaid/invoice.pdf").status_code == 200
        assert client.get("/api/orders/order-paid/invoice.pdf").status_code == 404
        staff["permissions"]["canViewFinancials"] = False
        assert client.get("/api/orders/order-unpaid/invoice.pdf").status_code == 403
        staff["permissions"]["canViewFinancials"] = True
        staff.pop("assigned_branch_id")
        assert client.get("/api/orders/order-unpaid/invoice.pdf").status_code == 404
        staff["retailer_id"] = "other-store"
        assert client.get("/api/orders/order-unpaid/invoice.pdf").status_code == 404
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_order_invoice_pdf_is_scoped_to_supplier(monkeypatch):
    client, _orders, _terms = _setup(monkeypatch, "supplier")
    try:
        assert client.get("/api/orders/order-unpaid/invoice.pdf").status_code == 200
        assert client.get("/api/orders/order-paid/invoice.pdf").status_code == 404
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_order_invoice_pdf_is_available_to_the_store(monkeypatch):
    client, _orders, _terms = _setup(monkeypatch, "retailer")
    _orders.rows[1]["items"] = [{"name": "ჩაი", "quantity": 1, "unit": "ცალი", "unit_price": 50}]
    users = server.db.users
    users.rows[0].update({
        "identification_number": "123456789", "address": "თბილისი", "phone": "555123456",
    })
    users.rows[2].update({
        "identification_number": "987654321", "address": "ქუთაისი", "phone": "555987654",
        "bank_name": "ქართული ბანკი", "iban": "GE00TEST1234", "vat_registered": True,
    })
    try:
        response = client.get("/api/orders/order-paid/invoice.pdf")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.content.startswith(b"%PDF")
        assert b"/Lang (ka-GE)" in response.content
        assert b"/FontFile2" in response.content
        assert b"/ToUnicode" in response.content
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_finance_export_xlsx_filters_period_and_includes_vat(monkeypatch):
    import io
    from openpyxl import load_workbook
    client, _orders, _terms = _setup(monkeypatch, "supplier")
    server.db.users.rows[1]["vat_registered"] = True
    try:
        response = client.get("/api/finance/export.xlsx")
        assert response.status_code == 200
        sheet = load_workbook(io.BytesIO(response.content))["ინვოისები"]
        rows = [row for row in sheet.iter_rows(min_row=2, values_only=True) if row[0]]
        assert [row[0] for row in rows] == ["ORD-UNPAID", "სულ"]
        unpaid = rows[0]
        assert (unpaid[5], unpaid[6], unpaid[7], unpaid[9]) == (84.75, 15.25, 100, 100)
        assert unpaid[10] == "გადაუხდელი" or unpaid[10] == "ვადაგადაცილებული"
        future = client.get("/api/finance/export.xlsx", params={"date_from": "2999-01-01"})
        empty = load_workbook(io.BytesIO(future.content))["ინვოისები"]
        assert [row[0] for row in empty.iter_rows(min_row=2, values_only=True) if row[0]] == ["სულ"]
        assert client.get("/api/finance/export.xlsx", params={"date_from": "bad"}).status_code == 400
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_order_invoice_extracts_vat_inclusive_total_only_for_registered_supplier():
    assert _invoice_totals(118, vat_registered=True) == (100, 18, 118)
    assert _invoice_totals(118, vat_registered=False) == (118, 0.0, 118)


def test_supplier_can_save_vat_registration_for_invoice_generation(monkeypatch):
    client, _orders, _terms = _setup(monkeypatch, "supplier")
    try:
        response = client.put("/api/profile", json={"vat_registered": True})
        assert response.status_code == 200
        assert response.json()["vat_registered"] is True
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_commission_invoice_pdf_uses_georgian_language_and_embedded_font():
    pdf = build_invoice_pdf({
        "invoice_no": "INV-202610-ABCD", "issuer_name": "Distro Logistics",
        "issuer_tax_id": "123456789", "supplier_name": "მომწოდებელი",
        "period_label": "ოქტომბერი 2026", "issue_label": "21 ოქტომბერი 2026",
        "due_label": "26 ოქტომბერი 2026", "line_items": [],
        "amount": 25,
    })
    assert pdf.startswith(b"%PDF")
    assert b"/Lang (ka-GE)" in pdf
    assert b"/FontFile2" in pdf
    assert b"/ToUnicode" in pdf


def test_migration_backfills_legacy_paid_and_unpaid_order_ledgers():
    orders = _Collection([
        {"id": "paid", "total": 25, "payment_method": "tbc", "paid_at_checkout": True},
        {"id": "unpaid", "total": 40, "payment_method": "cash"},
    ])
    db = type("MemoryDB", (), {"orders": orders, "credit_terms": _Collection()})()
    asyncio.run(upgrade(db))
    asyncio.run(upgrade(db))
    paid = next(order for order in orders.rows if order["id"] == "paid")
    unpaid = next(order for order in orders.rows if order["id"] == "unpaid")
    assert paid["amount_paid"] == 25
    assert paid["payment_entries"][0]["automatic"] is True
    assert unpaid["amount_paid"] == 0
    assert unpaid["payment_entries"] == []


def test_legacy_delivery_uses_fourteen_day_due_term():
    delivered = datetime(2026, 1, 1, tzinfo=timezone.utc)
    order = {
        "id": "legacy", "total": 20, "status": "Delivered",
        "delivered_at": delivered.isoformat(), "amount_paid": 0,
    }
    due_day = server.finance_order_view(order, None, delivered + timedelta(days=14))
    late_day = server.finance_order_view(order, None, delivered + timedelta(days=15))
    assert due_day["payment_due_days"] == 14
    assert due_day["payment_status"] == "unpaid"
    assert late_day["payment_status"] == "overdue"
