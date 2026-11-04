import copy
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class MemoryUsers:
    def __init__(self, user=None):
        self.user = copy.deepcopy(user)

    async def find_one(self, query, projection=None):
        if self.user and self.user.get("email") == query.get("email"):
            return {key: self.user[key] for key in ("id", "email", "name") if key in self.user}
        return None

    async def update_one(self, query, update):
        if self.user and self.user.get("id") == query.get("id"):
            self.user.update(copy.deepcopy(update.get("$set", {})))
            return type("Result", (), {"matched_count": 1})()
        return type("Result", (), {"matched_count": 0})()


class MemoryPasswordResets:
    def __init__(self):
        self.rows = []

    async def find_one(self, query, projection=None):
        for row in self.rows:
            if row.get("email") != query.get("email"):
                continue
            cutoff = query.get("created_at", {}).get("$gt")
            if cutoff and row["created_at"] <= cutoff:
                continue
            return copy.deepcopy(row)
        return None

    async def find_one_and_delete(self, query):
        for index, row in enumerate(self.rows):
            if row["email"] != query["email"] or row["code_hash"] != query["code_hash"]:
                continue
            if row["expires_at"] <= query["expires_at"]["$gt"] or row.get("attempts", 0) >= 5:
                continue
            return self.rows.pop(index)
        return None

    async def insert_one(self, row):
        self.rows.append(copy.deepcopy(row))

    async def delete_one(self, query):
        self.rows = [row for row in self.rows if not all(row.get(key) == value for key, value in query.items())]

    async def delete_many(self, query):
        self.rows = [row for row in self.rows if not all(row.get(key) == value for key, value in query.items())]

    async def update_one(self, query, update):
        for row in self.rows:
            if row.get("email") != query.get("email") or row.get("code_hash") != query.get("code_hash"):
                continue
            if row["expires_at"] <= query["expires_at"]["$gt"]:
                continue
            row["attempts"] = row.get("attempts", 0) + update.get("$inc", {}).get("attempts", 0)
            return


def test_password_recovery_is_generic_hashed_and_single_use(monkeypatch, capsys):
    user = {"id": "reset-user", "email": "reset@example.com", "name": "Reset User", "password_hash": server.hash_password("OriginalPass123")}
    users = MemoryUsers(user)
    resets = MemoryPasswordResets()
    monkeypatch.setattr(server, "db", type("MemoryDB", (), {"users": users, "password_resets": resets})())
    sent_emails = []

    async def send_email(**kwargs):
        sent_emails.append(kwargs)
        return True

    monkeypatch.setattr(server, "try_send_email", send_email)
    monkeypatch.setenv("APP_ENV", "test")
    client = TestClient(server.app)

    known = client.post("/api/forgot-password", json={"email": user["email"]})
    unknown = client.post("/api/forgot-password", json={"email": "missing@example.com"})
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()
    assert len(sent_emails) == 1
    code = re.search(r">(\d{6})</span>", sent_emails[0]["html"]).group(1)
    assert resets.rows[0]["code_hash"] == server.hash_otp(code)
    assert code not in resets.rows[0]["code_hash"]
    assert code in capsys.readouterr().out

    reset = client.post("/api/reset-password", json={"email": user["email"], "code": code, "password": "NewSecurePass123"})
    assert reset.status_code == 200
    assert server.verify_password("NewSecurePass123", users.user["password_hash"])
    assert client.post("/api/reset-password", json={"email": user["email"], "code": code, "password": "AnotherPass123"}).status_code == 400


def test_expired_password_reset_code_is_rejected(monkeypatch):
    users = MemoryUsers({"id": "reset-user", "email": "reset@example.com", "password_hash": server.hash_password("OriginalPass123")})
    resets = MemoryPasswordResets()
    code = "123456"
    resets.rows.append({
        "user_id": "reset-user", "email": "reset@example.com", "code_hash": server.hash_otp(code),
        "expires_at": datetime.now(timezone.utc) - timedelta(minutes=1),
        "created_at": datetime.now(timezone.utc) - timedelta(minutes=11), "attempts": 0,
    })
    monkeypatch.setattr(server, "db", type("MemoryDB", (), {"users": users, "password_resets": resets})())
    response = TestClient(server.app).post(
        "/api/reset-password", json={"email": "reset@example.com", "code": code, "password": "NewSecurePass123"},
    )
    assert response.status_code == 400
    assert server.verify_password("OriginalPass123", users.user["password_hash"])


def test_password_reset_code_locks_after_five_invalid_attempts(monkeypatch):
    user = {"id": "reset-user", "email": "reset@example.com", "name": "Reset User", "password_hash": server.hash_password("OriginalPass123")}
    users = MemoryUsers(user)
    resets = MemoryPasswordResets()
    monkeypatch.setattr(server, "db", type("MemoryDB", (), {"users": users, "password_resets": resets})())

    async def send_email(**kwargs):
        return True

    monkeypatch.setattr(server, "try_send_email", send_email)
    monkeypatch.setenv("APP_ENV", "test")
    client = TestClient(server.app)
    client.post("/api/forgot-password", json={"email": user["email"]})

    for _ in range(5):
        response = client.post("/api/reset-password", json={
            "email": user["email"], "code": "000000", "password": "NewSecurePass123",
        })
        assert response.status_code == 400
    assert resets.rows == []