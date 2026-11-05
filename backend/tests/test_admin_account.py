import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import seed
import server

EMAIL = "distrologistics1@gmail.com"
PASSWORD = "Test-only-Passw0rd!"


class Users:
    def __init__(self, rows=None):
        self.rows = rows or []

    async def find_one(self, query, projection=None):
        for row in self.rows:
            if all(row.get(k) == v for k, v in query.items()):
                return dict(row)  # copy, like a real driver
        return None

    async def insert_one(self, doc):
        self.rows.append(dict(doc))

    async def update_one(self, query, update):
        row = next(r for r in self.rows if all(r.get(k) == v for k, v in query.items()))
        row.update(update.get("$set", {}))

    async def delete_one(self, query):
        original_count = len(self.rows)
        self.rows[:] = [r for r in self.rows if not all(r.get(k) == v for k, v in query.items())]
        return SimpleNamespace(deleted_count=original_count - len(self.rows))

    async def count_documents(self, query):
        return sum(all(row.get(k) == v for k, v in query.items()) for row in self.rows)


class FakeDB:
    def __init__(self, rows=None):
        self.users = Users(rows)


@pytest.fixture(autouse=True)
def admin_env(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", EMAIL)
    monkeypatch.setenv("ADMIN_PASSWORD", PASSWORD)


def ensure(db):
    return asyncio.run(seed.ensure_admin_account(db, server.hash_password, server.verify_password))


def login(monkeypatch, db, password=PASSWORD):
    monkeypatch.setattr(server, "db", db)
    return TestClient(server.app).post("/api/auth/login", json={"email": EMAIL, "password": password})


def test_admin_created_and_can_log_in(monkeypatch):
    db = FakeDB()
    assert ensure(db) == "created"
    res = login(monkeypatch, db)
    assert res.status_code == 200
    assert res.json()["user"]["role"] == "admin" and res.json()["token"]
    assert "password_hash" not in res.json()["user"]
    assert login(monkeypatch, db, "wrong").status_code == 401


def test_admin_can_delete_user_but_not_self(monkeypatch):
    db = FakeDB([
        {"id": "admin-1", "email": EMAIL, "role": "admin", "status": "active",
         "password_hash": server.hash_password(PASSWORD)},
        {"id": "retailer-1", "email": "retailer@example.com", "role": "retailer"},
    ])
    response = login(monkeypatch, db)
    assert response.status_code == 200
    client = TestClient(server.app)
    headers = {"Authorization": f"Bearer {response.json()['token']}"}

    deleted = client.delete("/api/admin/users/retailer-1", headers=headers)
    assert deleted.status_code == 200
    assert all(row["id"] != "retailer-1" for row in db.users.rows)

    self_delete = client.delete("/api/admin/users/admin-1", headers=headers)
    assert self_delete.status_code == 400
    assert any(row["id"] == "admin-1" for row in db.users.rows)


def test_existing_account_is_promoted_and_repaired(monkeypatch):
    db = FakeDB([{"id": "u1", "email": EMAIL, "role": "retailer", "status": "suspended",
                  "email_verified": False, "password_hash": server.hash_password("old-password")}])
    assert ensure(db) == "updated"
    row = db.users.rows[0]
    assert row["role"] == "admin" and row["status"] == "active" and row["email_verified"] is True
    assert login(monkeypatch, db).status_code == 200
    assert ensure(db) == "ok"  # idempotent: nothing to change on the next startup


def test_skipped_without_credentials(monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD")
    db = FakeDB()
    assert ensure(db) is None and db.users.rows == []


def _match(doc, q):
    import re
    for k, v in q.items():
        if k == "$or":
            if not any(_match(doc, s) for s in v):
                return False
        elif k == "$and":
            if not all(_match(doc, s) for s in v):
                return False
        elif isinstance(v, dict):
            val = doc.get(k)
            if "$in" in v and val not in v["$in"]:
                return False
            if "$ne" in v and val == v["$ne"]:
                return False
            if "$regex" in v and not re.search(v["$regex"], val or "", re.I):
                return False
        elif doc.get(k) != v:
            return False
    return True


class Coll:
    def __init__(self, rows):
        self.rows = rows

    def find(self, query, projection=None):
        found = [dict(r) for r in self.rows if _match(r, query)]

        class Cursor:
            async def to_list(self, n):
                return found
        return Cursor()

    async def delete_many(self, query):
        self.rows[:] = [r for r in self.rows if not _match(r, query)]


class PurgeDB:
    def __init__(self):
        self.users = Coll([
            {"id": "a", "email": EMAIL, "role": "admin"},
            {"id": "d", "email": "metro@distro.com", "role": "supplier"},
            {"id": "o", "email": "mgv67mk2j5@privaterelay.appleid.com", "role": "admin"},
            {"id": "t", "email": "TEST_ret_1@distro.com", "role": "retailer"},
            {"id": "r", "email": "real@shop.ge", "role": "retailer"},
        ])
        self.orders = Coll([{"id": "1", "supplier_id": "d", "retailer_id": "r"}, {"id": "2", "supplier_id": "x", "retailer_id": "r"}])

    def __getitem__(self, name):
        if not hasattr(self, name):
            setattr(self, name, Coll([]))
        return getattr(self, name)


def test_demo_accounts_are_purged_but_admin_and_real_users_stay():
    db = PurgeDB()
    assert asyncio.run(seed.purge_demo_accounts(db)) == 3
    assert sorted(u["email"] for u in db.users.rows) == [EMAIL, "real@shop.ge"]
    assert [o["id"] for o in db.orders.rows] == ["2"]
