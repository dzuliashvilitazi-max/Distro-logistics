import asyncio
import base64

from mongomock_motor import AsyncMongoMockClient

import server


def test_legacy_sensitive_fields_are_migrated_before_startup(monkeypatch):
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"m" * 32).decode())
    database = AsyncMongoMockClient()["sensitive_migration_test"]

    async def seed_and_migrate():
        await database.users.insert_one({
            "id": "supplier-1", "iban": "GE29000000000000000000",
            "bank_accounts": [{"iban": "GE29000000000000000001"}],
            "card_last4": "4242", "card_expiry": "12/30",
            "payment_cards": [{"last4": "1234", "exp": "01/29", "token": "old-token"}],
            "card_token": "legacy-token",
        })
        await database.orders.insert_one({
            "id": "order-1", "bank_account_snapshot": {"iban": "GE29000000000000000002"},
            "platform_split": {"platform_iban": "GE29000000000000000003"},
        })
        await database.settings.insert_one({"id": "platform", "issuer_iban": "GE29000000000000000004"})
        await database.invoices.insert_one({"id": "invoice-1", "issuer_iban": "GE29000000000000000005"})
        monkeypatch.setattr(server, "db", database)
        await server.migrate_sensitive_fields()
        await server.remove_plaintext_card_tokens()
        user = await database.users.find_one({"id": "supplier-1"})
        order = await database.orders.find_one({"id": "order-1"})
        settings = await database.settings.find_one({"id": "platform"})
        invoice = await database.invoices.find_one({"id": "invoice-1"})
        return user, order, settings, invoice

    user, order, settings, invoice = asyncio.run(seed_and_migrate())

    assert user["iban"].startswith("enc:v1:")
    assert user["bank_accounts"][0]["iban"].startswith("enc:v1:")
    assert user["card_last4"].startswith("enc:v1:")
    assert user["payment_cards"][0]["last4"].startswith("enc:v1:")
    assert "token" not in user["payment_cards"][0]
    assert "card_token" not in user
    assert order["bank_account_snapshot"]["iban"].startswith("enc:v1:")
    assert order["platform_split"]["platform_iban"].startswith("enc:v1:")
    assert settings["issuer_iban"].startswith("enc:v1:")
    assert invoice["issuer_iban"].startswith("enc:v1:")


def test_public_user_serializer_never_exposes_password_or_payment_tokens(monkeypatch):
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"u" * 32).decode())
    stored = server.safeguards.transform_iban_fields({
        "id": "supplier-1", "iban": "GE29000000000000000000", "card_last4": "4242",
        "card_token": "secret-token", "payment_cards": [{"token": "nested-secret"}],
        "password_hash": "password-hash", "_id": "mongo-id",
    }, encrypt=True)

    public = server.public_user_document(stored)

    assert public["iban"] == "GE29000000000000000000"
    assert public["card_last4"] == "4242"
    assert "password_hash" not in public and "card_token" not in public
    assert "payment_cards" not in public and "_id" not in public