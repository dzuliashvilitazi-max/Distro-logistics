"""Security primitives: secret redaction, append-only audit access, webhook replay protection,
idempotency keys, IP allowlists and hardened MongoDB client options."""
import hashlib
import ipaddress
import json
import logging
import os
import re
import base64
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import urlsplit

from fastapi import HTTPException

try:
    from pymongo.errors import DuplicateKeyError
except ImportError:  # pragma: no cover
    class DuplicateKeyError(Exception):
        pass

# ---------- redaction ----------
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_BEARER_RE = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
_MONGO_URI_RE = re.compile(r"(mongodb(?:\+srv)?://)[^:@/\s]+:[^@/\s]+@")
_SENSITIVE_KEYS = ("password", "secret", "token", "api_key", "apikey", "authorization", "cvc", "cvv",
                   "card_number", "private_key")
_IBAN_KEYS = ("iban",)


def mask_iban(value: str) -> str:
    compact = re.sub(r"\s+", "", str(value))
    return compact if len(compact) < 9 else f"{compact[:4]}{'•' * (len(compact) - 8)}{compact[-4:]}"


def _luhn(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _mask_card_match(match: re.Match) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    return f"••••{digits[-4:]}" if 13 <= len(digits) <= 19 and _luhn(digits) else match.group(0)


def redact_text(text: str) -> str:
    text = _MONGO_URI_RE.sub(r"\1***:***@", text)
    text = _BEARER_RE.sub(lambda m: f"{m.group(1)} [REDACTED]", text)
    text = _IBAN_RE.sub(lambda m: mask_iban(m.group(0)), text)
    return _CARD_RE.sub(_mask_card_match, text)


def redact(value: Any, key: str = "") -> Any:
    """Deep copy with IBANs masked and card/secret/token fields removed; safe for logs and audit records."""
    lowered = key.lower()
    if lowered and any(k in lowered for k in _IBAN_KEYS) and isinstance(value, str):
        return mask_iban(value)
    if lowered and any(k in lowered for k in _SENSITIVE_KEYS) and value not in (None, "", False):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {k: redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, key) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


class RedactingFilter(logging.Filter):
    """Scrubs IBANs, card numbers, bearer tokens and database credentials from every log line."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_text(record.getMessage())
        record.args = ()
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact_text(record.exc_text)
        return True


def install_log_redaction() -> None:
    log_filter = RedactingFilter()
    root = logging.getLogger()
    for handler in root.handlers:
        handler.addFilter(log_filter)


# ---------- append-only audit access ----------
class AuditImmutableError(RuntimeError):
    pass


class AppendOnlyCollection:
    """Audit collection facade: insert and read only. Update/delete/drop raise, aggregate may not write."""

    _READ = {"find", "find_one", "count_documents", "distinct", "create_index"}

    def __init__(self, resolve: Callable[[], Any]):
        self._resolve = resolve

    async def insert_one(self, document: dict):
        return await self._resolve().insert_one(redact(document))

    def aggregate(self, pipeline, *args, **kwargs):
        if any(isinstance(stage, dict) and ({"$out", "$merge"} & stage.keys()) for stage in pipeline):
            raise AuditImmutableError("Audit logs are append-only.")
        return self._resolve().aggregate(pipeline, *args, **kwargs)

    def __getattr__(self, name: str):
        if name in self._READ:
            return getattr(self._resolve(), name)
        raise AuditImmutableError(f"Audit logs are append-only; '{name}' is not permitted.")


# ---------- webhook replay protection ----------
def webhook_event_key(source: str, event_id: Optional[str], raw_body: bytes) -> str:
    """Provider event id when present, otherwise a digest of the exact payload."""
    basis = event_id.strip() if isinstance(event_id, str) and event_id.strip() else hashlib.sha256(raw_body).hexdigest()
    return f"{source}:{basis}"


async def claim_webhook_event(collection, key: str) -> bool:
    """True the first time an event is seen; False for a replay. Unique index on _id makes this atomic."""
    if collection is None:
        return True
    try:
        await collection.insert_one({"_id": key, "received_at": datetime.now(timezone.utc)})
    except DuplicateKeyError:
        return False
    return True


async def release_webhook_event(collection, key: str) -> None:
    """Allow the provider to retry after a processing failure."""
    if collection is not None:
        await collection.delete_one({"_id": key})


# ---------- idempotency keys ----------
_IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9_\-:.]{8,128}$")


async def run_idempotent(collection, scope: str, key: Optional[str], payload: Any,
                         handler: Callable[[], Awaitable[Any]]):
    """Run handler once per (scope, key); replays return the stored response, mismatched payloads are rejected."""
    if not key:
        return await handler()
    if not _IDEMPOTENCY_KEY_RE.match(key):
        raise HTTPException(400, "Idempotency-Key must be 8-128 characters: letters, digits, _ - : .")
    if collection is None:
        return await handler()
    record_id = f"{scope}:{key}"
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    try:
        await collection.insert_one({"_id": record_id, "fingerprint": fingerprint, "state": "in_progress",
                                     "created_at": datetime.now(timezone.utc)})
    except DuplicateKeyError:
        record = await collection.find_one({"_id": record_id})
        if not record or record.get("fingerprint") != fingerprint:
            raise HTTPException(422, "Idempotency-Key was already used with a different request.")
        if record.get("state") == "done":
            return record["response"]
        raise HTTPException(409, "A request with this Idempotency-Key is still being processed.")
    try:
        response = await handler()
    except BaseException:
        await collection.delete_one({"_id": record_id})
        raise
    await collection.update_one({"_id": record_id}, {"$set": {"state": "done", "response": response}})
    return response


# ---------- network controls ----------
def ip_allowed(host: Optional[str], allowlist: str) -> bool:
    """Empty allowlist means unrestricted; otherwise the caller must fall inside a listed IP/CIDR."""
    networks = []
    for item in (allowlist or "").split(","):
        if item.strip():
            networks.append(ipaddress.ip_network(item.strip(), strict=False))
    if not networks:
        return True
    try:
        address = ipaddress.ip_address(host or "")
    except ValueError:
        return False
    return any(address in network for network in networks)


def mongo_client_options(url: str, env: dict) -> dict:
    """Hardened MongoDB settings: TLS with certificate validation, majority writes, bounded timeouts."""
    is_local = bool(re.search(r"://(?:[^@/]*@)?(localhost|127\.0\.0\.1)(?:[:/,]|$)", url))
    tls_default = "false" if is_local else "true"
    tls = str(env.get("MONGO_TLS", tls_default)).strip().lower() != "false"
    production = str(env.get("APP_ENV", "")).strip().lower() == "production"
    if not is_local and not tls:
        raise RuntimeError("MONGO_TLS=false is not allowed for a remote MongoDB.")
    if not is_local and not re.search(r"://[^/@]+:[^/@]+@", url):
        raise RuntimeError("MONGO_URL must include credentials for a remote MongoDB (authentication is mandatory).")
    if production and is_local:
        raise RuntimeError("A local MongoDB is not allowed when APP_ENV=production.")
    options = {
        "serverSelectionTimeoutMS": int(env.get("MONGO_SELECTION_TIMEOUT_MS", "10000")),
        "connectTimeoutMS": 10000,
        "socketTimeoutMS": int(env.get("MONGO_SOCKET_TIMEOUT_MS", "25000")),
        "maxPoolSize": int(env.get("MONGO_MAX_POOL", "50")),
        "maxIdleTimeMS": int(env.get("MONGO_MAX_IDLE_MS", "60000")),
        "retryWrites": True, "retryReads": True,
        "w": "majority", "appname": "distro-logistics",
    }
    if tls:
        import certifi
        options.update(tls=True, tlsAllowInvalidCertificates=False, tlsAllowInvalidHostnames=False,
                       tlsCAFile=certifi.where())
    return options


# ---------- field-level encryption ----------
_ENCRYPTED_PREFIX = "enc:v1:"


def _field_encryption_key(env: Optional[dict] = None) -> bytes:
    source = os.environ if env is None else env
    value = source.get("FIELD_ENCRYPTION_KEY", "").strip()
    if not value:
        raise RuntimeError("FIELD_ENCRYPTION_KEY must be configured before storing sensitive fields.")
    try:
        key = base64.urlsafe_b64decode(value.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as error:
        raise RuntimeError("FIELD_ENCRYPTION_KEY must be a URL-safe base64-encoded 32-byte key.") from error
    if len(key) != 32:
        raise RuntimeError("FIELD_ENCRYPTION_KEY must be a URL-safe base64-encoded 32-byte key.")
    return key


def encrypt_field(value: Optional[str], field: str = "sensitive") -> Optional[str]:
    """AES-256-GCM encrypt a field using a key injected by a secrets manager/KMS."""
    if value in (None, "") or (isinstance(value, str) and value.startswith(_ENCRYPTED_PREFIX)):
        return value
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    aad = f"distro:{_ENCRYPTED_PREFIX}{field}".encode("utf-8")
    ciphertext = AESGCM(_field_encryption_key()).encrypt(nonce, str(value).encode("utf-8"), aad)
    encoded = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")
    return _ENCRYPTED_PREFIX + encoded


def decrypt_field(value: Optional[str], field: str = "sensitive") -> Optional[str]:
    """Decrypt an encrypted field; legacy plaintext is returned only to support migration reads."""
    if value in (None, "") or not (isinstance(value, str) and value.startswith(_ENCRYPTED_PREFIX)):
        return value
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.exceptions import InvalidTag

    try:
        raw = base64.urlsafe_b64decode(value[len(_ENCRYPTED_PREFIX):].encode("ascii"))
        nonce, ciphertext = raw[:12], raw[12:]
        aad = f"distro:{_ENCRYPTED_PREFIX}{field}".encode("utf-8")
        return AESGCM(_field_encryption_key()).decrypt(nonce, ciphertext, aad).decode("utf-8")
    except (ValueError, UnicodeEncodeError, InvalidTag) as error:
        raise RuntimeError(f"Could not decrypt sensitive field '{field}'.") from error


def encrypt_iban(value: Optional[str]) -> Optional[str]:
    return encrypt_field(value, "iban")


def decrypt_iban(value: Optional[str]) -> Optional[str]:
    return decrypt_field(value, "iban")


def transform_iban_fields(document: dict, encrypt: bool) -> dict:
    """Copy a document while encrypting IBANs and saved-card fragments at known storage paths."""
    transform = encrypt_iban if encrypt else decrypt_iban
    result = dict(document)
    if "iban" in result:
        result["iban"] = transform(result.get("iban"))
    if isinstance(result.get("bank_accounts"), list):
        result["bank_accounts"] = [
            {**account, "iban": transform(account.get("iban"))}
            if isinstance(account, dict) and "iban" in account else account
            for account in result["bank_accounts"]
        ]
    snapshot = result.get("bank_account_snapshot")
    if isinstance(snapshot, dict):
        result["bank_account_snapshot"] = transform_iban_fields(snapshot, encrypt)
    split = result.get("platform_split")
    if isinstance(split, dict) and "platform_iban" in split:
        result["platform_split"] = {**split, "platform_iban": transform(split.get("platform_iban"))}
    if "issuer_iban" in result:
        result["issuer_iban"] = transform(result.get("issuer_iban"))
    card_transform = encrypt_field if encrypt else decrypt_field
    for field in ("card_last4", "card_expiry"):
        if field in result:
            result[field] = card_transform(result.get(field), field)
    if isinstance(result.get("payment_cards"), list):
        result["payment_cards"] = [
            {key: card_transform(value, f"card_{key}") if key in ("last4", "exp") else value
             for key, value in card.items()} if isinstance(card, dict) else card
            for card in result["payment_cards"]
        ]
    return result


# ---------- production configuration ----------
def validate_production_environment(env: Optional[dict] = None) -> None:
    """Fail closed in production while keeping explicitly named dev/test environments usable."""
    env = os.environ if env is None else env
    app_env = (env.get("APP_ENV") or "").strip().lower()
    if app_env in {"development", "test"}:
        return
    if app_env != "production":
        raise RuntimeError("APP_ENV must be explicitly set to 'production', 'development', or 'test'.")

    required = ("MONGO_URL", "MONGO_AUDIT_URL", "DB_NAME", "JWT_SECRET", "FIELD_ENCRYPTION_KEY", "RESEND_API_KEY",
                "CORS_ORIGINS", "APP_BASE_URL",
                "WEBHOOK_ALLOWED_IPS", "BANK_WEBHOOK_SECRET", "INVOICE_WEBHOOK_SECRET")
    missing = [key for key in required if not env.get(key, "").strip()]
    if missing:
        raise RuntimeError("Missing required production settings: " + ", ".join(missing))
    if env.get("MONGO_TLS", "").strip().lower() != "true":
        raise RuntimeError("MONGO_TLS=true is required in production.")
    if len(env["JWT_SECRET"].encode("utf-8")) < 32:
        raise RuntimeError("JWT_SECRET must be at least 32 bytes in production.")
    for key in ("BANK_WEBHOOK_SECRET", "INVOICE_WEBHOOK_SECRET"):
        if len(env[key].encode("utf-8")) < 32:
            raise RuntimeError(f"{key} must be at least 32 bytes in production.")
    _field_encryption_key(env)
    parse_cors_origins(env)
    frontend = urlsplit(env["APP_BASE_URL"].strip())
    if frontend.scheme != "https" or not frontend.netloc:
        raise RuntimeError("APP_BASE_URL must be an HTTPS origin in production.")

    cidrs = [item.strip() for item in env["WEBHOOK_ALLOWED_IPS"].split(",") if item.strip()]
    if not cidrs:
        raise RuntimeError("WEBHOOK_ALLOWED_IPS must contain one or more CIDR networks.")
    try:
        networks = [ipaddress.ip_network(item, strict=True) for item in cidrs]
    except ValueError as error:
        raise RuntimeError("WEBHOOK_ALLOWED_IPS must contain canonical CIDR networks.") from error
    if any(network.prefixlen == 0 for network in networks):
        raise RuntimeError("WEBHOOK_ALLOWED_IPS cannot contain an unrestricted /0 network.")


def parse_cors_origins(env: Optional[dict] = None) -> list[str]:
    """Use explicit HTTPS origins in production and a wildcard only in development/test."""
    env = os.environ if env is None else env
    app_env = (env.get("APP_ENV") or "development").strip().lower()
    origins = [origin.strip().rstrip("/") for origin in env.get("CORS_ORIGINS", "").split(",") if origin.strip()]
    if app_env == "production":
        if not origins or "*" in origins:
            raise RuntimeError("CORS_ORIGINS must list explicit HTTPS frontend origins in production.")
        for origin in origins:
            parsed = urlsplit(origin)
            if parsed.scheme != "https" or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
                raise RuntimeError("Production CORS_ORIGINS entries must be HTTPS origins without paths or wildcards.")
        return origins
    return origins or ["*"]
