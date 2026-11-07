import copy
import asyncio
import re
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


def matches(document, query):
    for key, expected in query.items():
        if key == "$or":
            if not any(matches(document, branch) for branch in expected):
                return False
            continue
        value = document.get(key)
        if isinstance(expected, dict):
            if "$in" in expected and value not in expected["$in"]:
                return False
            if "$ne" in expected and value == expected["$ne"]:
                return False
            if "$regex" in expected:
                flags = re.IGNORECASE if expected.get("$options") == "i" else 0
                if not re.search(expected["$regex"], str(value or ""), flags):
                    return False
        elif value != expected:
            return False
    return True


class MemoryCursor:
    def __init__(self, rows):
        self.rows = rows

    def __aiter__(self):
        self.index = 0
        return self

    async def __anext__(self):
        if self.index >= len(self.rows):
            raise StopAsyncIteration
        row = copy.deepcopy(self.rows[self.index])
        self.index += 1
        return row

    def sort(self, field, direction=1):
        self.rows.sort(key=lambda row: row.get(field, ""), reverse=direction < 0)
        return self

    async def to_list(self, limit):
        return copy.deepcopy(self.rows[:limit])


class MemoryCollection:
    def __init__(self, rows=()):
        self.rows = [copy.deepcopy(row) for row in rows]

    def find(self, query, projection=None):
        rows = [row for row in self.rows if matches(row, query)]
        if projection and projection.get("_id") == 0:
            fields = {key for key, included in projection.items() if included == 1}
            if fields:
                rows = [{key: value for key, value in row.items() if key in fields} for row in rows]
            else:
                rows = [{key: value for key, value in row.items() if key not in projection} for row in rows]
        return MemoryCursor(rows)

    async def find_one(self, query, projection=None):
        rows = await self.find(query, projection).to_list(1)
        return rows[0] if rows else None

    async def update_one(self, query, update, upsert=False):
        for row in self.rows:
            if matches(row, query):
                row.update(copy.deepcopy(update.get("$set", {})))
                for key, value in update.get("$push", {}).items():
                    row.setdefault(key, []).append(copy.deepcopy(value))
                return
        if upsert:
            self.rows.append({
                **copy.deepcopy(query),
                **copy.deepcopy(update.get("$setOnInsert", {})),
                **copy.deepcopy(update.get("$set", {})),
            })

    async def insert_one(self, document):
        self.rows.append(copy.deepcopy(document))


class EmptyOrders:
    def find(self, query, projection=None):
        return MemoryCursor([])


def setup_contact_test(monkeypatch):
    owner = {"id": "supplier-1", "role": "supplier", "business_name": "Supplier"}
    users = MemoryCollection([
        {"id": "retailer-1", "role": "retailer", "status": "active", "business_name": "Corner Store", "phone": "+995555000001"},
        {"id": "supplier-2", "role": "supplier", "status": "active", "business_name": "North Distributor", "phone": "+995555000002"},
        {"id": "supplier-1", "role": "supplier", "status": "active", "business_name": "Supplier"},
    ])
    drivers = MemoryCollection([
        {"id": "driver-1", "supplier_id": "supplier-1", "name": "Jemali", "phone": "+995555000003"},
    ])
    saved_contacts = MemoryCollection()
    messages = MemoryCollection()
    monkeypatch.setattr(server, "db", type("MemoryDB", (), {
        "users": users,
        "drivers": drivers,
        "orders": EmptyOrders(),
        "saved_contacts": saved_contacts,
        "messages": messages,
        "terms_acceptances": MemoryCollection(),
        "support_tickets": MemoryCollection(),
        "notifications": MemoryCollection(),
    })())
    server.app.dependency_overrides[server.get_current_user] = lambda: owner
    return TestClient(server.app), owner


def test_contact_search_returns_registered_accounts_and_owned_drivers(monkeypatch):
    client, owner = setup_contact_test(monkeypatch)
    try:
        response = client.get("/api/contacts/search", params={"query": "995555000003"})
        assert response.status_code == 200
        assert response.json() == [{
            "id": "driver-1",
            "name": "Jemali",
            "phone": "+995555000003",
            "role": "driver",
            "kind": "driver",
            "is_registered": False,
        }]

        response = client.get("/api/contacts/search", params={"query": "Corner"})
        assert response.status_code == 200
        assert response.json()[0]["id"] == "retailer-1"
        assert response.json()[0]["is_registered"] is True
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_manual_contact_is_saved_and_returned_in_contact_list(monkeypatch):
    client, owner = setup_contact_test(monkeypatch)
    try:
        response = client.post("/api/contacts", json={
            "name": "After Hours Store",
            "phone": "+995555000004",
            "role": "store",
        })
        assert response.status_code == 200
        contact = response.json()
        assert contact["is_external_contact"] is True
        assert contact["role"] == "store"

        response = client.get("/api/contacts")
        assert response.status_code == 200
        assert any(item["id"] == contact["id"] and item["phone"] == "+995555000004" for item in response.json())
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_registered_contact_and_owned_driver_are_saved_with_correct_chat_modes(monkeypatch):
    client, owner = setup_contact_test(monkeypatch)
    try:
        registered = client.post("/api/contacts", json={
            "contact_id": "retailer-1",
            "name": "Corner Store",
            "role": "retailer",
            "kind": "registered",
        })
        assert registered.status_code == 200
        assert registered.json()["is_external_contact"] is False

        driver = client.post("/api/contacts", json={
            "contact_id": "driver-1",
            "name": "Jemali",
            "role": "driver",
            "kind": "driver",
        })
        assert driver.status_code == 200
        assert driver.json()["is_external_contact"] is True
        assert driver.json()["phone"] == "+995555000003"
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_registration_adds_admin_to_new_account_contacts(monkeypatch):
    client, owner = setup_contact_test(monkeypatch)
    admin = {
        "id": "admin-1", "role": "admin", "status": "active",
        "name": "Platform Admin", "business_name": "Distro Admin", "phone": "+995555000005",
    }
    server.db.users.rows.append(admin)

    async def no_op_issue_otp(*args, **kwargs):
        return None

    monkeypatch.setattr(server, "is_disposable_email", lambda email: False)
    monkeypatch.setattr(server, "issue_otp", no_op_issue_otp)
    try:
        response = client.post("/api/auth/register", json={
            "email": "new-user@example.com",
            "password": "valid-password-123",
            "name": "New User",
            "role": "retailer",
            "phone": "+995555000006",
            "identification_number": "12345678901",
            "vat_registered": False,
            "accept_terms": True,
        })
        assert response.status_code == 200
        new_user = next(row for row in server.db.users.rows if row.get("email") == "new-user@example.com")

        saved = server.db.saved_contacts.rows
        assert any(
            item["owner_id"] == new_user["id"] and item["contact_id"] == "admin-1"
            and item["kind"] == "registered" for item in saved
        )
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_startup_backfill_adds_admin_to_existing_users_idempotently(monkeypatch):
    client, owner = setup_contact_test(monkeypatch)
    server.db.users.rows.append({
        "id": "admin-1", "role": "admin", "status": "active",
        "name": "Platform Admin", "business_name": "Distro Admin",
    })
    try:
        asyncio.run(server.backfill_existing_admin_contacts())
        asyncio.run(server.backfill_existing_admin_contacts())

        for existing_user in server.db.users.rows:
            if existing_user["id"] == "admin-1":
                continue
            assert sum(
                contact["owner_id"] == existing_user["id"] and contact["contact_id"] == "admin-1"
                for contact in server.db.saved_contacts.rows
            ) == 1
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_message_from_unknown_contact_is_stored_and_creates_chat(monkeypatch):
    client, owner = setup_contact_test(monkeypatch)
    pushes = []
    monkeypatch.setattr(server.web_push, "schedule", lambda _db, notification: pushes.append(notification))
    try:
        response = client.post("/api/messages", json={"to_id": "retailer-1", "text": "Hello"})
        assert response.status_code == 200
        assert response.json()["text"] == "Hello"
        assert len(server.db.messages.rows) == 1
        assert any(
            item["owner_id"] == "retailer-1" and item["contact_id"] == owner["id"]
            for item in server.db.saved_contacts.rows
        )
        assert any(
            item["owner_id"] == owner["id"] and item["contact_id"] == "retailer-1"
            for item in server.db.saved_contacts.rows
        )
        assert [(item["user_id"], item["type"]) for item in pushes] == [("retailer-1", "message")]
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_support_ticket_is_saved_and_opens_admin_chat(monkeypatch):
    client, owner = setup_contact_test(monkeypatch)
    admin = {
        "id": "admin-1", "role": "admin", "status": "active",
        "name": "Platform Admin", "business_name": "Distro Admin", "phone": "+995555000005",
    }
    server.db.users.rows.append(admin)

    pushes = []
    monkeypatch.setattr(server.web_push, "schedule", lambda _db, notification: pushes.append(notification))
    try:
        response = client.post("/api/support/tickets", json={"message": "Please help me"})

        assert response.status_code == 200
        assert response.json()["admin_id"] == "admin-1"
        assert server.db.support_tickets.rows[0]["message"] == "Please help me"
        assert server.db.messages.rows[0]["from_id"] == owner["id"]
        assert server.db.messages.rows[0]["to_id"] == "admin-1"
        assert server.db.messages.rows[0]["text"] == "Please help me"
        assert any(
            item["owner_id"] == owner["id"] and item["contact_id"] == "admin-1"
            for item in server.db.saved_contacts.rows
        )
        assert [(item["user_id"], item["type"]) for item in pushes] == [("admin-1", "support")]
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)


def test_admin_support_reply_pushes_ticket_owner(monkeypatch):
    client, _owner = setup_contact_test(monkeypatch)
    admin = {"id": "admin-1", "role": "admin", "name": "Admin"}
    server.app.dependency_overrides[server.get_current_user] = lambda: admin
    server.db.support_tickets.rows.append({
        "id": "ticket-1", "user_id": "retailer-1", "status": "open", "replies": [],
    })
    pushes = []
    monkeypatch.setattr(server.web_push, "schedule", lambda _db, notification: pushes.append(notification))
    try:
        response = client.post("/api/admin/support/tickets/ticket-1/reply", json={"reply": "We are looking into it."})

        assert response.status_code == 200
        assert [(item["user_id"], item["type"]) for item in pushes] == [("retailer-1", "support")]
        assert server.db.support_tickets.rows[0]["replies"][0]["text"] == "We are looking into it."
    finally:
        server.app.dependency_overrides.pop(server.get_current_user, None)
