import base64

import pytest

import security


KEY = base64.urlsafe_b64encode(b"k" * 32).decode("ascii")


def test_field_encryption_round_trips_and_binds_field(monkeypatch):
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", KEY)
    encrypted = security.encrypt_iban("GE29000000000000000000")

    assert encrypted.startswith("enc:v1:")
    assert "GE29000000000000000000" not in encrypted
    assert security.decrypt_iban(encrypted) == "GE29000000000000000000"
    with pytest.raises(RuntimeError, match="Could not decrypt"):
        security.decrypt_field(encrypted, "another-field")


def test_transform_encrypts_nested_iban_fields(monkeypatch):
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", KEY)
    original = {
        "iban": "GE29000000000000000000",
        "bank_accounts": [{"iban": "GE29000000000000000001"}],
        "bank_account_snapshot": {"iban": "GE29000000000000000002"},
        "platform_split": {"platform_iban": "GE29000000000000000003"},
        "issuer_iban": "GE29000000000000000004",
        "card_last4": "4242", "card_expiry": "12/30",
        "payment_cards": [{"last4": "1234", "exp": "01/29", "brand": "visa"}],
    }

    encrypted = security.transform_iban_fields(original, encrypt=True)
    assert encrypted["iban"].startswith("enc:v1:")
    assert encrypted["bank_accounts"][0]["iban"].startswith("enc:v1:")
    assert encrypted["bank_account_snapshot"]["iban"].startswith("enc:v1:")
    assert encrypted["platform_split"]["platform_iban"].startswith("enc:v1:")
    assert encrypted["issuer_iban"].startswith("enc:v1:")
    assert encrypted["card_last4"].startswith("enc:v1:")
    assert encrypted["card_expiry"].startswith("enc:v1:")
    assert encrypted["payment_cards"][0]["last4"].startswith("enc:v1:")
    assert encrypted["payment_cards"][0]["exp"].startswith("enc:v1:")
    assert security.transform_iban_fields(encrypted, encrypt=False) == original


def test_production_config_requires_tls_secrets_and_cidrs():
    with pytest.raises(RuntimeError, match="Missing required production settings"):
        security.validate_production_environment({"APP_ENV": "production"})

    env = {
        "APP_ENV": "production", "MONGO_URL": "mongodb+srv://user:pass@cluster/db",
        "MONGO_AUDIT_URL": "mongodb+srv://audit:pass@cluster/audit", "DB_NAME": "distro",
        "MONGO_TLS": "true", "JWT_SECRET": "j" * 32, "FIELD_ENCRYPTION_KEY": KEY,
        "RESEND_API_KEY": "re_test_key",
        "CORS_ORIGINS": "https://app.example", "APP_BASE_URL": "https://app.example",
        "WEBHOOK_ALLOWED_IPS": "203.0.113.10/32", "BANK_WEBHOOK_SECRET": "b" * 32,
        "INVOICE_WEBHOOK_SECRET": "i" * 32,
    }
    security.validate_production_environment(env)

    env["WEBHOOK_ALLOWED_IPS"] = "0.0.0.0/0"
    with pytest.raises(RuntimeError, match="unrestricted /0"):
        security.validate_production_environment(env)


def test_missing_app_env_fails_closed():
    with pytest.raises(RuntimeError, match="APP_ENV must be explicitly"):
        security.validate_production_environment({})
    security.validate_production_environment({"APP_ENV": "test"})
    with pytest.raises(RuntimeError, match="APP_ENV must be explicitly"):
        security.validate_production_environment({"APP_ENV": "staging"})


def test_production_cors_requires_explicit_https_origins():
    assert security.parse_cors_origins({"APP_ENV": "development"}) == ["*"]
    assert security.parse_cors_origins({"APP_ENV": "production", "CORS_ORIGINS": "https://app.example"}) == [
        "https://app.example",
    ]
    assert security.parse_cors_origins({
        "APP_ENV": "production",
        "CORS_ORIGINS": "https://distrologistics.ge,https://www.distrologistics.ge",
    }) == ["https://distrologistics.ge", "https://www.distrologistics.ge"]
    with pytest.raises(RuntimeError, match="explicit HTTPS"):
        security.parse_cors_origins({"APP_ENV": "production", "CORS_ORIGINS": "*"})