# Production Security Setup

## Required Environment

Set `APP_ENV=production`. Startup validates these settings and fails before serving requests when they are missing or invalid:

- `MONGO_URL`, `DB_NAME`, and `MONGO_TLS=true`
- `CORS_ORIGINS` as a comma-separated list of explicit HTTPS origins and `APP_BASE_URL` as the public HTTPS frontend origin
- `MONGO_AUDIT_URL` and `AUDIT_DB_NAME` for the isolated audit database
- `FIELD_ENCRYPTION_KEY`, a URL-safe base64-encoded 32-byte AES-256 key
- `RESEND_API_KEY` for transactional email delivery. `onboarding@resend.dev` is suitable for testing only; verify a sending domain before production use.
- `WEBHOOK_ALLOWED_IPS`, a comma-separated list of canonical CIDR ranges. Do not use `0.0.0.0/0` or `::/0`.
- `BANK_WEBHOOK_SECRET` and `INVOICE_WEBHOOK_SECRET`, each at least 32 bytes
- `JWT_SECRET`, at least 32 bytes

Generate a key outside the application and inject it from a KMS/secrets manager; do not commit it or put it in MongoDB:

```powershell
python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Keep the encryption key stable and backed up independently of the database. The current ciphertext format is versioned (`enc:v1:`) and authenticated with AES-256-GCM. Key rotation requires a planned decrypt-and-reencrypt migration while both old and new keys are available; replacing the key in place makes existing ciphertext unreadable.

## Field Encryption

The API encrypts IBANs before storing supplier profiles, historical order bank snapshots, invoice issuer details, settings, and platform split snapshots. Saved-card last four digits and expiration metadata are encrypted as well. Values are decrypted only for authenticated profile/admin views, invoice PDF/email, and payment workflows that require them. Startup performs an idempotent migration of legacy plaintext fields when `FIELD_ENCRYPTION_KEY` is configured. Back up the database before deploying this migration and verify the encrypted fields before removing old backups under the organization's retention policy.

Payment-card PAN and CVC are not persisted by the application. Sandbox tokens are removed from saved-card documents; production card payments should use provider-hosted tokenization.

## Append-Only MongoDB Audit Role

Use a dedicated database and MongoDB user for audit events. Create the collections as a database administrator, then create a custom role with only `find` and `insert`. Do not grant `readWrite`, `dbOwner`, update, or remove permissions on the audit database to the audit application user.

```javascript
use distro_audit

db.createCollection("financial_audit_logs")
db.createCollection("connection_audit_logs")
db.financial_audit_logs.createIndex({ at: -1 })
db.financial_audit_logs.createIndex({ status: 1, at: -1 })
db.financial_audit_logs.createIndex({ entity_id: 1 })
db.connection_audit_logs.createIndex({ at: -1 })

db.createRole({
  role: "auditAppendRead",
  privileges: [
    {
      resource: { db: "distro_audit", collection: "financial_audit_logs" },
      actions: ["find", "insert"]
    },
    {
      resource: { db: "distro_audit", collection: "connection_audit_logs" },
      actions: ["find", "insert"]
    }
  ],
  roles: []
})

db.createUser({
  user: "distro_audit_writer",
  pwd: passwordPrompt(),
  roles: [{ role: "auditAppendRead", db: "distro_audit" }]
})
```

Set `MONGO_AUDIT_URL` to this user's TLS connection string and `AUDIT_DB_NAME=distro_audit`. Before switching the app, copy existing `financial_audit_logs` and `connection_audit_logs` into this database with a one-time migration using a database administrator account, preserve document `_id` values, and verify counts. The normal application Mongo user must not have privileges on `distro_audit`.

The Python `AppendOnlyCollection` facade also rejects update/delete operations and write stages such as `$out`/`$merge`; the MongoDB role is the actual enforcement boundary if application code is bypassed.

For MongoDB Atlas, add only the backend's stable egress IP/CIDR to Network Access. Do not use `0.0.0.0/0`. `WEBHOOK_ALLOWED_IPS` is a separate inbound webhook control and must be populated with the provider's documented source CIDRs.

## Test Execution

Do not run integration tests against production credentials or a production database. Use an isolated test Mongo database and test gateway credentials. Run deterministic unit/API tests first, then the live-service integration tests separately:

```powershell
python -m pytest tests/test_security.py tests/test_admin_broadcast.py tests/test_invoice_webhook.py tests/test_financial_audit.py -q -p no:cacheprovider
python -m pytest tests/test_payments_checkout.py tests/test_payment_method.py -q -n 0 --tb=short
```

The repository's `pytest.ini` pins two xdist workers for the full suite because generated/live-backend tests share state; do not change its configured `addopts`. The focused integration command uses `-n 0` to avoid concurrent state changes within those selected modules. Keep HTTP calls bounded by explicit `requests`/`httpx` timeouts, use a separate test backend, and split long integration suites into smaller CI jobs with per-job timeouts rather than increasing a single global timeout indefinitely.
