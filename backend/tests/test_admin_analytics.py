from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

import server

NOW = datetime.now(timezone.utc)
THIS = NOW.strftime("%Y-%m")


def order(oid, status, total, fee, retailer, supplier, created=None, **extra):
    return {"id": oid, "status": status, "total": total, "service_fee": fee, "retailer_id": retailer,
            "supplier_id": supplier, "created_at": created or NOW.isoformat(), **extra}


@pytest.fixture
def client(monkeypatch):
    db = AsyncMongoMockClient()["analytics_test"]
    monkeypatch.setattr(server, "db", db)
    users = [
        {"id": "admin", "role": "admin", "created_at": NOW.isoformat()},
        {"id": "r1", "role": "retailer", "created_at": NOW.isoformat()},
        {"id": "r2", "role": "retailer", "created_at": NOW.isoformat()},
        {"id": "s1", "role": "supplier", "created_at": NOW.isoformat()},
        {"id": "s2", "role": "supplier", "created_at": "2020-01-05T00:00:00+00:00"},
    ]
    orders = [
        order("o1", "Delivered", 100.0, 5.0, "r1", "s1"),
        order("o2", "Pending", 200.0, 10.0, "r1", "s1"),
        order("o3", "Cancelled", 999.0, 50.0, "r2", "s1"),
        order("o4", "In Transit", 300.0, 15.0, "r1", "s1"),
        order("o5", "Delivered", 5000.0, 0, "r2", "s1", external_order=True),
        order("o6", "Delivered", 400.0, 20.0, "r2", "s2", created="2020-01-10T00:00:00+00:00"),
    ]

    async def seed():
        await db.users.insert_many(users)
        await db.orders.insert_many(orders)

    import asyncio
    asyncio.run(seed())
    c = TestClient(server.app)
    c.headers["Authorization"] = f"Bearer {server.create_token('admin', users[0])}"
    return c


def test_requires_admin(client):
    anon = TestClient(server.app)
    assert anon.get("/api/admin/analytics/overview").status_code == 401
    client.headers["Authorization"] = f"Bearer {server.create_token('r1', {'role': 'retailer'})}"
    assert client.get("/api/admin/analytics/overview").status_code == 403


@pytest.mark.parametrize("months", [6, 12])
def test_series_length_and_current_month(client, months):
    body = client.get("/api/admin/analytics/overview", params={"months": months}).json()
    assert len(body["series"]) == months
    assert body["series"][-1]["month"] == THIS
    assert body["series"][0]["month"] < body["series"][-1]["month"]


def test_monthly_aggregation(client):
    body = client.get("/api/admin/analytics/overview", params={"months": 6}).json()
    cur = body["series"][-1]
    # cancelled and external orders are excluded from GMV and fees
    assert cur["gmv"] == 600.0 and cur["revenue"] == 30.0
    assert (cur["delivered"], cur["in_progress"], cur["cancelled"]) == (1, 2, 1)
    assert cur["new_stores"] == 2 and cur["new_distributors"] == 1
    assert sum(r["gmv"] for r in body["series"][:-1]) == 0  # 2020 data is out of range


def test_daily_aggregation_uses_recorded_commission_amount(client):
    import asyncio
    asyncio.run(server.db.orders.insert_one(order(
        "o7", "Delivered", 100.0, 5.0, "r1", "s1", commission_amount=8.0,
    )))
    body = client.get("/api/admin/analytics/overview", params={"granularity": "daily", "days": 7}).json()
    assert len(body["series"]) == 7
    assert body["series"][-1]["month"] == NOW.strftime("%Y-%m-%d")
    assert body["series"][-1]["gmv"] == 700.0
    assert body["series"][-1]["revenue"] == 38.0


def test_summary_and_year_filter(client):
    s = client.get("/api/admin/analytics/overview", params={"months": 6}).json()["summary"]
    assert s["total_gmv"] == 600.0 and s["aov"] == 200.0 and s["mrr"] == 5.0
    assert s["users_total"] == 4 and s["users_active"] == 2  # r1 and s1 ordered recently; r2 only cancelled/old
    assert s["active_pct"] == 50.0 and s["inactive_pct"] == 50.0
    old = client.get("/api/admin/analytics/overview", params={"year": 2020}).json()
    assert len(old["series"]) == 12
    jan = old["series"][0]
    assert jan["gmv"] == 400.0 and jan["delivered"] == 1 and jan["new_distributors"] == 1


def test_explicit_admin_date_range_filters_daily_gmv(client):
    response = client.get("/api/admin/analytics/overview", params={
        "granularity": "daily", "start_date": "2020-01-01", "end_date": "2020-01-31",
    })
    assert response.status_code == 200
    body = response.json()
    assert len(body["series"]) == 31
    assert sum(item["gmv"] for item in body["series"]) == 400.0
    assert body["series"][9]["gmv"] == 400.0

    invalid = client.get("/api/admin/analytics/overview", params={
        "granularity": "daily", "start_date": "2020-02-01", "end_date": "2020-01-01",
    })
    assert invalid.status_code == 400


def test_admin_summary_includes_unpaid_invoice_debt(client):
    import asyncio
    asyncio.run(server.db.invoices.insert_one({"id": "inv-open", "status": "pending", "amount": 73.25}))
    body = client.get("/api/admin/analytics/overview", params={"months": 6}).json()
    assert body["summary"]["system_debt"] == 73.25
    assert body["summary"]["open_invoices"] == 1


def test_realtime_sync_new_order_and_user(client):
    import asyncio
    before = client.get("/api/admin/analytics/overview", params={"months": 6}).json()
    asyncio.run(server.db.orders.insert_one(order("o9", "Delivered", 50.0, 2.5, "r2", "s1")))
    asyncio.run(server.db.users.insert_one({"id": "r9", "role": "retailer", "created_at": NOW.isoformat()}))
    after = client.get("/api/admin/analytics/overview", params={"months": 6}).json()
    a, b = before["series"][-1], after["series"][-1]
    assert b["gmv"] == a["gmv"] + 50.0 and b["delivered"] == a["delivered"] + 1
    assert b["new_stores"] == a["new_stores"] + 1
    assert after["summary"]["users_total"] == before["summary"]["users_total"] + 1
    assert after["summary"]["users_active"] == before["summary"]["users_active"] + 1  # r2 became active
