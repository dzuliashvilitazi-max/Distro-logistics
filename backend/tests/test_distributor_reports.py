import asyncio
import io

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient
from openpyxl import load_workbook

import server

SUPPLIER = {"id": "d1", "role": "supplier", "business_name": "Distro One", "supplier_access_role": "global_admin"}
OTHER = "d2"


def order(oid, supplier, store, status, total, qty, unit, created, **extra):
    return {
        "id": oid, "order_no": f"ORD-{oid}", "supplier_id": supplier, "retailer_id": store, "retailer_name": store.upper(),
        "status": status, "total": total, "service_fee": round(total * extra.pop("rate", 0.03), 2),
        "fee_type": "percent", "fee_value": 3, "created_at": created, "delivered_at": created if status == "Delivered" else None,
        "items": [{"product_id": "p1", "name": "Chips", "quantity": qty, "unit_price": unit}],
        "payment_method": "cash", "amount_paid": extra.pop("paid", 0), **extra,
    }


@pytest.fixture
def client(monkeypatch):
    database = AsyncMongoMockClient()["reports_test"]
    asyncio.run(database.orders.insert_many([
        order("1", "d1", "s1", "Delivered", 100.0, 10, 10.0, "2026-10-05T08:00:00+00:00", paid=100.0),
        order("2", "d1", "s2", "Delivered", 50.0, 5, 10.0, "2026-10-20T08:00:00+00:00", rate=0.05),
        order("3", "d1", "s1", "Pending", 30.0, 3, 10.0, "2026-10-25T08:00:00+00:00"),
        order("4", "d1", "s1", "Cancelled", 80.0, 8, 10.0, "2026-10-26T08:00:00+00:00"),
        order("5", "d2", "s9", "Delivered", 999.0, 9, 111.0, "2026-10-06T08:00:00+00:00"),
        order("6", "d1", "s1", "Delivered", 40.0, 4, 10.0, "2026-09-10T08:00:00+00:00"),
    ]))
    asyncio.run(database.payouts.insert_one({"supplier_id": "d1", "order_no": "ORD-1", "supplier_payout": 97.0, "commission": 3.0,
                                              "status": "settled", "method": "checkout_card", "created_at": "2026-10-05T09:00:00+00:00"}))
    monkeypatch.setattr(server, "db", database)
    monkeypatch.setattr(server, "supplier_warehouse_id", lambda *_a, **_k: asyncio.sleep(0, result=None))
    server.app.dependency_overrides[server.get_current_user] = lambda: SUPPLIER
    yield TestClient(server.app)
    server.app.dependency_overrides.pop(server.get_current_user, None)


def test_completed_orders_only_delivered_own_orders_with_commission(client):
    data = client.get("/api/supplier/reports/completed-orders").json()
    assert {r["order_no"] for r in data["items"]} == {"ORD-1", "ORD-2", "ORD-6"}
    row = next(r for r in data["items"] if r["order_no"] == "ORD-2")
    assert row["commission"] == 2.5 and row["net_after_commission"] == 47.5 and row["commission_value"] == 3
    assert data["summary"]["count"] == 3 and data["summary"]["commission"] == 6.7


def test_completed_orders_filters(client):
    data = client.get("/api/supplier/reports/completed-orders", params={"store_id": "s1", "start_date": "2026-10-01", "end_date": "2026-10-31"}).json()
    assert [r["order_no"] for r in data["items"]] == ["ORD-1"]
    paid = client.get("/api/supplier/reports/completed-orders", params={"payment_status": "paid"}).json()
    assert [r["order_no"] for r in paid["items"]] == ["ORD-1"]
    assert client.get("/api/supplier/reports/completed-orders", params={"order_no": "ord-6"}).json()["total"] == 1
    assert client.get("/api/supplier/reports/completed-orders", params={"product": "chip"}).json()["total"] == 3


def test_analytics_uses_frozen_commission_and_compares_periods(client):
    data = client.get("/api/supplier/reports/analytics", params={"start_date": "2026-10-01", "end_date": "2026-10-31"}).json()
    kpis = data["kpis"]
    assert kpis["total_sales"] == 180.0 and kpis["orders"] == 3 and kpis["completed_orders"] == 2
    assert kpis["commission"] == 3.0 + 2.5 + 0.9 and kpis["quantity"] == 18
    assert kpis["average_order_value"] == 60.0
    assert data["previous"]["total_sales"] == 40.0 and data["change"]["total_sales"] == 350.0
    assert {s["store_id"] for s in data["stores"]} == {"s1", "s2"}
    only_s2 = client.get("/api/supplier/reports/analytics", params={"start_date": "2026-10-01", "end_date": "2026-10-31", "store_id": "s2"}).json()
    assert only_s2["kpis"]["total_sales"] == 50.0


def test_finance_summary_settlements_and_filters(client):
    data = client.get("/api/supplier/reports/finance", params={"start_date": "2026-10-01", "end_date": "2026-10-31"}).json()
    assert data["summary"]["completed_sales"] == 150.0 and data["summary"]["commission"] == 5.5
    assert data["summary"]["commission_percent"] == round(5.5 / 150 * 100, 2)
    assert data["summary"]["commission_agreements"]
    assert any(e["kind"] == "payout" and e["status"] == "settled" for e in data["settlements"])
    unpaid = client.get("/api/supplier/reports/finance", params={"status": "unpaid"}).json()
    assert all(r["payment_status"] == "unpaid" for r in unpaid["items"])
    big = client.get("/api/supplier/reports/finance", params={"min_amount": "60"}).json()
    assert [r["order_no"] for r in big["items"]] == ["ORD-1"]


def test_exports_csv_and_xlsx_respect_filters(client):
    csv_response = client.get("/api/supplier/reports/completed-orders/export", params={"format": "csv", "store_id": "s2"})
    assert csv_response.status_code == 200 and "ORD-2" in csv_response.text and "ORD-1" not in csv_response.text
    xlsx = client.get("/api/supplier/reports/finance/export", params={"format": "xlsx"})
    workbook = load_workbook(io.BytesIO(xlsx.content))
    assert set(workbook.sheetnames) == {"ინვოისები", "ფინანსები", "ანგარიშსწორებები"}
    analytics = client.get("/api/supplier/reports/analytics/export", params={"format": "csv", "start_date": "2026-10-01", "end_date": "2026-10-31"})
    assert analytics.status_code == 200


def test_csv_cells_cannot_inject_formulas():
    from distributor_reports import to_csv
    out = to_csv({"x": ([("a", "A")], [{"a": "=HYPERLINK(1)"}])}).decode("utf-8-sig")
    assert "'=HYPERLINK" in out
