from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parent / '.env')

import os
import re
import base64
import uuid
import json
import jwt
import bcrypt
import logging
import asyncio
import time
import traceback
from datetime import date, datetime, timezone, timedelta
from html import escape as html_escape
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo
from decimal import Decimal, ROUND_HALF_UP
from bson.decimal128 import Decimal128
from urllib.parse import urlsplit
import money as moneylib

from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Form, Response, WebSocket, WebSocketDisconnect
from starlette.middleware.gzip import GZipMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import DeleteOne, UpdateOne
from pymongo.errors import DuplicateKeyError
from pydantic import BaseModel, Field, EmailStr, ValidationError, field_validator

from seed import ensure_admin_account, purge_demo_accounts
from delivery_routes import sequence_stops

import io
import pandas as pd
from fastapi import File, UploadFile, Query
import secrets
import hmac
import hashlib
import random
import httpx
from fastapi import Header, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
from email_service import try_send_email, try_send_email_detailed, invoice_email_html, reminder_email_html, otp_email_html, password_reset_otp_email_html
from invoices import build_invoice_pdf
from invoices import build_order_invoice_pdf
from logos import LogoError, process_upload, save_logo, delete_logo, logo_bytes
from migrations import migrate_store_branches, migrate_store_finance, migrate_supplier_warehouses
from payments import validate_card, gen_token, simulate_hold, simulate_charge, CardError
from waybills import build_waybill_html
import web_push
from tbc_gateway import TBCGatewayError, credentials_override as tbc_credentials, create_payment as create_tbc_payment, get_payment as get_tbc_payment, validate_configuration as validate_tbc_configuration
from bog_gateway import BOGGatewayError, credentials_override as bog_credentials, callback_url as bog_callback_url, create_order as create_bog_order, get_order as get_bog_order, validate_configuration as validate_bog_configuration, verify_callback_signature

import security as safeguards
from inventory_sync import InventorySyncAdapter

# Fail closed: refuse to start without an explicit APP_ENV and, in production, the required secrets.
safeguards.validate_production_environment(os.environ)

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url, **safeguards.mongo_client_options(mongo_url, os.environ))
db = client[os.environ['DB_NAME']]
audit_url = os.environ.get("MONGO_AUDIT_URL", "").strip()
audit_client = (AsyncIOMotorClient(audit_url, **safeguards.mongo_client_options(audit_url, os.environ))
                if audit_url else None)
audit_db = audit_client[os.environ.get("AUDIT_DB_NAME", "distro_audit")] if audit_client is not None else None


def _audit_collection(name: str):
    target = audit_db if audit_db is not None else db
    try:
        return target[name]
    except TypeError:
        return getattr(target, name)


# In production, the audit URI uses a dedicated find+insert-only MongoDB role.
financial_audit_logs = safeguards.AppendOnlyCollection(lambda: _audit_collection("financial_audit_logs"))
connection_audit_logs = safeguards.AppendOnlyCollection(lambda: _audit_collection("connection_audit_logs"))

JWT_SECRET = os.environ['JWT_SECRET']
JWT_ALGORITHM = "HS256"

app = FastAPI()
api = APIRouter()
security = HTTPBearer(auto_error=False)

logging.basicConfig(level=logging.INFO)
safeguards.install_log_redaction()
logger = logging.getLogger("distro")


class LocationSocketManager:
    def __init__(self):
        self.supplier_clients: Dict[str, Dict[WebSocket, Optional[str]]] = {}
        self.order_clients: Dict[str, set] = {}

    def connect_supplier(self, supplier_id: str, warehouse_id: Optional[str], websocket: WebSocket):
        self.supplier_clients.setdefault(supplier_id, {})[websocket] = warehouse_id

    def connect_order(self, order_id: str, websocket: WebSocket):
        self.order_clients.setdefault(order_id, set()).add(websocket)

    def disconnect_supplier(self, supplier_id: str, websocket: WebSocket):
        clients = self.supplier_clients.get(supplier_id, {})
        clients.pop(websocket, None)
        if not clients:
            self.supplier_clients.pop(supplier_id, None)

    def disconnect_order(self, order_id: str, websocket: WebSocket):
        clients = self.order_clients.get(order_id, set())
        clients.discard(websocket)
        if not clients:
            self.order_clients.pop(order_id, None)

    async def broadcast_supplier(self, supplier_id: str, warehouse_id: Optional[str], payload: dict):
        clients = self.supplier_clients.get(supplier_id, {})
        targets = [
            websocket for websocket, scoped_warehouse in clients.items()
            if scoped_warehouse is None or scoped_warehouse == warehouse_id
        ]
        await asyncio.gather(*(self._send(websocket, payload) for websocket in targets), return_exceptions=True)

    async def broadcast_order(self, order_id: str, payload: dict):
        targets = list(self.order_clients.get(order_id, set()))
        await asyncio.gather(*(self._send(websocket, payload) for websocket in targets), return_exceptions=True)

    @staticmethod
    async def _send(websocket: WebSocket, payload: dict):
        try:
            await websocket.send_json(payload)
        except Exception:
            return


location_sockets = LocationSocketManager()


# ---------- helpers ----------
def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()

def verify_password(p: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode(), h.encode())
    except Exception:
        return False

def create_token(user_id: str, user: Optional[dict] = None) -> str:
    payload = {"sub": user_id, "exp": datetime.now(timezone.utc) + timedelta(days=7), "type": "access"}
    if user:
        access_role = user.get("supplier_access_role")
        payload.update({
            "role": ("Branch Manager" if access_role == "branch_manager" else "Global Admin")
            if user.get("role") == "supplier" else user.get("role"),
            "app_role": user.get("role"),
            "assigned_branch_id": user.get("assigned_branch_id"),
            "store_access_role": user.get("store_access_role"),
        })
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _analytics_date_range(start_date: Optional[str], end_date: Optional[str], max_days: int = 366):
    if not start_date and not end_date:
        return None
    first = last = None
    try:
        first = date.fromisoformat(start_date) if start_date else None
        last = date.fromisoformat(end_date) if end_date else None
    except (TypeError, ValueError):
        raise HTTPException(400, "Dates must use YYYY-MM-DD format.")
    if (first and first.isoformat() != start_date) or (last and last.isoformat() != end_date):
        raise HTTPException(400, "Dates must use YYYY-MM-DD format.")
    if first and last and first > last:
        raise HTTPException(400, "start_date must be on or before end_date.")
    if first and last and (last - first).days + 1 > max_days:
        raise HTTPException(422, f"Date range cannot exceed {max_days} days.")
    return first, last


def _analytics_date_query(field: str, date_range) -> dict:
    if not date_range:
        return {}
    first, last = date_range
    bounds = {}
    if first:
        bounds["$gte"] = moneylib.platform_day_start_utc(first).isoformat()
    if last:
        bounds["$lt"] = moneylib.platform_day_start_utc(last + timedelta(days=1)).isoformat()
    return {field: bounds}

async def get_current_user(request: Request, cred: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> dict:
    token = cred.credentials if cred else request.cookies.get("access_token")
    if not token:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")
    user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(401, "User not found")
    user = safeguards.transform_iban_fields(user, encrypt=False)
    if user.get("role") == "retailer" and user.get("active") is False:
        raise HTTPException(403, "Store staff account is inactive.")
    if user.get("role") == "supplier":
        if user.get("active") is False:
            raise HTTPException(403, "Distributor staff account is inactive.")
        user.setdefault("supplier_access_role", "branch_manager" if user.get("supplier_id") else "global_admin")
        if user["supplier_access_role"] == "branch_manager" and not user.get("assigned_branch_id"):
            raise HTTPException(403, "A branch manager must be assigned to a warehouse.")
        user["branch_role"] = "Branch Manager" if user["supplier_access_role"] == "branch_manager" else "Global Admin"
    elif user.get("role") == "retailer":
        user.setdefault("store_access_role", "global_admin")
        user["branch_role"] = {
            "global_admin": "Global Admin",
            "branch_manager": "Branch Manager",
            "staff": "Staff",
        }.get(user["store_access_role"], "Staff")
        user["permissions"] = effective_store_permissions(user)
    return user


async def authenticate_websocket(websocket: WebSocket) -> Optional[dict]:
    try:
        credentials = await asyncio.wait_for(websocket.receive_json(), timeout=10)
        token = credentials.get("token") if isinstance(credentials, dict) else None
        if not token:
            raise ValueError("Missing access token")
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user = await db.users.find_one({"id": payload.get("sub")}, {"_id": 0, "password_hash": 0})
        if not user:
            raise ValueError("User not found")
        if user.get("role") == "supplier":
            user.setdefault("supplier_access_role", "branch_manager" if user.get("supplier_id") else "global_admin")
        elif user.get("role") == "retailer":
            user.setdefault("store_access_role", "global_admin")
        return user
    except (asyncio.TimeoutError, ValueError, jwt.InvalidTokenError, KeyError):
        await websocket.close(code=1008, reason="Authentication required")
        return None

def require_role(*roles):
    async def checker(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(403, "Insufficient permissions")
        return user
    return checker


def supplier_owner_id(user: dict) -> str:
    return user.get("supplier_id") or user["id"]


def store_owner_id(user: dict) -> str:
    return user.get("retailer_id") or user["id"]


def require_store_owner(user: dict) -> None:
    if user.get("store_access_role", "global_admin") != "global_admin":
        raise HTTPException(403, "Only the store owner can manage store settings.")


STORE_PERMISSION_FLAGS = (
    "canViewFinancials", "canManageInventory", "canChangePrices", "canAccessPOS", "canManageApi",
    "canManageOrders",
)


def default_store_permissions(role: str) -> dict:
    # Staff keep the day-to-day abilities they had before the matrix existed.
    return {
        flag: flag in ("canManageInventory", "canAccessPOS", "canManageOrders")
        for flag in STORE_PERMISSION_FLAGS
    }


def effective_store_permissions(user: dict) -> dict:
    """Owners hold every flag; staff only the flags explicitly granted to them."""
    role = user.get("store_access_role", "global_admin")
    if role == "global_admin":
        return {flag: True for flag in STORE_PERMISSION_FLAGS}
    stored = user.get("permissions")
    if not isinstance(stored, dict):
        stored = default_store_permissions(role)
    return {flag: stored.get(flag) is True for flag in STORE_PERMISSION_FLAGS}


def require_store_permission(flag: str):
    """Dependency factory: store owner always passes, staff need the flag enabled."""
    if flag not in STORE_PERMISSION_FLAGS:
        raise ValueError(f"Unknown permission flag: {flag}")

    async def dependency(user: dict = Depends(require_role("retailer"))) -> dict:
        if not effective_store_permissions(user)[flag]:
            raise HTTPException(403, f"Permission required: {flag}")
        return user

    return dependency


def validate_store_permissions(value: Optional[dict]) -> Optional[dict]:
    if value is None:
        return None
    unknown = set(value) - set(STORE_PERMISSION_FLAGS)
    if unknown:
        raise ValueError(f"Unknown permissions: {', '.join(sorted(unknown))}")
    if not all(isinstance(flag, bool) for flag in value.values()):
        raise ValueError("Permission flags must be true or false.")
    return {flag: bool(value.get(flag, False)) for flag in STORE_PERMISSION_FLAGS}


def require_supplier_permission(user: dict, permission: str) -> None:
    if user.get("role") != "supplier":
        raise HTTPException(403, "Not allowed.")
    if user.get("supplier_access_role") == "branch_manager":
        permissions = set(user.get("operational_permissions", []))
        aliases = {
            "routes": {"routes", "deliveries"},
            "drivers": {"drivers", "deliveries"},
            "inventory": {"inventory"},
            "orders": {"orders"},
            "finance": {"finance"},
            "transfers": {"transfers"},
        }
        if not permissions.intersection(aliases.get(permission, {permission})):
            raise HTTPException(403, "You do not have permission to perform this operation.")


async def supplier_warehouse_id(user: dict, requested_id: Optional[str] = None) -> Optional[str]:
    owner_id = supplier_owner_id(user)
    assigned_id = user.get("assigned_branch_id") if user.get("supplier_access_role") == "branch_manager" else None
    if user.get("supplier_access_role") == "branch_manager" and not assigned_id:
        raise HTTPException(403, "A branch manager must be assigned to a warehouse.")
    if assigned_id:
        if requested_id not in (None, "", assigned_id):
            raise HTTPException(403, "Branch managers cannot access another warehouse.")
        requested_id = assigned_id
    if requested_id in (None, "", "all"):
        return None
    warehouse_collection = getattr(db, "supplier_warehouses", None)
    if warehouse_collection is None:
        raise HTTPException(404, "Warehouse not found.")
    warehouse = await warehouse_collection.find_one(
        {"id": requested_id, "supplier_id": owner_id, "active": True}, {"_id": 0, "id": 1},
    )
    if not warehouse:
        raise HTTPException(404, "Warehouse not found.")
    return requested_id


def order_payment_totals(order: dict) -> tuple[float, float]:
    total = moneylib.q(order.get("total"))
    if "amount_paid" in order:
        raw_paid = moneylib.amount_or_zero(order.get("amount_paid"))
    else:
        raw_paid = total if (
            not order.get("external_order")
            and (order.get("paid_at_checkout") or order.get("payment_status") == "Succeeded")
        ) else moneylib.ZERO
    amount_paid = min(total, max(moneylib.ZERO, raw_paid))
    return moneylib.as_json(total), moneylib.as_json(max(moneylib.ZERO, total - amount_paid))


def _encrypt_sensitive_fields(document: dict) -> dict:
    if not os.environ.get("FIELD_ENCRYPTION_KEY", "").strip():
        return document
    return safeguards.transform_iban_fields(document, encrypt=True)


def _decrypt_sensitive_fields(document: dict) -> dict:
    return safeguards.transform_iban_fields(document, encrypt=False)


async def log_financial_event(action: str, actor: dict, entity: str, entity_id: str,
                              before=None, after=None, status: Optional[str] = None, **extra) -> None:
    """Append-only audit record; entries are never updated or deleted by the API."""
    action_lower = action.lower()
    event_status = status or (
        "error" if any(token in action_lower for token in ("blocked", "failed", "error"))
        else "pending" if "pending" in action_lower
        else "success"
    )
    await financial_audit_logs.insert_one({
        "id": str(uuid.uuid4()), "action": action, "entity": entity, "entity_id": entity_id,
        "actor_id": (actor or {}).get("id"),
        "actor_name": (actor or {}).get("business_name") or (actor or {}).get("name", ""),
        "before": before, "after": after, "at": now_iso(), "status": event_status, **extra,
    })


def bank_account_snapshot(supplier: Optional[dict]) -> dict:
    """Frozen copy of the supplier's bank details, stored on the order at creation time."""
    supplier = _decrypt_sensitive_fields(supplier or {})
    accounts = [dict(account) for account in supplier.get("bank_accounts") or []]
    return _encrypt_sensitive_fields({
        "bank_name": supplier.get("bank_name", ""), "iban": supplier.get("iban", ""),
        "bank_accounts": accounts, "captured_at": now_iso(),
    })


async def outstanding_debt(order_query: dict) -> tuple[float, int]:
    """Unpaid balance and count of open orders matching the query (cancelled/external/unconfirmed gateway excluded)."""
    orders = await db.orders.find(
        {**order_query, "external_order": {"$ne": True}, "status": {"$ne": "Cancelled"}}, {"_id": 0},
    ).to_list(100000)
    debt, count = moneylib.ZERO, 0
    for order in orders:
        if order.get("payment_method") in {"tbc", "bog"} and order.get("payment_status") != "Succeeded":
            continue
        balance = moneylib.q(order_payment_totals(order)[1])
        if balance > 0:
            debt += balance
            count += 1
    return moneylib.as_json(debt), count

PAYMENT_REFERENCE_RE = re.compile(r"\bREF-INV-\d{4,}\b", re.IGNORECASE)


async def _next_payment_reference() -> str:
    await db.counters.update_one(
        {"_id": "bank_transfer_reference"},
        {"$inc": {"seq": 1}},
        upsert=True,
    )
    row = await db.counters.find_one({"_id": "bank_transfer_reference"}, {"_id": 0, "seq": 1})
    seq = int((row or {}).get("seq", 0) or 0)
    return f"REF-INV-{seq:04d}"


LIFECYCLE_BY_STATUS = {
    "Pending Payment": "NEW",
    "Pending": "NEW", "Processing": "APPROVED", "In Transit": "IN_TRANSIT",
    "Delivered": "DELIVERED", "Cancelled": "CANCELLED",
}
STATUS_BY_LIFECYCLE = {
    "NEW": "Pending", "APPROVED": "Processing", "IN_TRANSIT": "In Transit",
    "DELIVERED": "Delivered", "CANCELLED": "Cancelled", "REJECTED": "Cancelled",
}


def lifecycle_status(order: dict) -> str:
    if order.get("status") == "Cancelled" and order.get("rejected"):
        return "REJECTED"
    return LIFECYCLE_BY_STATUS.get(order.get("status"), "NEW")


def order_payment_fields(order: dict) -> dict:
    total, balance = order_payment_totals(order)
    paid = moneylib.as_json(moneylib.q(total) - moneylib.q(balance))
    status = "PAID" if balance <= 0 and total > 0 else ("PARTIAL" if paid > 0 else "UNPAID")
    return {"paymentStatus": status, "paidAmount": paid, "totalAmount": total, "balance": balance}


async def sync_order_payment_fields(order_id: str) -> None:
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if order:
        await db.orders.update_one({"id": order_id}, {"$set": order_payment_fields(order)})


def order_delivery_date(order: dict) -> Optional[datetime]:
    delivered_at = order.get("delivered_at")
    if not delivered_at:
        delivered_at = next(
            (entry.get("at") for entry in reversed(order.get("timeline", []))
             if entry.get("status") == "Delivered" and entry.get("at")),
            None,
        )
    if not delivered_at and order.get("status") == "Delivered":
        delivered_at = order.get("updated_at")
    if not delivered_at:
        return None
    try:
        delivered = datetime.fromisoformat(str(delivered_at).replace("Z", "+00:00"))
    except ValueError:
        logger.warning("Invalid delivery timestamp on order %s", order.get("id"))
        return None
    if delivered.tzinfo is None:
        delivered = delivered.replace(tzinfo=timezone.utc)
    return delivered


def finance_order_view(order: dict, terms: Optional[dict], now: Optional[datetime] = None) -> dict:
    total, balance = order_payment_totals(order)
    amount_paid = moneylib.as_json(moneylib.q(total) - moneylib.q(balance))
    delivered_at = order_delivery_date(order)
    due_days = int(terms.get("payment_due_days", 14)) if terms else 14
    due_at = delivered_at + timedelta(days=due_days) if delivered_at else None
    now = now or datetime.now(timezone.utc)
    if balance <= 0:
        payment_status = "paid"
    elif due_at and due_at.astimezone(ZoneInfo("Asia/Tbilisi")).date() < now.astimezone(ZoneInfo("Asia/Tbilisi")).date():
        payment_status = "overdue"
    elif amount_paid > 0:
        payment_status = "partially_paid"
    else:
        payment_status = "unpaid"
    view = dict(order)
    view.update({
        "total": total,
        "amount_paid": amount_paid,
        "balance_due": balance,
        "payment_status": payment_status,
        "payment_due_days": due_days,
        "payment_due_date": due_at.isoformat() if due_at else None,
        "delivered_at": delivered_at.isoformat() if delivered_at else order.get("delivered_at"),
        "payment_entries": order.get("payment_entries", []),
    })
    return view


async def resolve_store_branch(user: dict, branch_id: Optional[str]) -> str:
    owner_id = store_owner_id(user)
    assigned_id = user.get("assigned_branch_id") if user.get("store_access_role") != "global_admin" else None
    if assigned_id:
        if branch_id not in (None, "", assigned_id):
            raise HTTPException(403, "Store staff cannot access another branch.")
        branch_id = assigned_id
    resolved_id = branch_id or user.get("default_branch_id")
    if resolved_id:
        branch = await db.store_branches.find_one({
            "id": resolved_id, "retailer_id": owner_id, "active": True,
        }, {"id": 1})
        if not branch and resolved_id != owner_id:
            raise HTTPException(404, "Active store branch not found.")
        return resolved_id
    if assigned_id:
        raise HTTPException(403, "Store staff do not have an assigned branch.")
    return owner_id


# ---------- models ----------
class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: str  # retailer | supplier
    business_name: Optional[str] = ""
    address: Optional[str] = ""
    city: Optional[str] = ""
    cities: List[str] = Field(default_factory=list)
    identification_number: str  # Tax ID / Personal ID (mandatory)
    phone: Optional[str] = ""
    category: Optional[str] = ""  # legacy free-text category (kept for compatibility)
    category_ids: List[str] = Field(default_factory=list)  # supplier: selected Category ids (many-to-many)
    business_sectors: List[str] = Field(default_factory=list)  # supplier: served business sectors
    establishment_type: Optional[str] = ""  # retailer only
    establishment_type_other: Optional[str] = ""
    # retailer card (store masked only)
    card_name: Optional[str] = ""
    card_number: Optional[str] = ""
    card_expiry: Optional[str] = ""
    # supplier banking
    bank_name: Optional[str] = ""
    iban: Optional[str] = ""
    accept_terms: bool = False
    vat_registered: bool  # VAT payer (mandatory choice)

    @field_validator("cities")
    @classmethod
    def validate_cities_list(cls, v):
        return _validate_cities(v)

    @field_validator("city")
    @classmethod
    def validate_single_city(cls, v):
        return (_validate_cities(v, allow_all=False) or [""])[0] if v else ""

    @field_validator('identification_number')
    @classmethod
    def validate_tax_id(cls, v: str) -> str:
            if not v.isdigit() or len(v) not in [9, 11]:
                raise ValueError('საიდენტიფიკაციო ან პირადი ნომერი უნდა შედგებოდეს ზუსტად 9 ან 11 ციფრისგან!')
            return v
class StaffFirstPasswordIn(BaseModel):
    email: EmailStr
    temporary_password: str = Field(min_length=8, max_length=100)
    new_password: str = Field(min_length=8, max_length=72)

    @field_validator("new_password")
    @classmethod
    def validate_new_password_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be 72 UTF-8 bytes or fewer.")
        return value


class SupplierWarehouseIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    city: str = Field(min_length=2, max_length=100)
    servedCities: Optional[List[str]] = None
    address: str = Field(default="", max_length=500)
    active: bool = True
    is_default: bool = False

    @field_validator("servedCities", mode="before")
    @classmethod
    def validate_served_cities(cls, value):
        if value is None:
            return None
        cities = _validate_cities(value, allow_all=False)
        if not cities:
            raise ValueError("Select at least one city served by this warehouse.")
        return cities

    @field_validator("name", "city", "address")
    @classmethod
    def clean_warehouse_text(cls, value: str) -> str:
        return value.strip()


class WarehouseTransferIn(BaseModel):
    product_id: str
    from_warehouse_id: str
    to_warehouse_id: str
    quantity: int = Field(gt=0, le=100000)
    note: str = Field(default="", max_length=300)

    @field_validator("note")
    @classmethod
    def clean_transfer_note(cls, value: str) -> str:
        return value.strip()


class SupplierStaffIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: str = Field(default="", max_length=40)
    branch_id: str
    operational_permissions: List[str] = Field(default_factory=lambda: ["orders", "inventory", "drivers", "routes"])
    permissions: Optional[dict[str, bool]] = None
    active: bool = True

    @field_validator("name", "phone")
    @classmethod
    def clean_staff_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("operational_permissions")
    @classmethod
    def validate_staff_permissions(cls, value: List[str]) -> List[str]:
        allowed = {"orders", "inventory", "drivers", "routes", "finance", "transfers"}
        if not set(value).issubset(allowed):
            raise ValueError("Unsupported operational permission.")
        return list(dict.fromkeys(value))

    def resolved_permissions(self) -> List[str]:
        if self.permissions is None:
            return self.operational_permissions
        allowed = {"orders", "inventory", "transfers", "deliveries"}
        if not set(self.permissions).issubset(allowed):
            raise ValueError("Unsupported operational permission.")
        permissions = {key for key, enabled in self.permissions.items() if enabled}
        resolved = []
        if "orders" in permissions:
            resolved.append("orders")
        if "inventory" in permissions:
            resolved.append("inventory")
        if "transfers" in permissions:
            resolved.append("transfers")
        if "deliveries" in permissions:
            resolved.extend(["drivers", "routes"])
        return resolved


class StoreStaffIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    branch_id: str
    role: str
    permissions: Optional[Dict[str, Any]] = None

    @field_validator("permissions")
    @classmethod
    def validate_permissions(cls, value):
        return validate_store_permissions(value)

    @field_validator("name")
    @classmethod
    def clean_store_staff_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("role")
    @classmethod
    def validate_store_staff_role(cls, value: str) -> str:
        if value not in {"branch_manager", "staff"}:
            raise ValueError("Role must be Branch Manager or Staff.")
        return value


class StoreStaffStatusIn(BaseModel):
    active: Optional[bool] = None
    role: Optional[str] = None
    branch_id: Optional[str] = None
    permissions: Optional[Dict[str, Any]] = None

    @field_validator("permissions")
    @classmethod
    def validate_permissions(cls, value):
        return validate_store_permissions(value)

    @field_validator("role")
    @classmethod
    def validate_role(cls, value):
        if value is not None and value not in {"branch_manager", "staff"}:
            raise ValueError("Role must be Branch Manager or Staff.")
        return value

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class VerifyOtpIn(BaseModel):
    email: EmailStr
    code: str

class ForgotPasswordIn(BaseModel):
    email: EmailStr

class ResetPasswordIn(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$")
    password: str = Field(min_length=8, max_length=72)

    @field_validator("password")
    @classmethod
    def validate_password_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be 72 UTF-8 bytes or fewer.")
        return value

class WaybillDispatchIn(BaseModel):
    driver_name: str = Field(min_length=1, max_length=120)
    driver_id: Optional[str] = Field(default="", max_length=32)
    vehicle_plate: str = Field(min_length=1, max_length=32)
    transport_type: Optional[str] = Field(default="", max_length=80)

class ResendIn(BaseModel):
    email: EmailStr

class TierPrice(BaseModel):
    min_qty: int
    price: float

class ProductIn(BaseModel):
    name: str = Field(min_length=1)
    category: str
    city: Optional[str] = ""
    price_per_unit: float = Field(ge=0)
    tier_pricing: List[TierPrice] = []
    moq: int = Field(default=1, ge=1)
    stock: int = Field(default=0, ge=0)
    image: str = ""
    description: Optional[str] = ""
    sku: Optional[str] = ""
    barcode: Optional[str] = ""
    unit: Optional[str] = ""
    external_id: Optional[str] = ""
    discount_exempt: bool = False

class ProductImportRow(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    city: Optional[str] = None
    price_per_unit: Optional[float] = Field(default=None, ge=0)
    tier_pricing: Optional[List[TierPrice]] = None
    moq: Optional[int] = Field(default=None, ge=1)
    stock: Optional[int] = Field(default=None, ge=0)
    image: Optional[str] = None
    description: Optional[str] = None
    sku: Optional[str] = None
    barcode: Optional[str] = None
    unit: Optional[str] = None
    external_id: Optional[str] = None

class OrderItem(BaseModel):
    product_id: str
    name: str
    image: str = ""
    supplier_id: str
    quantity: int = Field(ge=1)
    unit_price: float = Field(ge=0)

class OrderIn(BaseModel):
    items: List[OrderItem]
    delivery_address: str
    notes: Optional[str] = ""
    delivery_window: Optional[str] = ""
    payment_method: Optional[str] = "cash"  # cash | card | consignment | bank_transfer
    branch_id: Optional[str] = Field(default=None, max_length=100)
    card_id: Optional[str] = Field(default=None, max_length=64)

class OrderInvoiceShareIn(BaseModel):
    email: Optional[EmailStr] = None

class StoreBranchIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    address: str = Field(min_length=3, max_length=500)
    phone: str = Field(default="", max_length=40)
    active: bool = True

    @field_validator("name", "address", "phone")
    @classmethod
    def clean_branch_fields(cls, value: str) -> str:
        return value.strip()

class StoreIntegrationIn(BaseModel):
    software: str = Field(min_length=1, max_length=80)
    location_name: str = Field(default="", max_length=120)

    @field_validator("software", "location_name")
    @classmethod
    def clean_integration_fields(cls, value: str) -> str:
        return value.strip()

class POSSaleItemIn(BaseModel):
    product_id: Optional[str] = Field(default=None, max_length=100)
    sku: Optional[str] = Field(default=None, max_length=100)
    product_name: Optional[str] = Field(default=None, max_length=200)
    quantity: float = Field(gt=0, le=1000000)
    retail_price: float = Field(ge=0, le=100000000)

class POSSaleIn(BaseModel):
    sale_id: str = Field(min_length=1, max_length=160)
    branch_id: str = Field(min_length=1, max_length=100)
    sold_at: datetime
    items: List[POSSaleItemIn] = Field(min_length=1, max_length=100)

class StorePricingAdvisorIn(BaseModel):
    order_id: str = Field(min_length=1, max_length=100)
    product_id: str = Field(min_length=1, max_length=100)
    planned_retail_price: Optional[Decimal] = Field(default=None, ge=0, le=100000000)


class ExternalMarketPriceIn(BaseModel):
    product_id: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=2, max_length=120)
    source_url: str = Field(min_length=10, max_length=2048)
    price: Decimal = Field(gt=0, le=100000000)
    currency: str = Field(default="GEL", min_length=3, max_length=3)
    confidence: Decimal = Field(default=Decimal("1"), ge=0, le=1)
    observed_at: datetime

    @field_validator("source_url")
    @classmethod
    def require_https_source(cls, value: str) -> str:
        value = value.strip()
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("Benchmark source URL must use HTTPS.")
        return value

    @field_validator("currency")
    @classmethod
    def normalize_benchmark_currency(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("observed_at")
    @classmethod
    def require_timezone_aware_benchmark_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("observed_at must include a timezone.")
        return value.astimezone(timezone.utc)


class ExternalMarketPriceBatchIn(BaseModel):
    benchmarks: List[ExternalMarketPriceIn] = Field(min_length=1, max_length=500)

class StoreExpenseIn(BaseModel):
    branch_id: str = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=80)
    amount: float = Field(gt=0, le=100000000)
    expense_date: datetime
    note: str = Field(default="", max_length=500)

class ManualExternalOrderIn(BaseModel):
    customer_name: str = Field(min_length=1, max_length=160)
    customer_phone: str = Field(default="", max_length=40)
    delivery_address: str = Field(min_length=3, max_length=500)
    item_name: str = Field(min_length=1, max_length=200)
    product_id: Optional[str] = Field(default=None, max_length=100)
    quantity: int = Field(default=1, ge=1, le=100000)
    unit_price: float = Field(ge=0)
    notes: Optional[str] = Field(default="", max_length=1000)
    delivery_window: Optional[str] = Field(default="", max_length=120)
    external_order: bool

    @field_validator("customer_name", "delivery_address", "item_name")
    @classmethod
    def validate_manual_order_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Customer, item, and delivery address are required.")
        return value

    @field_validator("external_order")
    @classmethod
    def require_external_order_flag(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Manual orders must be explicitly marked as external/off-app.")
        return value

class DriverIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=5, max_length=40)
    vehicle_plate: str = Field(default="", max_length=32)
    personal_id: str = Field(default="", max_length=32)
    transport_type: str = Field(default="", max_length=80)
    working_days: List[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5], min_length=1, max_length=7)
    active: bool = True

    @field_validator("name", "phone")
    @classmethod
    def validate_driver_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Driver name and phone are required.")
        return value

    @field_validator("phone")
    @classmethod
    def validate_driver_phone(cls, value: str) -> str:
        if len(re.sub(r"\D", "", value)) < 5:
            raise ValueError("Enter a valid driver phone number.")
        return value

    @field_validator("vehicle_plate")
    @classmethod
    def validate_vehicle_plate(cls, value: str) -> str:
        return value.strip()

    @field_validator("working_days")
    @classmethod
    def validate_working_days(cls, value: List[int]) -> List[int]:
        if any(day < 1 or day > 7 for day in value) or len(set(value)) != len(value):
            raise ValueError("Working days must be unique weekdays numbered from 1 to 7.")
        return sorted(value)

class DeliveryRouteIn(BaseModel):
    origin_lat: Optional[float] = Field(default=None, ge=-90, le=90)
    origin_lon: Optional[float] = Field(default=None, ge=-180, le=180)
    order_ids: Optional[List[str]] = Field(default=None, min_length=1, max_length=24)
    replace_route_ids: List[str] = Field(default_factory=list, max_length=100)

class RouteStopOrderIn(BaseModel):
    stop_order: List[str] = Field(min_length=1, max_length=24)

    @field_validator("stop_order")
    @classmethod
    def validate_stop_order(cls, stop_order: List[str]) -> List[str]:
        if any(not order_id.strip() for order_id in stop_order) or len(set(stop_order)) != len(stop_order):
            raise ValueError("Route stop order must contain unique delivery IDs.")
        return stop_order

class TrafficRouteIn(BaseModel):
    geometry: List[tuple[float, float]] = Field(min_length=1, max_length=10000)
    stop_order: List[str] = Field(min_length=1, max_length=24)
    distance_meters: int = Field(ge=0)
    duration_seconds: int = Field(ge=0)

    @field_validator("geometry")
    @classmethod
    def validate_route_geometry(cls, points: List[tuple[float, float]]) -> List[tuple[float, float]]:
        if any(not -180 <= lon <= 180 or not -90 <= lat <= 90 for lon, lat in points):
            raise ValueError("Route geometry contains invalid coordinates.")
        return points

    @field_validator("stop_order")
    @classmethod
    def validate_stop_order(cls, stop_order: List[str]) -> List[str]:
        if any(not order_id.strip() for order_id in stop_order) or len(set(stop_order)) != len(stop_order):
            raise ValueError("Route stop order must contain unique delivery IDs.")
        return stop_order

class RouteAssignmentIn(BaseModel):
    driver_id: str = Field(min_length=1, max_length=100)
    scheduled_at: datetime
    traffic_route: Optional[TrafficRouteIn] = None
    replace_route_ids: List[str] = Field(default_factory=list, max_length=100)

    @field_validator("scheduled_at")
    @classmethod
    def validate_route_schedule(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("A timezone-aware scheduled date and time are required.")
        if value <= datetime.now(timezone.utc):
            raise ValueError("The route schedule must be in the future.")
        return value

class StatusUpdate(BaseModel):
    status: str
    reason: Optional[str] = Field(default=None, max_length=300)

class BulkStatusIn(BaseModel):
    order_ids: List[str] = Field(min_length=1, max_length=200)
    status: str
    reason: Optional[str] = Field(default=None, max_length=300)

class BulkAssignDriverIn(BaseModel):
    order_ids: List[str] = Field(min_length=1, max_length=200)
    driver_id: str

class DriverDeliverIn(BaseModel):
    payment: str = "cash"

    @field_validator("payment")
    @classmethod
    def validate_driver_payment(cls, value: str) -> str:
        if value not in {"cash", "credit"}:
            raise ValueError("Payment must be cash or credit.")
        return value


class DriverLocationIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    accuracy_meters: Optional[float] = Field(default=None, ge=0, le=2000)

class StoreCreditTermsIn(BaseModel):
    credit_limit: float = Field(ge=0, le=100000000)
    payment_due_days: int = Field(ge=1, le=365)

class OrderPaymentIn(BaseModel):
    amount: float = Field(gt=0, le=100000000)
    method: str
    reference: str = Field(default="", max_length=160)
    note: str = Field(default="", max_length=500)

    @field_validator("method")
    @classmethod
    def validate_payment_method(cls, value: str) -> str:
        if value not in {"cash", "bank_transfer"}:
            raise ValueError("Payment method must be cash or bank transfer.")
        return value


RETURN_REASONS = ("damaged", "wrong_item", "expired", "quality_issue", "other")


class ReturnRequestIn(BaseModel):
    order_id: str = Field(min_length=1, max_length=100)
    product_id: str = Field(min_length=1, max_length=100)
    quantity: int = Field(ge=1, le=100000)
    reason: str
    comment: str = Field(default="", max_length=1000)

    @field_validator("reason")
    @classmethod
    def validate_return_reason(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in RETURN_REASONS:
            raise ValueError("Unsupported return reason.")
        return value


class ReturnDecisionIn(BaseModel):
    decision: str
    comment: str = Field(default="", max_length=1000)

    @field_validator("decision")
    @classmethod
    def validate_return_decision(cls, value: str) -> str:
        value = value.strip().upper()
        if value not in {"APPROVED", "REJECTED"}:
            raise ValueError("Decision must be APPROVED or REJECTED.")
        return value

class MessageIn(BaseModel):
    to_id: str
    text: str
    order_id: Optional[str] = ""

class ContactIn(BaseModel):
    contact_id: Optional[str] = Field(default=None, max_length=100)
    name: str = Field(min_length=1, max_length=160)
    phone: str = Field(default="", max_length=40)
    role: str = Field(default="other", max_length=40)
    kind: str = Field(default="manual", max_length=20)

    @field_validator("name", "phone", "role", "kind")
    @classmethod
    def clean_contact_text(cls, value: str) -> str:
        return value.strip()

class ProfileIn(BaseModel):
    name: Optional[str] = None
    business_name: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    city: Optional[str] = None
    cities: Optional[List[str]] = None
    identification_number: Optional[str] = None
    establishment_type: Optional[str] = None
    establishment_type_other: Optional[str] = None
    category: Optional[str] = None
    category_ids: Optional[List[str]] = None
    business_sectors: Optional[List[str]] = None
    card_number: Optional[str] = None
    card_expiry: Optional[str] = None
    bank_name: Optional[str] = None
    iban: Optional[str] = None
    bank_accounts: Optional[List[Dict[str, str]]] = None
    accountant_email: Optional[str] = None
    vat_registered: Optional[bool] = None

    @field_validator("cities")
    @classmethod
    def validate_cities_list(cls, v):
        return None if v is None else _validate_cities(v)

    @field_validator("city")
    @classmethod
    def validate_single_city(cls, v):
        return None if v is None else ((_validate_cities(v, allow_all=False) or [""])[0] if v else "")

class CommissionIn(BaseModel):
    enabled: bool = True
    customCommissionType: Optional[str] = None   # percent | fixed
    customCommissionValue: Optional[float] = Field(default=None, ge=0, le=1000000)
    commissionPayer: Optional[str] = None        # supplier | retailer | split


class SettingsIn(BaseModel):
    fee_type: str = "percent"       # percent | fixed
    fee_value: float = 5.0          # percent (%) or fixed amount (₾)
    fee_payer: str = "supplier"     # supplier | retailer | split
    issuer_name: Optional[str] = None
    issuer_tax_id: Optional[str] = None
    issuer_iban: Optional[str] = None
    billing_overdue_limit: Optional[float] = Field(default=None, ge=0, le=100000000)
    billing_overdue_days: Optional[int] = Field(default=None, ge=0, le=365)
    billing_reminder_days: Optional[int] = Field(default=None, ge=0, le=30)
    payment_provider: Optional[str] = None          # tbc | bog | stripe
    payment_client_id: Optional[str] = Field(default=None, max_length=200)
    payment_secret: Optional[str] = Field(default=None, max_length=500)  # write-only; blank keeps the stored secret
    payment_split_enabled: Optional[bool] = None

PLATFORM_FEE_PERCENT = 3.0
SECRET_SETTING_FIELDS = ("payment_secret_enc",)


def _settings_cipher():
    from cryptography.fernet import Fernet
    key = os.environ.get("PAYMENT_SETTINGS_KEY", "").strip()
    if not key:
        key = base64.urlsafe_b64encode(hashlib.sha256(("payment-settings:" + JWT_SECRET).encode()).digest()).decode()
    return Fernet(key.encode())


def encrypt_secret(value: str) -> str:
    return _settings_cipher().encrypt(value.encode()).decode()


def decrypt_secret(token: str) -> str:
    try:
        return _settings_cipher().decrypt(token.encode()).decode()
    except Exception:
        return ""


def public_settings(s: dict, include_sensitive: bool = False) -> dict:
    """Settings safe to return to clients: the gateway secret is never exposed."""
    out = {k: v for k, v in s.items() if k not in SECRET_SETTING_FIELDS}
    if not include_sensitive:
        out.pop("issuer_iban", None)
    out["payment_secret_set"] = bool(s.get("payment_secret_enc"))
    out.setdefault("payment_provider", "tbc")
    out.setdefault("payment_client_id", "")
    out["payment_split_enabled"] = bool(s.get("payment_split_enabled"))
    return out


def gateway_credentials(settings: dict, gateway: str) -> Optional[dict]:
    """Admin-stored credentials for the gateway, or None to use environment configuration."""
    if settings.get("payment_provider") != gateway:
        return None
    client_id = (settings.get("payment_client_id") or "").strip()
    secret = decrypt_secret(settings.get("payment_secret_enc") or "")
    if not client_id or not secret:
        return None
    return {"client_id": client_id, "client_secret": secret}


def is_external_order(o: dict) -> bool:
    return o.get("source") == "external" or bool(o.get("external_order"))


def compute_platform_split(amount, settings: dict, source: str = "app") -> Optional[dict]:
    if source != "app" or not settings.get("payment_split_enabled"):
        return None
    platform_amount = moneylib.percent_of(amount, PLATFORM_FEE_PERCENT)
    split = {"percent": PLATFORM_FEE_PERCENT, "platform_amount": moneylib.as_json(platform_amount),
             "supplier_amount": moneylib.as_json(moneylib.q(amount) - platform_amount),
             "platform_iban": settings.get("issuer_iban", "")}
    return _encrypt_sensitive_fields({"platform_split": split})["platform_split"]

class CategoryIn(BaseModel):
    name: str


def mask_card(number: str) -> str:
    digits = "".join(ch for ch in (number or "") if ch.isdigit())
    return digits[-4:] if len(digits) >= 4 else ""


GEORGIAN_BANKS = [
    "საქართველოს ბანკი", "თიბისი ბანკი", "ლიბერთი ბანკი", "პროკრედიტ ბანკი",
    "ტერაბანკი", "ბაზისბანკი", "კრედო ბანკი", "ხალიკ ბანკი", "ვითიბი ბანკი",
]


def _validate_bank_name(value) -> str:
    v = (value or "").strip()
    if v and v not in GEORGIAN_BANKS:
        raise HTTPException(422, "აირჩიეთ ბანკი სიიდან")
    return v


def _validate_iban(value) -> str:
    v = re.sub(r"\s+", "", value or "").upper()
    if v and not re.fullmatch(r"GE\d{2}[A-Z]{2}\d{16}", v):
        raise HTTPException(422, "IBAN უნდა იყოს ფორმატით GE00XX0000000000000000 (22 სიმბოლო)")
    return v

async def get_settings() -> dict:
    s = await db.settings.find_one({"id": "platform"}, {"_id": 0})
    if not s:
        s = {"id": "platform", "fee_type": "percent", "fee_value": 5.0, "fee_payer": "supplier"}
        await db.settings.insert_one(dict(s))
    changed = {}
    for k, v in {"issuer_name": "Distro Logistics LLC", "issuer_tax_id": "400123456",
                 "issuer_iban": "GE00DL0000000000001234"}.items():
        if not s.get(k):
            s[k] = v
            changed[k] = v
        stored_value = _encrypt_sensitive_fields({"issuer_iban": s[k]})["issuer_iban"] if k == "issuer_iban" else s[k]
        if stored_value != s[k]:
            s[k] = stored_value
            changed[k] = stored_value
    if changed:
        await db.settings.update_one({"id": "platform"}, {"$set": changed})
    return _decrypt_sensitive_fields(s)

def compute_fee(total: float, s: dict) -> float:
    if s["fee_type"] == "fixed":
        return moneylib.as_json(moneylib.q(s["fee_value"]))
    return moneylib.as_json(moneylib.percent_of(total, s["fee_value"]))


def resolve_commission(settings: dict, store: Optional[dict], supplier: Optional[dict]) -> dict:
    """Platform defaults, overridden by the store's custom commission, then the supplier's."""
    resolved = {k: settings[k] for k in ("fee_type", "fee_value", "fee_payer")}
    resolved["fee_source"] = "platform"
    for source, party in (("store", store), ("supplier", supplier)):
        if party and party.get("customCommissionType") in ("percent", "fixed") \
                and party.get("customCommissionValue") is not None:
            resolved.update(fee_type=party["customCommissionType"],
                            fee_value=float(party["customCommissionValue"]), fee_source=source)
            break
    for party in (store, supplier):
        if party and party.get("commissionPayer") in ("supplier", "retailer", "split"):
            resolved["fee_payer"] = party["commissionPayer"]
            break
    return resolved


async def notify(user_id: str, text: str, ntype: str = "info", order_id: Optional[str] = None,
                 invoice_id: Optional[str] = None, notification_id: Optional[str] = None,
                 product_id: Optional[str] = None, distributor_id: Optional[str] = None,
                 negotiation_id: Optional[str] = None, broadcast_id: Optional[str] = None):
    notification = {
        "id": notification_id or str(uuid.uuid4()), "user_id": user_id, "text": text,
        "type": ntype, "read": False, "created_at": now_iso()
    }
    if order_id:
        notification["order_id"] = order_id
    if invoice_id:
        notification["invoice_id"] = invoice_id
    if product_id:
        notification["product_id"] = product_id
        if ntype == "product_offer":
            notification["productId"] = product_id
    if distributor_id:
        notification["distributor_id"] = distributor_id
        if ntype == "product_offer":
            notification["distributorId"] = distributor_id
    if negotiation_id:
        notification["negotiation_id"] = negotiation_id
    if broadcast_id:
        notification["broadcast_id"] = broadcast_id
    if notification_id:
        result = await db.notifications.update_one(
            {"id": notification_id}, {"$setOnInsert": notification}, upsert=True
        )
        is_new = result.upserted_id is not None
    else:
        await db.notifications.insert_one(notification)
        is_new = True
    if is_new:
        web_push.schedule(db, notification)

def clean(doc):
    doc.pop("_id", None)
    return doc


def public_user_document(document: dict) -> dict:
    user = _decrypt_sensitive_fields(dict(document))
    for field in ("_id", "password_hash", "card_token", "payment_cards", "card_sim_status"):
        user.pop(field, None)
    return user


ALL_CITY_TOKENS = {"all", "all cities", "ყველა", "ყველა ქალაქი"}

# Latin spellings (legacy data) map onto the canonical Georgian city names used by the UI lists.
CITY_ALIASES = {
    "tbilisi": "თბილისი", "batumi": "ბათუმი", "kutaisi": "ქუთაისი", "rustavi": "რუსთავი",
    "gori": "გორი", "khashuri": "ხაშური", "zugdidi": "ზუგდიდი", "poti": "ფოთი",
    "senaki": "სენაკი", "telavi": "თელავი", "akhaltsikhe": "ახალციხე",
    "kobuleti": "ქობულეთი", "ozurgeti": "ოზურგეთი", "marneuli": "მარნეული",
}


GEORGIAN_CITIES = [
    "თბილისი", "ბათუმი", "ქუთაისი", "რუსთავი", "გორი", "ზუგდიდი", "ფოთი", "ხაშური", "სამტრედია",
    "სენაკი", "ზესტაფონი", "მარნეული", "თელავი", "ახალციხე", "ქობულეთი", "ოზურგეთი", "კასპი",
    "ჭიათურა", "წყალტუბო", "საგარეჯო", "გარდაბანი", "ბორჯომი", "თერჯოლა", "ახალქალაქი", "ქარელი",
    "ლანჩხუთი", "დუშეთი", "მცხეთა", "საჩხერე", "დედოფლისწყარო", "ლაგოდეხი", "ახმეტა", "ყვარელი",
    "გურჯაარი", "სიღნაღი", "წნორი", "თიანეთი", "ბოლნისი", "დმანისი", "წალკა", "თეთრიწყარო",
    "ახალგორი", "ბაღდათი", "ვანი", "ტყიბული", "ხონი", "წალენჯიხა", "ხობი", "აბაშა", "მარტვილი",
    "ჩოხატაური", "ხელვაჩაური", "ქედა", "შუახევი", "ხულო", "კარელი", "ადიგენი", "ასპინძა",
    "ამბროლაური", "ონი", "ცაგერი", "ლენტეხი", "მესტია", "ნინოწმინდა", "ბაკურიანი", "გუდაური",
    "ყაზბეგი", "ჯავა",
]
_GEORGIAN_CITIES_CF = {c.casefold(): c for c in GEORGIAN_CITIES}


def _canon_city(value) -> str:
    clean = " ".join(str(value or "").split())
    return CITY_ALIASES.get(clean.casefold(), clean)


def _validate_cities(values, allow_all: bool = True) -> List[str]:
    """Strict server-side check: every value must be a known Georgian city (or 'All')."""
    if isinstance(values, str):
        values = [values]
    out = []
    for value in values or []:
        city = _canon_city(value)
        if not city:
            continue
        if city.casefold() in ALL_CITY_TOKENS:
            if not allow_all:
                raise ValueError("'All' is not allowed here")
            return ["All"]
        known = _GEORGIAN_CITIES_CF.get(city.casefold())
        if not known:
            raise ValueError(f"Unknown city: {city}")
        if known not in out:
            out.append(known)
    return out


def _parse_city_filter(city: Optional[str] = None, cities: Optional[str] = None) -> List[str]:
    """Merge the legacy single `city` param and comma-separated `cities` into canonical names ('All' dropped)."""
    raw = [*str(cities or "").split(","), *str(city or "").split(",")]
    out = []
    for value in raw:
        value = _canon_city(value)
        if value and value.casefold() not in ALL_CITY_TOKENS and value.casefold() not in {c.casefold() for c in out}:
            out.append(value)
    return out


def _normalize_service_cities(cities, fallback_city=None) -> List[str]:
    if isinstance(cities, str):
        cities = [cities]
    values = cities if isinstance(cities, list) else []
    cleaned = []
    for value in values:
        city = _canon_city(value)
        if city:
            cleaned.append(city)
    if not cleaned and fallback_city:
        fallback = _canon_city(fallback_city)
        if fallback:
            cleaned.append(fallback)
    if any(city.casefold() in ALL_CITY_TOKENS for city in cleaned):
        return ["All"]
    unique = {}
    for city in cleaned:
        unique.setdefault(city.casefold(), city)
    return list(unique.values())


def _supplier_cities(supplier: dict) -> List[str]:
    return _normalize_service_cities(supplier.get("cities"), supplier.get("city"))


def _supplier_serves_any_city(supplier: dict, cities: List[str]) -> bool:
    return not cities or any(_supplier_serves_city(supplier, c) for c in cities)


def _supplier_serves_city(supplier: dict, city: Optional[str]) -> bool:
    requested = _canon_city(city).casefold()
    if not requested or requested in ALL_CITY_TOKENS:
        return True
    supplied = _supplier_cities(supplier)
    return any(value.casefold() == "all" or value.casefold() == requested for value in supplied)


# ---------- auth ----------
log = logging.getLogger("distro.auth")

DISPOSABLE_DOMAINS = {
    "mailinator.com", "yopmail.com", "guerrillamail.com", "10minutemail.com", "tempmail.com",
    "temp-mail.org", "trashmail.com", "getnada.com", "dispostable.com", "sharklasers.com",
    "fakeinbox.com", "maildrop.cc", "throwawaymail.com", "mailnesia.com", "mohmal.com",
    "emailondeck.com", "spam4.me", "guerrillamailblock.com", "grr.la", "tmpmail.org",
}


def is_disposable_email(email: str) -> bool:
    return email.rsplit("@", 1)[-1].lower() in DISPOSABLE_DOMAINS


def gen_otp() -> str:
    return f"{random.randint(0, 999999):06d}"


def hash_otp(code: str) -> str:
    return hashlib.sha256((code.strip() + JWT_SECRET).encode()).hexdigest()


async def issue_otp(email: str, name: str) -> None:
    code = gen_otp()
    await db.email_otps.update_one({"email": email}, {"$set": {
        "email": email, "code_hash": hash_otp(code),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        "attempts": 0, "last_sent": now_iso(),
    }}, upsert=True)
    if os.environ.get("APP_ENV", "").strip().lower() in {"development", "dev", "test", "testing"}:
        log.info(f"[OTP] Verification code for {email}: {code}")
    await try_send_email(to=email, subject="Your Distro Logistics verification code",
                         html=otp_email_html(code, name))


@api.post("/auth/register")
async def register(body: RegisterIn, request: Request):
    email = body.email.lower()
    if body.role not in ("retailer", "supplier"):
        raise HTTPException(400, "Invalid role")
    category_ids, category_names = await _resolve_supplier_categories(body.category_ids if body.role == "supplier" else [])
    if is_disposable_email(email):
        raise HTTPException(400, "Disposable or temporary email addresses are not allowed.")
    if await db.users.find_one({"email": email}):
        raise HTTPException(400, "Email already registered")
    if not (body.identification_number or "").strip():
        raise HTTPException(400, "Identification number is required")
    if not body.accept_terms:
        raise HTTPException(400, "You must accept the Terms of Service and Privacy Policy to create an account.")
    terms_version = "2026-06-01"
    accepted_at = now_iso()
    xff = request.headers.get("x-forwarded-for", "")
    client_ip = xff.split(",")[0].strip() if xff else (request.client.host if request.client else "")
    uid = str(uuid.uuid4())
    user = {
        "id": uid, "email": email, "password_hash": hash_password(body.password),
        "name": body.name, "role": body.role, "business_name": body.business_name or body.name,
        "address": body.address or "", "phone": body.phone or "", "city": _canon_city(body.city),
        "cities": _normalize_service_cities(body.cities, body.city) if body.role == "supplier" else [],
        "identification_number": body.identification_number.strip(),
        "establishment_type": body.establishment_type or "",
        "establishment_type_other": body.establishment_type_other or "",
        "category": ", ".join(category_names) if category_names else (body.category or ""),
        "category_ids": category_ids,
        "business_sectors": body.business_sectors if body.role == "supplier" else [],
        "servedSectors": body.business_sectors if body.role == "supplier" else [],
        "card_name": body.card_name or "" if body.role != "supplier" else "",
        "card_last4": mask_card(body.card_number) if body.role != "supplier" else "",
        "card_expiry": body.card_expiry or "" if body.role != "supplier" else "",
        "bank_name": _validate_bank_name(body.bank_name) if body.role == "supplier" else "",
        "iban": _validate_iban(body.iban) if body.role == "supplier" else "",
        "vat_registered": body.vat_registered,
        "status": "pending" if body.role == "supplier" else "active",
        "email_verified": False,
        "terms_accepted": True, "terms_accepted_at": accepted_at,
        "terms_accepted_ip": client_ip, "terms_version": terms_version,
        "created_at": now_iso(),
    }
    if body.role == "retailer":
        user.update({"store_access_role": "global_admin", "branch_role": "Global Admin"})
        user["entityGroup"] = _entity_group_for_type(body.establishment_type)
        user["is_retail"] = user["entityGroup"] == "RETAIL"
    await db.users.insert_one(_encrypt_sensitive_fields(user))
    await _ensure_admin_contacts(uid)
    await db.terms_acceptances.insert_one({
        "id": str(uuid.uuid4()), "user_id": uid, "email": email, "role": body.role,
        "terms_version": terms_version, "accepted_at": accepted_at, "ip": client_ip,
        "user_agent": request.headers.get("user-agent", ""),
    })
    await issue_otp(email, body.name)
    return {"verification_required": True, "email": email}


@api.post("/auth/verify-otp")
async def verify_otp(body: VerifyOtpIn):
    email = body.email.lower()
    rec = await db.email_otps.find_one({"email": email})
    user = await db.users.find_one({"email": email})
    if not rec or not user:
        raise HTTPException(400, "No pending verification for this email")
    if datetime.fromisoformat(rec["expires_at"]) < datetime.now(timezone.utc):
        raise HTTPException(400, "Code expired. Please request a new one.")
    if rec.get("attempts", 0) >= 5:
        raise HTTPException(429, "Too many attempts. Please request a new code.")
    if not secrets.compare_digest(rec["code_hash"], hash_otp(body.code)):
        await db.email_otps.update_one({"email": email}, {"$inc": {"attempts": 1}})
        raise HTTPException(400, "Invalid verification code")
    await db.users.update_one({"id": user["id"]}, {"$set": {"email_verified": True}})
    await db.email_otps.delete_one({"email": email})
    if user["role"] == "supplier":
        user.setdefault("supplier_access_role", "global_admin")
        user["branch_role"] = "Global Admin"
        for a in await db.users.find({"role": "admin"}).to_list(10):
            await notify(a["id"], f"დასადასტურებლად ახალი მომწოდებელი დარეგისტრირდა: „{user['business_name']}“", "approval")
    elif user["role"] == "retailer":
        user.setdefault("store_access_role", "global_admin")
        user["branch_role"] = {
            "global_admin": "Global Admin",
            "branch_manager": "Branch Manager",
            "staff": "Staff",
        }.get(user["store_access_role"], "Staff")
        user["permissions"] = effective_store_permissions(user)
    token = create_token(user["id"], user)
    u = public_user_document(user)
    u["email_verified"] = True
    return {"token": token, "user": u}


@api.post("/auth/resend-otp")
async def resend_otp(body: ResendIn):
    email = body.email.lower()
    user = await db.users.find_one({"email": email})
    if not user:
        raise HTTPException(404, "Email not found")
    if user.get("email_verified"):
        raise HTTPException(400, "Email already verified")
    rec = await db.email_otps.find_one({"email": email})
    if rec and rec.get("last_sent"):
        if (datetime.now(timezone.utc) - datetime.fromisoformat(rec["last_sent"])).total_seconds() < 45:
            raise HTTPException(429, "Please wait a moment before requesting another code.")
    await issue_otp(email, user.get("name", ""))
    return {"sent": True, "email": email}


@api.post("/auth/login")
async def login(body: LoginIn):
    user = await db.users.find_one({"email": body.email.lower()})
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password")
    if user.get("email_verified") is False:
        await issue_otp(user["email"], user.get("name", ""))
        raise HTTPException(403, "EMAIL_NOT_VERIFIED")
    if user.get("role") == "retailer" and user.get("active") is False:
        raise HTTPException(403, "Store staff account is inactive.")
    if user.get("role") == "supplier" and user.get("active") is False:
        raise HTTPException(403, "Distributor staff account is inactive.")
    if user.get("must_change_password"):
        raise HTTPException(403, {"code": "PASSWORD_RESET_REQUIRED", "email": user["email"]})
    if user.get("role") == "supplier":
        user.setdefault("supplier_access_role", "branch_manager" if user.get("supplier_id") else "global_admin")
        if user["supplier_access_role"] == "branch_manager" and not user.get("assigned_branch_id"):
            raise HTTPException(403, "A branch manager must be assigned to a warehouse.")
        user["branch_role"] = "Branch Manager" if user["supplier_access_role"] == "branch_manager" else "Global Admin"
    elif user.get("role") == "retailer":
        user.setdefault("store_access_role", "global_admin")
        user["branch_role"] = {
            "global_admin": "Global Admin",
            "branch_manager": "Branch Manager",
            "staff": "Staff",
        }.get(user["store_access_role"], "Staff")
        user["permissions"] = effective_store_permissions(user)
    token = create_token(user["id"], user)
    return {"token": token, "user": public_user_document(user)}


@api.post("/auth/staff-first-password")
async def staff_first_password(body: StaffFirstPasswordIn):
    email = body.email.lower()
    user = await db.users.find_one({
        "email": email, "role": {"$in": ["supplier", "retailer"]}, "must_change_password": True,
    })
    if not user or not verify_password(body.temporary_password, user.get("password_hash", "")):
        raise HTTPException(401, "Invalid invitation credentials.")
    if user["role"] == "supplier" and (
        user.get("active") is False or not user.get("assigned_branch_id")
    ):
        raise HTTPException(403, "This distributor invitation is inactive or has no assigned warehouse.")
    password_hash = hash_password(body.new_password)
    await db.users.update_one(
        {"id": user["id"], "must_change_password": True},
        {"$set": {"password_hash": password_hash, "must_change_password": False,
                  "password_changed_at": now_iso()}},
    )
    user.update({"must_change_password": False, "password_hash": password_hash})
    if user["role"] == "supplier":
        user.setdefault("supplier_access_role", "branch_manager")
        user["branch_role"] = "Branch Manager"
    else:
        user.setdefault("store_access_role", "staff")
        user["branch_role"] = "Branch Manager" if user["store_access_role"] == "branch_manager" else "Staff"
        user["permissions"] = effective_store_permissions(user)
    token = create_token(user["id"], user)
    return {"token": token, "user": public_user_document(user)}


@api.get("/supplier/warehouses")
async def list_supplier_warehouses(user: dict = Depends(require_role("supplier"))):
    require_supplier_permission(user, "inventory")
    owner_id = supplier_owner_id(user)
    query = {"supplier_id": owner_id}
    if user.get("supplier_access_role") == "branch_manager":
        if not user.get("assigned_branch_id"):
            raise HTTPException(403, "A branch manager must be assigned to a warehouse.")
        query["id"] = user["assigned_branch_id"]
    warehouses = await db.supplier_warehouses.find(query, {"_id": 0}).sort("created_at", 1).to_list(500)
    warehouse_ids = [warehouse["id"] for warehouse in warehouses]
    inventory_rows = await db.warehouse_inventory.find(
        {"supplier_id": owner_id, "warehouse_id": {"$in": warehouse_ids}}, {"_id": 0},
    ).to_list(10000) if warehouse_ids else []
    product_ids = list({row["product_id"] for row in inventory_rows})
    products = await db.products.find(
        {"supplier_id": owner_id, "id": {"$in": product_ids}}, {"_id": 0, "id": 1, "name": 1},
    ).to_list(len(product_ids)) if product_ids else []
    product_names = {product["id"]: product.get("name", "") for product in products}
    by_warehouse = {}
    for row in inventory_rows:
        by_warehouse.setdefault(row["warehouse_id"], []).append({
            "product_id": row["product_id"], "name": product_names.get(row["product_id"], ""),
            "stock": int(row.get("stock", 0)),
        })
    for warehouse in warehouses:
        warehouse["stock_items"] = by_warehouse.get(warehouse["id"], [])
    return warehouses


@api.post("/supplier/warehouses")
async def create_supplier_warehouse(
    body: SupplierWarehouseIn, user: dict = Depends(require_role("supplier")),
):
    if user.get("supplier_access_role", "global_admin") != "global_admin":
        raise HTTPException(403, "Only the distributor owner can manage warehouses.")
    owner_id = supplier_owner_id(user)
    existing = await db.supplier_warehouses.find_one({
        "supplier_id": owner_id, "city_lower": body.city.casefold(),
    }, {"_id": 0, "id": 1})
    if existing:
        raise HTTPException(409, "A warehouse is already registered for this city.")
    warehouse_id = str(uuid.uuid4())
    now = now_iso()
    warehouse = {
        "id": warehouse_id, "supplier_id": owner_id, **body.model_dump(),
        "servedCities": body.servedCities or [body.city],
        "city_lower": body.city.casefold(), "created_at": now, "updated_at": now,
    }
    if body.is_default:
        await db.supplier_warehouses.update_many(
            {"supplier_id": owner_id}, {"$set": {"is_default": False}},
        )
    await db.supplier_warehouses.insert_one(dict(warehouse))
    return warehouse


@api.put("/supplier/warehouses/{warehouse_id}")
async def update_supplier_warehouse(
    warehouse_id: str, body: SupplierWarehouseIn,
    user: dict = Depends(require_role("supplier")),
):
    if user.get("supplier_access_role") != "global_admin":
        raise HTTPException(403, "Only the distributor owner can manage warehouses.")
    owner_id = supplier_owner_id(user)
    duplicate = await db.supplier_warehouses.find_one({
        "supplier_id": owner_id, "city_lower": body.city.casefold(), "id": {"$ne": warehouse_id},
    }, {"_id": 0, "id": 1})
    if duplicate:
        raise HTTPException(409, "A warehouse is already registered for this city.")
    if body.is_default:
        await db.supplier_warehouses.update_many(
            {"supplier_id": owner_id}, {"$set": {"is_default": False}},
        )
    result = await db.supplier_warehouses.update_one(
        {"id": warehouse_id, "supplier_id": owner_id},
        {"$set": {
            **body.model_dump(),
            "servedCities": body.servedCities or [body.city],
            "city_lower": body.city.casefold(),
            "updated_at": now_iso(),
        }},
    )
    if not result.matched_count:
        raise HTTPException(404, "Warehouse not found.")
    return await db.supplier_warehouses.find_one({"id": warehouse_id}, {"_id": 0})


async def _delete_supplier_warehouse(warehouse_id: str, user: dict):
    if user.get("supplier_access_role") != "global_admin":
        raise HTTPException(403, "Only the distributor owner can manage warehouses.")
    owner_id = supplier_owner_id(user)
    warehouse = await db.supplier_warehouses.find_one(
        {"id": warehouse_id, "supplier_id": owner_id}, {"_id": 0, "id": 1},
    )
    if not warehouse:
        raise HTTPException(404, "Warehouse not found.")
    active_orders = await db.orders.count_documents({
        "supplier_id": owner_id, "warehouse_id": warehouse_id,
        "status": {"$in": ["Pending", "Processing", "In Transit"]},
    })
    if active_orders:
        raise HTTPException(409, "ფილიალს აქვს აქტიური შეკვეთები და ვერ წაიშლება.")
    debt, open_orders = await outstanding_debt({"supplier_id": owner_id, "warehouse_id": warehouse_id})
    if debt > 0:
        await log_financial_event(
            "warehouse_delete_blocked", user, "warehouse", warehouse_id,
            before={"debt": debt, "open_orders": open_orders},
        )
        raise HTTPException(
            409,
            f"საწყობის წაშლა შეუძლებელია, რადგან მასზე ფიქსირდება დავალიანება/ნისია (₾{debt:.2f}, "
            f"{open_orders} შეკვეთა). წაშლა დაშვებულია მხოლოდ დავალიანების სრულად დაფარვის შემდეგ.",
        )
    await log_financial_event("warehouse_deleted", user, "warehouse", warehouse_id, before={"debt": 0.0})
    await db.warehouse_inventory.delete_many({"supplier_id": owner_id, "warehouse_id": warehouse_id})
    await db.products.update_many(
        {"supplier_id": owner_id, "warehouse_id": warehouse_id}, {"$set": {"warehouse_id": None}},
    )
    await db.supplier_warehouses.delete_one({"id": warehouse_id, "supplier_id": owner_id})
    return {"status": "deleted", "id": warehouse_id}


@api.delete("/supplier/warehouses/{warehouse_id}")
async def delete_supplier_warehouse(warehouse_id: str, user: dict = Depends(require_role("supplier"))):
    return await _delete_supplier_warehouse(warehouse_id, user)


@api.delete("/warehouses/{warehouse_id}")
async def delete_warehouse_alias(warehouse_id: str, user: dict = Depends(require_role("supplier"))):
    return await _delete_supplier_warehouse(warehouse_id, user)


@api.get("/supplier/warehouses/transfers")
async def list_warehouse_transfers(
    warehouse_id: Optional[str] = None, user: dict = Depends(require_role("supplier")),
):
    require_supplier_permission(user, "transfers")
    owner_id = supplier_owner_id(user)
    query = {"supplier_id": owner_id}
    selected_id = await supplier_warehouse_id(user, warehouse_id)
    if selected_id:
        query["$or"] = [{"from_warehouse_id": selected_id}, {"to_warehouse_id": selected_id}]
    return await db.warehouse_transfers.find(query, {"_id": 0}).sort("created_at", -1).to_list(200)


@api.post("/supplier/warehouses/transfers")
async def transfer_warehouse_stock(
    body: WarehouseTransferIn, user: dict = Depends(require_role("supplier")),
):
    if user.get("supplier_access_role") != "global_admin":
        raise HTTPException(403, "Only the distributor owner can transfer stock between warehouses.")
    owner_id = supplier_owner_id(user)
    if body.from_warehouse_id == body.to_warehouse_id:
        raise HTTPException(422, "Choose two different warehouses.")
    warehouses = await db.supplier_warehouses.find({
        "supplier_id": owner_id, "id": {"$in": [body.from_warehouse_id, body.to_warehouse_id]},
        "active": True,
    }, {"_id": 0, "id": 1}).to_list(2)
    if {warehouse["id"] for warehouse in warehouses} != {body.from_warehouse_id, body.to_warehouse_id}:
        raise HTTPException(404, "Both transfer warehouses must exist and be active.")
    product = await db.products.find_one(
        {"id": body.product_id, "supplier_id": owner_id}, {"_id": 0, "id": 1, "name": 1},
    )
    if not product:
        raise HTTPException(404, "Product not found.")
    source = await db.warehouse_inventory.find_one({
        "supplier_id": owner_id, "product_id": body.product_id, "warehouse_id": body.from_warehouse_id,
    }, {"_id": 0})
    if not source or int(source.get("stock", 0)) < body.quantity:
        raise HTTPException(409, "Insufficient stock at the source warehouse.")
    result = await db.warehouse_inventory.update_one(
        {"supplier_id": owner_id, "product_id": body.product_id, "warehouse_id": body.from_warehouse_id,
         "stock": {"$gte": body.quantity}},
        {"$inc": {"stock": -body.quantity}, "$set": {"updated_at": now_iso()}},
    )
    if not result.modified_count:
        raise HTTPException(409, "Stock changed during transfer. Refresh and try again.")
    await db.warehouse_inventory.update_one(
        {"supplier_id": owner_id, "product_id": body.product_id, "warehouse_id": body.to_warehouse_id},
        {"$inc": {"stock": body.quantity}, "$set": {"updated_at": now_iso()},
         "$setOnInsert": {"id": str(uuid.uuid4()), "supplier_id": owner_id,
                          "product_id": body.product_id, "warehouse_id": body.to_warehouse_id}},
        upsert=True,
    )
    transfer = {
        "id": str(uuid.uuid4()), "supplier_id": owner_id, "product_id": body.product_id,
        "product_name": product.get("name", ""), "from_warehouse_id": body.from_warehouse_id,
        "to_warehouse_id": body.to_warehouse_id, "quantity": body.quantity,
        "note": body.note, "created_by": user["id"], "created_at": now_iso(),
    }
    await db.warehouse_transfers.insert_one(dict(transfer))
    return transfer


class CentralStockAssignIn(BaseModel):
    warehouse_id: str
    product_ids: Optional[List[str]] = None


@api.post("/supplier/warehouses/assign-central-stock")
async def assign_central_stock(
    body: CentralStockAssignIn, user: dict = Depends(require_role("supplier")),
):
    """Move products held in the central (warehouse-less) pool into a specific warehouse."""
    if user.get("supplier_access_role", "global_admin") != "global_admin":
        raise HTTPException(403, "Only the distributor owner can assign stock to warehouses.")
    owner_id = supplier_owner_id(user)
    warehouse = await db.supplier_warehouses.find_one(
        {"id": body.warehouse_id, "supplier_id": owner_id, "active": True}, {"_id": 0, "id": 1},
    )
    if not warehouse:
        raise HTTPException(404, "Warehouse not found.")
    query = {"supplier_id": owner_id, "$or": [{"warehouse_id": None}, {"warehouse_id": {"$exists": False}}, {"warehouse_id": ""}]}
    if body.product_ids is not None:
        query["id"] = {"$in": body.product_ids}
    products = await db.products.find(query, {"_id": 0, "id": 1, "stock": 1}).to_list(None)
    assigned = 0
    for product in products:
        claimed = await db.products.update_one(
            {"id": product["id"], "supplier_id": owner_id, "$or": query["$or"]},
            {"$set": {"warehouse_id": body.warehouse_id}},
        )
        if not claimed.modified_count:
            continue
        await db.warehouse_inventory.update_one(
            {"supplier_id": owner_id, "product_id": product["id"], "warehouse_id": body.warehouse_id},
            {"$inc": {"stock": int(product.get("stock", 0) or 0)}, "$set": {"updated_at": now_iso()},
             "$setOnInsert": {"id": str(uuid.uuid4()), "supplier_id": owner_id,
                              "product_id": product["id"], "warehouse_id": body.warehouse_id}},
            upsert=True,
        )
        assigned += 1
    return {"status": "assigned", "warehouse_id": body.warehouse_id, "assigned_count": assigned}


@api.get("/supplier/staff")
async def list_supplier_staff(user: dict = Depends(require_role("supplier"))):
    if user.get("supplier_access_role") != "global_admin":
        raise HTTPException(403, "Only the distributor owner can manage staff.")
    staff = await db.users.find(
        {"supplier_id": supplier_owner_id(user), "supplier_access_role": "branch_manager"},
        {"_id": 0, "password_hash": 0},
    ).sort("created_at", -1).to_list(500)
    for member in staff:
        operational = set(member.get("operational_permissions", []))
        member["branch_id"] = member.get("assigned_branch_id", "")
        member["permissions"] = {
            "orders": "orders" in operational,
            "inventory": "inventory" in operational,
            "transfers": "transfers" in operational,
            "deliveries": bool(operational.intersection({"drivers", "routes", "deliveries"})),
        }
    return staff


@api.post("/supplier/staff")
async def create_supplier_staff(
    body: SupplierStaffIn, user: dict = Depends(require_role("supplier")),
):
    if user.get("supplier_access_role") != "global_admin":
        raise HTTPException(403, "Only the distributor owner can manage staff.")
    owner_id = supplier_owner_id(user)
    email = body.email.lower()
    if await db.users.find_one({"email": email}, {"_id": 0, "id": 1}):
        raise HTTPException(409, "An account with this email already exists.")
    warehouse = await db.supplier_warehouses.find_one(
        {"id": body.branch_id, "supplier_id": owner_id, "active": True}, {"_id": 0, "id": 1},
    )
    if not warehouse:
        raise HTTPException(404, "Assigned warehouse not found or inactive.")
    temporary_password = secrets.token_urlsafe(12)
    staff = {
        "id": str(uuid.uuid4()), "email": email, "password_hash": hash_password(temporary_password),
        "name": body.name, "business_name": body.name, "role": "supplier",
        "supplier_id": owner_id, "supplier_access_role": "branch_manager",
        "assigned_branch_id": body.branch_id, "branch_id": body.branch_id,
        "operational_permissions": body.resolved_permissions(),
        "permissions": body.permissions or {},
        "phone": body.phone, "active": body.active,
        "must_change_password": True, "email_verified": True, "status": "active",
        "created_at": now_iso(),
    }
    await db.users.insert_one(dict(staff))
    await _ensure_admin_contacts(staff["id"])
    delivered = await try_send_email(
        to=email,
        subject="Distro Logistics branch manager invitation",
        html=(
            f"<p>Hello {html_escape(body.name)},</p>"
            "<p>Your distributor branch manager account is ready. Sign in with your email and the "
            f"temporary password below. You will be required to change it at first sign-in.</p>"
            f"<p><strong>Temporary password:</strong> {html_escape(temporary_password)}</p>"
        ),
    )
    staff.pop("password_hash", None)
    staff["invitation_email_sent"] = delivered
    staff["temporary_password"] = temporary_password
    return staff


@api.put("/supplier/staff/{staff_id}")
async def update_supplier_staff(
    staff_id: str, body: SupplierStaffIn, user: dict = Depends(require_role("supplier")),
):
    if user.get("supplier_access_role") != "global_admin":
        raise HTTPException(403, "Only the distributor owner can manage staff.")
    owner_id = supplier_owner_id(user)
    warehouse = await db.supplier_warehouses.find_one(
        {"id": body.branch_id, "supplier_id": owner_id, "active": True}, {"_id": 0, "id": 1},
    )
    if not warehouse:
        raise HTTPException(404, "Assigned warehouse not found or inactive.")
    existing = await db.users.find_one(
        {"id": staff_id, "supplier_id": owner_id, "supplier_access_role": "branch_manager"},
        {"_id": 0, "id": 1},
    )
    if not existing:
        raise HTTPException(404, "Staff member not found.")
    duplicate = await db.users.find_one({"email": body.email.lower(), "id": {"$ne": staff_id}}, {"_id": 0, "id": 1})
    if duplicate:
        raise HTTPException(409, "An account with this email already exists.")
    await db.users.update_one({"id": staff_id}, {"$set": {
        "name": body.name, "business_name": body.name, "email": body.email.lower(),
        "assigned_branch_id": body.branch_id, "branch_id": body.branch_id,
        "operational_permissions": body.resolved_permissions(),
        "permissions": body.permissions or {},
        "phone": body.phone, "active": body.active,
        "updated_at": now_iso(),
    }})
    staff = await db.users.find_one({"id": staff_id}, {"_id": 0})
    return public_user_document(staff)


@api.post("/forgot-password")
async def forgot_password(body: ForgotPasswordIn):
    email = str(body.email).strip().lower()
    user = await db.users.find_one({"email": email}, {"_id": 0, "id": 1, "email": 1, "name": 1})
    if user:
        now = datetime.now(timezone.utc)
        recent_reset = await db.password_resets.find_one({
            "email": email, "created_at": {"$gt": now - timedelta(seconds=60)},
        })
        if not recent_reset:
            code = f"{secrets.randbelow(1_000_000):06d}"
            code_hash = hash_otp(code)
            await db.password_resets.delete_many({"email": email})
            await db.password_resets.insert_one({
                "user_id": user["id"], "email": email, "code_hash": code_hash,
                "expires_at": now + timedelta(minutes=10), "created_at": now, "attempts": 0,
            })
            app_env = os.getenv("APP_ENV", "").casefold()
            debug_reset_code = os.getenv("PASSWORD_RESET_DEBUG", "").casefold() in {"1", "true", "yes"}
            if app_env in {"development", "dev", "test", "testing"} or debug_reset_code:
                print(f"[password-reset test code] {email}: {code}", flush=True)
            sent = await try_send_email(
                to=user["email"], subject="Your Distro Logistics password reset code",
                html=password_reset_otp_email_html(code, user.get("name", "")),
            )
            if not sent:
                await db.password_resets.delete_one({"email": email, "code_hash": code_hash})
    return {"message": "If an account exists for that email, a password reset code has been sent."}


@api.post("/reset-password")
async def reset_password(body: ResetPasswordIn):
    email = str(body.email).strip().lower()
    now = datetime.now(timezone.utc)
    reset = await db.password_resets.find_one({"email": email})
    expires_at = reset.get("expires_at") if reset else None
    if expires_at is not None:
        expires_at = expires_at.replace(tzinfo=timezone.utc) if expires_at.tzinfo is None else expires_at.astimezone(timezone.utc)
    if not reset or expires_at <= now or reset.get("attempts", 0) >= 5:
        if reset:
            await db.password_resets.delete_one({"email": email})
        raise HTTPException(400, "This password reset code is invalid or has expired.")
    if not secrets.compare_digest(hash_otp(body.code), reset["code_hash"]):
        if reset.get("attempts", 0) + 1 >= 5:
            await db.password_resets.delete_one({"email": email, "code_hash": reset["code_hash"]})
        else:
            await db.password_resets.update_one(
                {"email": email, "code_hash": reset["code_hash"], "expires_at": {"$gt": now}},
                {"$inc": {"attempts": 1}},
            )
        raise HTTPException(400, "This password reset code is invalid or has expired.")
    consumed = await db.password_resets.find_one_and_delete({
        "email": email, "code_hash": reset["code_hash"],
        "expires_at": {"$gt": now}, "attempts": {"$lt": 5},
    })
    if not consumed:
        raise HTTPException(400, "This password reset code is invalid or has expired.")
    result = await db.users.update_one(
        {"id": consumed["user_id"]},
        {"$set": {"password_hash": hash_password(body.password)}},
    )
    if result.matched_count == 0:
        raise HTTPException(400, "This password reset code is invalid or has expired.")
    await db.password_resets.delete_many({"email": email})
    return {"message": "Password reset successfully. You can now sign in."}

@api.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    if user.get("role") == "retailer":
        # Backfills accounts created before entityGroup existed (and staff inherit the owner's type).
        group = user.get("entityGroup")
        if group not in ("RETAIL", "SERVICE"):
            group = _entity_group_for_type(await _entity_type_for_user(user))
        user = {**user, "entityGroup": group, "is_retail": group == "RETAIL"}
    return {k: v for k, v in user.items() if k not in ("payment_cards", "card_token")}


# ---------- products ----------
async def _apply_regional_product_stock(products: List[dict], city: Optional[str] = None,
                                        warehouse_id: Optional[str] = None,
                                        fallback_address: Optional[str] = None) -> List[dict]:
    if not products:
        return products
    warehouse_collection = getattr(db, "supplier_warehouses", None)
    inventory_collection = getattr(db, "warehouse_inventory", None)
    if warehouse_collection is None:
        requested_city = _canon_city(city).casefold()
        city_filtered = bool(requested_city and requested_city not in ALL_CITY_TOKENS)
        if city_filtered or warehouse_id and warehouse_id not in {"all", ""}:
            for product in products:
                product["warehouse_id"] = None
                product["stock"] = 0
        return products
    supplier_ids = list({product.get("supplier_id") for product in products if product.get("supplier_id")})
    warehouses = await warehouse_collection.find(
        {"supplier_id": {"$in": supplier_ids}, "active": True}, {"_id": 0},
    ).sort("is_default", -1).to_list(3000)
    warehouses_by_supplier = {}
    for warehouse in warehouses:
        warehouses_by_supplier.setdefault(warehouse.get("supplier_id"), []).append(warehouse)
    requested_city = _canon_city(city).casefold()
    city_filtered = bool(requested_city and requested_city not in ALL_CITY_TOKENS)
    routed_by_supplier = {}
    if warehouse_id and warehouse_id not in {"all", ""}:
        routed_by_supplier = {
            supplier_id: warehouse_id for supplier_id in supplier_ids
            if any(
                warehouse.get("id") == warehouse_id
                for warehouse in warehouses_by_supplier.get(supplier_id, [])
            )
        }
    elif city_filtered:
        for supplier_id in supplier_ids:
            selected = next(
                (warehouse for warehouse in warehouses_by_supplier.get(supplier_id, [])
                 if _warehouse_serves_city(warehouse, city)),
                None,
            )
            if selected:
                routed_by_supplier[supplier_id] = selected["id"]
    elif fallback_address:
        for supplier_id in supplier_ids:
            routed = await _warehouse_for_supplier_location(supplier_id, fallback_address)
            if routed:
                routed_by_supplier[supplier_id] = routed

    selected_warehouse_ids = set(routed_by_supplier.values())
    product_ids = [product["id"] for product in products if product.get("id")]
    stock_query = {
        "supplier_id": {"$in": supplier_ids},
        "product_id": {"$in": product_ids},
    }
    if selected_warehouse_ids:
        stock_query["warehouse_id"] = {"$in": list(selected_warehouse_ids)}
    elif city_filtered or warehouse_id and warehouse_id not in {"all", ""}:
        stock_query["warehouse_id"] = {"$in": []}
    stock_rows = (
        await inventory_collection.find(stock_query, {"_id": 0}).to_list(10000)
        if product_ids and inventory_collection is not None else []
    )
    stock_by_product = {}
    for stock in stock_rows:
        supplier_id = stock.get("supplier_id")
        selected_id = routed_by_supplier.get(supplier_id)
        if selected_id:
            if stock.get("warehouse_id") != selected_id:
                continue
            stock_by_product[stock["product_id"]] = (int(stock.get("stock", 0)), stock.get("warehouse_id"))
        else:
            current, _warehouse = stock_by_product.get(stock["product_id"], (0, None))
            stock_by_product[stock["product_id"]] = (current + int(stock.get("stock", 0)), None)
    for product in products:
        routed = routed_by_supplier.get(product.get("supplier_id"))
        if routed:
            regional_stock = stock_by_product.get(product.get("id"))
            if regional_stock:
                product["warehouse_id"] = routed
                product["stock"] = regional_stock[0]
            else:
                product["warehouse_id"] = None
                product["stock"] = 0
            continue
        if product.get("id") in stock_by_product:
            product["stock"], product["warehouse_id"] = stock_by_product[product["id"]]
        else:
            product["warehouse_id"] = None
            if city_filtered or warehouse_id and warehouse_id not in {"all", ""} or fallback_address:
                product["stock"] = 0
    return products


def _warehouse_served_cities(warehouse: dict) -> List[str]:
    cities = warehouse.get("servedCities")
    if not isinstance(cities, list):
        return []
    return [_canon_city(city).casefold() for city in cities if city]


def _warehouse_serves_city(warehouse: dict, city: Optional[str]) -> bool:
    normalized_city = _canon_city(city).casefold()
    return bool(normalized_city and normalized_city in _warehouse_served_cities(warehouse))


async def _regional_warehouses_by_supplier(supplier_ids: List[str], city: str) -> dict:
    warehouse_collection = getattr(db, "supplier_warehouses", None)
    if warehouse_collection is None or not supplier_ids:
        return {}
    warehouses = await warehouse_collection.find(
        {"supplier_id": {"$in": supplier_ids}, "active": True}, {"_id": 0},
    ).sort("is_default", -1).to_list(3000)
    result = {}
    for warehouse in warehouses:
        supplier_id = warehouse.get("supplier_id")
        if supplier_id and supplier_id not in result and _warehouse_serves_city(warehouse, city):
            result[supplier_id] = warehouse.get("id")
    return {supplier_id: warehouse_id for supplier_id, warehouse_id in result.items() if warehouse_id}


async def _store_routing_address(user: dict, branch_id: Optional[str], delivery_address: str) -> str:
    owner_id = store_owner_id(user)
    if branch_id:
        branch = await db.store_branches.find_one({"id": branch_id, "retailer_id": owner_id}, {"_id": 0, "address": 1, "city": 1})
        if branch and branch.get("address"):
            return f"{branch['address']} {branch.get('city') or ''}".strip()
    if user.get("city"):
        return f"{delivery_address} {user['city']}"
    return delivery_address


async def _store_city(user: dict, branch_id: Optional[str] = None) -> Optional[str]:
    owner_id = store_owner_id(user)
    if branch_id:
        branch = await db.store_branches.find_one(
            {"id": branch_id, "retailer_id": owner_id}, {"_id": 0, "city": 1},
        )
        if branch and branch.get("city"):
            return _canon_city(branch["city"])
    city = user.get("city")
    if not city and owner_id != user.get("id"):
        owner = await db.users.find_one({"id": owner_id}, {"_id": 0, "city": 1})
        city = (owner or {}).get("city")
    return _canon_city(city) if city else None


async def _warehouse_for_supplier_location(
    supplier_id: str, address: str, city: Optional[str] = None,
) -> Optional[str]:
    warehouse_collection = getattr(db, "supplier_warehouses", None)
    if warehouse_collection is None:
        return None
    warehouses = await warehouse_collection.find(
        {"supplier_id": supplier_id, "active": True}, {"_id": 0},
    ).sort("is_default", -1).to_list(500)
    if city:
        matching = [warehouse for warehouse in warehouses if _warehouse_serves_city(warehouse, city)]
        return matching[0]["id"] if matching else None
    normalized_address = " ".join(str(address or "").split()).casefold()
    matching_warehouses = []
    for warehouse in warehouses:
        raw_cities = warehouse.get("servedCities")
        if not isinstance(raw_cities, list) or not raw_cities:
            raw_cities = [warehouse.get("city")]
        city_names = {
            " ".join(str(value or "").split()).casefold()
            for raw_city in raw_cities if raw_city
            for value in (raw_city, _canon_city(raw_city))
        }
        for city_name in city_names:
            if city_name and city_name in normalized_address:
                matching_warehouses.append((len(city_name), warehouse))
    if matching_warehouses:
        return max(matching_warehouses, key=lambda match: match[0])[1]["id"]
    return next((warehouse["id"] for warehouse in warehouses if warehouse.get("is_default")), None) or (
        warehouses[0]["id"] if warehouses else None
    )


async def reserve_product_stock(supplier_id: str, product_id: str, warehouse_id: Optional[str], quantity: int) -> bool:
    inventory = getattr(db, "warehouse_inventory", None)
    if inventory is not None and warehouse_id:
        result = await inventory.update_one(
            {"supplier_id": supplier_id, "product_id": product_id, "warehouse_id": warehouse_id,
             "stock": {"$gte": quantity}},
            {"$inc": {"stock": -quantity}, "$set": {"updated_at": now_iso()}},
        )
        if result.modified_count:
            return True
        return False
    result = await db.products.update_one(
        {"id": product_id, "supplier_id": supplier_id, "stock": {"$gte": quantity}},
        {"$inc": {"stock": -quantity}},
    )
    return bool(result.modified_count)


async def available_product_stock(supplier_id: str, product_id: str, warehouse_id: Optional[str], fallback: int) -> int:
    inventory = getattr(db, "warehouse_inventory", None)
    if inventory is not None and warehouse_id:
        stock = await inventory.find_one(
            {"supplier_id": supplier_id, "product_id": product_id, "warehouse_id": warehouse_id},
            {"_id": 0, "stock": 1},
        )
        if stock:
            return int(stock.get("stock", 0) or 0)
        return 0
    return int(fallback or 0)


async def release_product_stock(supplier_id: str, product_id: str, warehouse_id: Optional[str], quantity: int) -> None:
    inventory = getattr(db, "warehouse_inventory", None)
    if inventory is not None and warehouse_id:
        result = await inventory.update_one(
            {"supplier_id": supplier_id, "product_id": product_id, "warehouse_id": warehouse_id},
            {"$inc": {"stock": quantity}, "$set": {"updated_at": now_iso()}},
        )
        if result.modified_count:
            return
        return
    await db.products.update_one(
        {"id": product_id, "supplier_id": supplier_id}, {"$inc": {"stock": quantity}},
    )


SALE_SOURCES = ("app", "external")


async def deduct_inventory(
    lines: list, sale_source: str = "app", reference: str = "",
    out_of_stock_detail: str = "Insufficient stock. Refresh availability and try again.",
) -> list:
    """Central stock deduction shared by app checkouts and external sales sync.

    Each line is {supplier_id, product_id, warehouse_id, quantity}. Deduction is atomic per line;
    if any line fails, every line already deducted is restored and a 409 is raised.
    """
    if sale_source not in SALE_SOURCES:
        raise ValueError("Unknown sale source.")
    deducted = []
    for line in lines:
        ok = await reserve_product_stock(
            line["supplier_id"], line["product_id"], line.get("warehouse_id"), line["quantity"],
        )
        if not ok:
            await restore_inventory(deducted)
            raise HTTPException(409, out_of_stock_detail)
        deducted.append({
            "supplier_id": line["supplier_id"], "product_id": line["product_id"],
            "warehouse_id": line.get("warehouse_id"), "quantity": line["quantity"],
        })
    movements = getattr(db, "inventory_movements", None)
    if movements is not None and deducted:
        await movements.insert_many([{
            "id": str(uuid.uuid4()), "type": "sale", "sale_source": sale_source, "reference": reference,
            "supplier_id": d["supplier_id"], "product_id": d["product_id"],
            "warehouse_id": d["warehouse_id"], "quantity": -d["quantity"], "created_at": now_iso(),
        } for d in deducted])
    return deducted


async def restore_inventory(lines: list) -> None:
    for line in lines:
        await release_product_stock(
            line["supplier_id"], line["product_id"], line.get("warehouse_id"), line["quantity"],
        )


async def _supplier_logo_map(supplier_ids) -> dict:
    """Map supplier id -> logo_url (None when no logo uploaded) in a single query."""
    ids = list({sid for sid in supplier_ids if sid})
    users = getattr(db, "users", None)
    if not ids or users is None:
        return {}
    rows = await users.find({"id": {"$in": ids}}, {"_id": 0, "id": 1, "logo_url": 1}).to_list(len(ids))
    return {u["id"]: u.get("logo_url") or None for u in rows}


async def _attach_supplier_logos(docs: List[dict]) -> List[dict]:
    logos_by_id = await _supplier_logo_map(d.get("supplier_id") for d in docs)
    for d in docs:
        d["supplier_logo"] = logos_by_id.get(d.get("supplier_id"))
    return docs


@api.get("/products")
async def list_products(category: Optional[str] = None, supplier_id: Optional[str] = None,
                        search: Optional[str] = None, availability: Optional[str] = None,
                        city: Optional[str] = None, cities: Optional[str] = None,
                        warehouse_id: Optional[str] = None,
                        user: Optional[dict] = Depends(get_current_user)):
    selected_warehouse_id = None
    if user and user.get("role") == "supplier":
        require_supplier_permission(user, "inventory")
        supplier_id = supplier_owner_id(user)
        selected_warehouse_id = await supplier_warehouse_id(user, warehouse_id)
    elif user and user.get("role") != "retailer":
        selected_warehouse_id = warehouse_id
    is_retailer = bool(user and user.get("role") == "retailer")
    serving_ids = None
    retailer_city = await _retailer_city(user)
    city_filter = [retailer_city] if retailer_city else _parse_city_filter(city, cities)
    if is_retailer and city_filter:
        city_filter = city_filter[:1]
    city = city_filter[0] if len(city_filter) == 1 else None
    if is_retailer and not city:
        return []
    regional_warehouse_ids = None
    if user and user.get("role") == "retailer":
        entity_type = await _entity_type_for_user(user)
        if entity_type:
            serving_ids = await _serving_supplier_ids(entity_type)
    if supplier_id and user and user.get("role") == "retailer":
        entity_type = await _entity_type_for_user(user)
        if entity_type:
            supplier = await db.users.find_one(
                {"id": supplier_id, "role": "supplier"},
                {"_id": 0, "business_sectors": 1, "servedSectors": 1},
            )
            if not supplier or not _supplier_serves_entity(supplier, entity_type):
                return []
    q = {}
    if category and category not in ("All Products", "all"):
        q["category"] = category
    if city_filter:
        suppliers = await db.users.find({"role": "supplier"}, {"_id": 0, "id": 1, "city": 1, "cities": 1}).to_list(1000)
        if is_retailer:
            regional_warehouse_ids = await _regional_warehouses_by_supplier(
                [supplier["id"] for supplier in suppliers], city,
            )
            matching_supplier_ids = list(regional_warehouse_ids)
        else:
            warehouse_collection = getattr(db, "supplier_warehouses", None)
            warehouses = await warehouse_collection.find(
                {"active": True}, {"_id": 0, "supplier_id": 1, "city": 1, "servedCities": 1},
            ).to_list(3000) if warehouse_collection is not None else []
            warehouse_supplier_ids = {
                warehouse["supplier_id"] for warehouse in warehouses
                if warehouse.get("supplier_id") and any(
                    _warehouse_serves_city(warehouse, requested_city) for requested_city in city_filter
                )
            }
            matching_supplier_ids = [
                supplier["id"] for supplier in suppliers
                if _supplier_serves_any_city(supplier, city_filter) or supplier["id"] in warehouse_supplier_ids
            ]
        if supplier_id:
            if supplier_id not in matching_supplier_ids:
                return []
            q["supplier_id"] = supplier_id
        else:
            if not matching_supplier_ids:
                return []
            q["supplier_id"] = {"$in": matching_supplier_ids}
    elif supplier_id:
        q["supplier_id"] = supplier_id
    if serving_ids is not None:
        current = q.get("supplier_id")
        if isinstance(current, dict):
            serving_ids = [sid for sid in serving_ids if sid in current["$in"]]
        elif current:
            serving_ids = [sid for sid in serving_ids if sid == current]
        if not serving_ids:
            return []
        q["supplier_id"] = {"$in": serving_ids}
    if search and search.strip():
        search_pattern = re.escape(search.strip())
        q["$or"] = [
            {"name": {"$regex": search_pattern, "$options": "i"}},
            {"supplier_name": {"$regex": search_pattern, "$options": "i"}},
        ]
    docs = await db.products.find(q, {"_id": 0}).to_list(500)
    for product in docs:
        if not str(product.get("category") or "").strip():
            product["category"] = classify_product_category(product.get("name", "")) or "Other"
    is_supplier = bool(user and user.get("role") == "supplier")
    docs = await _apply_regional_product_stock(
        docs, city if not is_supplier else None, selected_warehouse_id,
        (user or {}).get("city") if is_retailer else None,
    )
    if regional_warehouse_ids is not None:
        docs = [
            product for product in docs
            if product.get("supplier_id") in regional_warehouse_ids
            and product.get("warehouse_id") == regional_warehouse_ids[product["supplier_id"]]
        ]
    if user and user.get("role") == "supplier" and selected_warehouse_id:
        scoped_products = await db.warehouse_inventory.find(
            {"supplier_id": supplier_owner_id(user), "warehouse_id": selected_warehouse_id},
            {"_id": 0, "product_id": 1},
        ).to_list(10000)
        allowed_product_ids = {stock["product_id"] for stock in scoped_products}
        docs = [product for product in docs if product["id"] in allowed_product_ids]
    if availability == "in_stock":
        docs = [product for product in docs if int(product.get("stock", 0) or 0) > 0]
    if user and user.get("role") == "retailer" and docs:
        allowed_categories = await _allowed_categories_for_user(user)
        docs = [p for p in docs if _category_allowed(p.get("category", "Other"), allowed_categories)]
    if not is_supplier and docs:
        declared_by_supplier = await _declared_category_names(list({p.get("supplier_id") for p in docs if p.get("supplier_id")}))
        docs = [
            p for p in docs
            if p.get("supplier_id") not in declared_by_supplier
            or p.get("category", "Other") in declared_by_supplier[p["supplier_id"]]
        ]
    if user and user.get("role") == "retailer":
        docs = await _apply_partner_pricing(docs, store_owner_id(user))
    for product in docs:
        product.pop("applied_return_ids", None)
    return await _attach_supplier_logos(docs)


# ---------- Private B2B partner connections & custom pricing ----------
CONNECTION_STATUSES = ("PENDING", "APPROVED", "REJECTED")


class ConnectionRequestIn(BaseModel):
    distributor_id: str = Field(min_length=1)


class ConnectionInviteIn(BaseModel):
    store_id: str = Field(min_length=1)


class ConnectionInvitationResponseIn(BaseModel):
    connection_id: str = Field(min_length=1)
    status: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, value):
        value = (value or "").upper()
        if value not in {"APPROVED", "REJECTED"}:
            raise ValueError("status must be APPROVED or REJECTED")
        return value


async def log_connection_event(connection: dict, actor: dict, action: str,
                               previous_status: Optional[str], next_status: Optional[str]) -> None:
    await connection_audit_logs.insert_one({
        "id": str(uuid.uuid4()), "connection_id": connection.get("id"),
        "store_id": connection.get("store_id"), "distributor_id": connection.get("distributor_id"),
        "action": action, "previous_status": previous_status, "next_status": next_status,
        "actor_id": actor.get("id"), "actor_role": actor.get("role"), "at": now_iso(),
    })


class CustomPriceIn(BaseModel):
    product_id: str = Field(min_length=1)
    custom_price: float = Field(ge=0)


class ConnectionApproveIn(BaseModel):
    store_id: str = Field(min_length=1)
    status: str = "APPROVED"
    discount_percent: Optional[float] = Field(default=None, ge=0, le=100)
    custom_prices: List[CustomPriceIn] = []

    @field_validator("status")
    @classmethod
    def _valid_status(cls, v):
        v = (v or "").upper()
        if v not in ("APPROVED", "REJECTED"):
            raise ValueError("status must be APPROVED or REJECTED")
        return v


def _locked_product(product: dict) -> dict:
    product["price"] = None
    product["price_per_unit"] = None
    product["tier_pricing"] = []
    product["isLocked"] = True
    return product


def _offer_history_event(offer: dict, action: str, actor: Optional[dict], at: str) -> dict:
    return {
        "id": str(uuid.uuid4()), "offer_id": offer.get("id"),
        "distributor_id": offer.get("distributor_id"), "store_id": offer.get("store_id"),
        "product_id": offer.get("product_id"), "offer_price": offer.get("offer_price"),
        "created_at": offer.get("created_at"), "expiresAt": offer.get("expiresAt"),
        "action": action, "actor_id": (actor or {}).get("id"),
        "actor_role": (actor or {}).get("role"), "at": at,
    }


async def _expire_product_offers(
    distributor_id: Optional[str] = None,
    store_id: Optional[str] = None,
    distributor_ids: Optional[List[str]] = None,
) -> None:
    offers = getattr(db, "product_offers", None)
    history = getattr(db, "product_offer_history", None)
    if offers is None:
        return
    now = datetime.now(timezone.utc).isoformat()
    query = {"status": "active", "expiresAt": {"$lte": now}}
    if distributor_id:
        query["distributor_id"] = distributor_id
    elif distributor_ids is not None:
        query["distributor_id"] = {"$in": distributor_ids}
    if store_id:
        query["store_id"] = store_id
    expired = await offers.find(query, {"_id": 0}).to_list(5000)
    for offer in expired:
        result = await offers.update_one(
            {"id": offer["id"], "status": "active"},
            {"$set": {"status": "expired", "updated_at": now}},
        )
        if result.modified_count and history is not None:
            await history.insert_one(_offer_history_event(offer, "expired", None, now))


async def _apply_partner_pricing(products: List[dict], store_id: str) -> List[dict]:
    """Expose list prices to all stores; apply private terms only after approval."""
    connections = await db.store_distributor_connections.find(
        {"store_id": store_id},
        {"_id": 0, "distributor_id": 1, "status": 1, "discount_percent": 1},
    ).to_list(5000)
    connection_status = {c["distributor_id"]: c.get("status") for c in connections}
    approved = {
        c["distributor_id"]: moneylib.dec(c.get("discount_percent") or 0)
        for c in connections if c.get("status") == "APPROVED"
    }
    custom = {
        c["product_id"]: moneylib.q(c["custom_price"])
        for c in await db.custom_prices.find(
            {"store_id": store_id, "distributor_id": {"$in": list(approved)}},
            {"_id": 0, "product_id": 1, "custom_price": 1},
        ).to_list(50000)
    } if approved else {}
    offer_collection = getattr(db, "product_offers", None)
    offers = {}
    if approved and offer_collection is not None:
        await _expire_product_offers(store_id=store_id, distributor_ids=list(approved))
        active_offers = await offer_collection.find({
            "store_id": store_id, "distributor_id": {"$in": list(approved)}, "status": "active",
        }, {"_id": 0, "distributor_id": 1, "product_id": 1, "offer_price": 1,
            "created_at": 1, "expiresAt": 1}).to_list(5000)
        offers = {(offer["distributor_id"], offer["product_id"]): offer for offer in active_offers}
    for product in products:
        distributor_id = product.get("supplier_id")
        if distributor_id not in approved:
            public_price = moneylib.as_json(moneylib.q(product.get("price_per_unit") or 0))
            product["base_price"] = public_price
            product["price"] = public_price
            product["price_per_unit"] = public_price
            product["isLocked"] = False
            product["can_order"] = False
            product["connection_status"] = connection_status.get(distributor_id)
            continue
        base_price = moneylib.q(product.get("price_per_unit") or 0)
        offer = offers.get((distributor_id, product["id"]))
        if offer:
            price = moneylib.q(offer["offer_price"])
            product["tier_pricing"] = []
            product["active_offer"] = {
                "offer_price": moneylib.as_json(price), "created_at": offer.get("created_at"),
                "expiresAt": offer.get("expiresAt"),
            }
        elif product["id"] in custom:
            price = custom[product["id"]]
            product["tier_pricing"] = []
        else:
            factor = Decimal(1) - approved[distributor_id] / Decimal(100)
            price = moneylib.q(base_price * factor)
            product["tier_pricing"] = [
                {**t, "price": moneylib.as_json(moneylib.q(moneylib.dec(t.get("price", 0)) * factor))}
                for t in product.get("tier_pricing") or []
            ]
        product["base_price"] = moneylib.as_json(base_price)
        product["price"] = moneylib.as_json(price)
        product["price_per_unit"] = moneylib.as_json(price)
        product["isLocked"] = False
        product["can_order"] = True
        product["connection_status"] = "APPROVED"
    for product in products:
        product.pop("applied_return_ids", None)
    return products


async def require_approved_distributor_connections(store_id: str, distributor_ids) -> None:
    required = {distributor_id for distributor_id in distributor_ids if distributor_id}
    if not required:
        return
    rows = await db.store_distributor_connections.find(
        {"store_id": store_id, "distributor_id": {"$in": list(required)}, "status": "APPROVED"},
        {"_id": 0, "distributor_id": 1},
    ).to_list(len(required))
    approved = {row["distributor_id"] for row in rows}
    missing = sorted(required - approved)
    if missing:
        raise HTTPException(403, {
            "code": "CONNECTION_REQUIRED",
            "message": "An approved distributor connection is required before ordering.",
            "distributor_ids": missing,
        })


def store_order_unit_price(product: dict, quantity: int) -> float:
    unit_price = moneylib.q(product.get("price_per_unit", product.get("price", 0)))
    for tier in sorted(product.get("tier_pricing") or [], key=lambda entry: int(entry.get("min_qty", 0))):
        if quantity >= int(tier.get("min_qty", 0)):
            unit_price = moneylib.q(tier.get("price", unit_price))
    return moneylib.as_json(unit_price)


@api.post("/connections/request", status_code=201)
async def request_connection(body: ConnectionRequestIn, user: dict = Depends(require_role("retailer"))):
    require_store_owner(user)
    store_id = store_owner_id(user)
    distributor = await db.users.find_one(
        {"id": body.distributor_id, "role": "supplier"}, {"_id": 0, "id": 1, "supplier_id": 1},
    )
    if not distributor or distributor.get("supplier_id"):
        raise HTTPException(404, "Distributor not found")
    existing = await db.store_distributor_connections.find_one(
        {"store_id": store_id, "distributor_id": body.distributor_id}, {"_id": 0},
    )
    if existing and existing["status"] in ("PENDING", "APPROVED"):
        raise HTTPException(409, f"Connection already {existing['status'].lower()}")
    now = now_iso()
    previous_status = existing.get("status") if existing else None
    connection = await db.store_distributor_connections.find_one_and_update(
        {"store_id": store_id, "distributor_id": body.distributor_id},
        {"$set": {
            "status": "PENDING", "requested_by_role": "retailer", "requested_by": store_id,
            "updated_at": now,
        },
         "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": now, "discount_percent": 0}},
        upsert=True, return_document=True, projection={"_id": 0},
    )
    await log_connection_event(connection, user, "request_sent", previous_status, "PENDING")
    store_name = user.get("business_name") or user.get("name") or "მაღაზია"
    await notify(
        body.distributor_id,
        f"📦 {store_name}-მ გამოგზავნა პარტნიორობის მოთხოვნა.",
        "connection_request",
    )
    return connection


@api.get("/connections/discover-stores")
async def discover_stores(
    city: Optional[str] = None,
    sector: Optional[str] = None,
    business_type: Optional[str] = None,
    search: Optional[str] = None,
    user: dict = Depends(require_role("supplier")),
):
    distributor_id = _require_distributor_owner(user)
    query = {
        "role": "retailer", "status": "active",
        "store_access_role": {"$in": ["global_admin", None]},
    }
    if city and city.strip():
        query["city"] = _canon_city(city)
    stores = await db.users.find(query, {
        "_id": 0, "id": 1, "name": 1, "business_name": 1, "city": 1,
        "establishment_type": 1, "establishment_type_other": 1, "entityGroup": 1,
        "is_retail": 1,
    }).sort("business_name", 1).to_list(5000)
    requested_sector = _normalize_business_sector(sector) if sector and sector.strip() else None
    requested_type = business_type.strip().upper() if business_type and business_type.strip() else None
    search_term = search.strip().casefold() if search and search.strip() else ""
    filtered = []
    for store in stores:
        establishment = store.get("establishment_type") or ""
        store_sector = _normalize_business_sector(establishment)
        store_type = store.get("entityGroup") or ("RETAIL" if store.get("is_retail") else _entity_group_for_type(establishment))
        if requested_sector and store_sector != requested_sector:
            continue
        if requested_type and store_type != requested_type:
            continue
        if search_term and search_term not in " ".join((store.get("business_name", ""), store.get("name", ""), establishment, store.get("city", ""))).casefold():
            continue
        store["sector"] = store_sector
        store["business_type"] = store_type
        filtered.append(store)

    connections = await db.store_distributor_connections.find({
        "distributor_id": distributor_id,
        "store_id": {"$in": [store["id"] for store in filtered]},
    }, {"_id": 0, "id": 1, "store_id": 1, "status": 1, "requested_by_role": 1}).to_list(5000) if filtered else []
    by_store = {connection["store_id"]: connection for connection in connections}
    return [{
        **store,
        "connection_id": by_store.get(store["id"], {}).get("id"),
        "connection_status": by_store.get(store["id"], {}).get("status"),
        "requested_by_role": by_store.get(store["id"], {}).get("requested_by_role"),
    } for store in filtered[:500]]


@api.post("/connections/invite", status_code=201)
async def invite_store(body: ConnectionInviteIn, user: dict = Depends(require_role("supplier"))):
    distributor_id = _require_distributor_owner(user)
    store = await db.users.find_one({
        "id": body.store_id, "role": "retailer", "status": "active",
        "store_access_role": {"$in": ["global_admin", None]},
    }, {"_id": 0, "id": 1, "business_name": 1, "name": 1})
    if not store:
        raise HTTPException(404, "Store not found.")
    existing = await db.store_distributor_connections.find_one(
        {"store_id": body.store_id, "distributor_id": distributor_id}, {"_id": 0},
    )
    if existing and existing.get("status") in {"PENDING", "APPROVED"}:
        raise HTTPException(409, f"Connection already {existing['status'].lower()}.")
    now = now_iso()
    connection = await db.store_distributor_connections.find_one_and_update(
        {"store_id": body.store_id, "distributor_id": distributor_id},
        {"$set": {
            "status": "PENDING", "requested_by_role": "supplier", "requested_by": distributor_id,
            "updated_at": now,
        }, "$setOnInsert": {
            "id": str(uuid.uuid4()), "created_at": now, "discount_percent": 0,
        }},
        upsert=True, return_document=True, projection={"_id": 0},
    )
    await log_connection_event(connection, user, "invitation_sent", existing.get("status") if existing else None, "PENDING")
    store_name = user.get("business_name") or user.get("name") or "დისტრიბუტორი"
    await notify(body.store_id, f"{store_name}-მა თანამშრომლობის მოწვევა გამოგიგზავნათ.", "connection_invitation")
    return connection


@api.patch("/connections/respond-invitation")
async def respond_to_connection_invitation(
    body: ConnectionInvitationResponseIn,
    user: dict = Depends(require_role("retailer")),
):
    require_store_owner(user)
    store_id = store_owner_id(user)
    connection = await db.store_distributor_connections.find_one({
        "id": body.connection_id, "store_id": store_id, "status": "PENDING",
        "requested_by_role": "supplier",
    }, {"_id": 0})
    if not connection:
        raise HTTPException(404, "Pending distributor invitation not found.")
    now = now_iso()
    result = await db.store_distributor_connections.update_one(
        {"id": body.connection_id, "store_id": store_id, "status": "PENDING", "requested_by_role": "supplier"},
        {"$set": {"status": body.status, "updated_at": now}},
    )
    if result.modified_count != 1:
        raise HTTPException(409, "Invitation changed. Refresh and try again.")
    await log_connection_event(connection, user, "invitation_accepted" if body.status == "APPROVED" else "invitation_rejected", "PENDING", body.status)
    await notify(
        connection["distributor_id"],
        "მაღაზიამ თანამშრომლობის მოწვევა მიიღო." if body.status == "APPROVED" else "მაღაზიამ თანამშრომლობის მოწვევა უარყო.",
        "connection_invitation_" + body.status.lower(),
    )
    return {**connection, "status": body.status, "updated_at": now}


@api.patch("/connections/approve")
async def approve_connection(body: ConnectionApproveIn, user: dict = Depends(require_role("supplier"))):
    if user.get("supplier_access_role") == "branch_manager":
        raise HTTPException(403, "Only the distributor owner can manage partner pricing.")
    distributor_id = supplier_owner_id(user)
    connection = await db.store_distributor_connections.find_one(
        {"store_id": body.store_id, "distributor_id": distributor_id}, {"_id": 0},
    )
    if not connection:
        raise HTTPException(404, "Connection request not found")
    if connection.get("status") == "PENDING" and connection.get("requested_by_role") == "supplier":
        raise HTTPException(409, "The store must respond to this distributor invitation.")
    if connection.get("status") == "REJECTED" or (connection.get("status") == "APPROVED" and body.status != "APPROVED"):
        raise HTTPException(409, "This connection cannot transition from its current status.")
    if connection.get("status") not in {"PENDING", "APPROVED"}:
        raise HTTPException(409, "This connection cannot be changed from its current status.")

    if body.custom_prices:
        product_ids = [p.product_id for p in body.custom_prices]
        owned = {
            p["id"] for p in await db.products.find(
                {"id": {"$in": product_ids}, "supplier_id": distributor_id}, {"_id": 0, "id": 1},
            ).to_list(len(product_ids))
        }
        unknown = set(product_ids) - owned
        if unknown:
            raise HTTPException(400, f"Products not owned by this distributor: {sorted(unknown)}")

    now = now_iso()
    update = {"status": body.status, "updated_at": now}
    if body.discount_percent is not None:
        update["discount_percent"] = body.discount_percent
    elif body.status == "APPROVED":
        update["discount_percent"] = 0
    result = await db.store_distributor_connections.update_one(
        {"store_id": body.store_id, "distributor_id": distributor_id, "status": connection["status"]},
        {"$set": update},
    )
    if result.modified_count != 1:
        raise HTTPException(409, "Connection changed. Refresh and try again.")
    if body.status == "APPROVED":
        await db.custom_prices.delete_many({"store_id": body.store_id, "distributor_id": distributor_id})
    if body.status == "APPROVED" and body.custom_prices:
        await db.custom_prices.bulk_write([
            UpdateOne(
                {"distributor_id": distributor_id, "store_id": body.store_id, "product_id": p.product_id},
                {"$set": {"custom_price": p.custom_price, "updated_at": now},
                 "$setOnInsert": {"id": str(uuid.uuid4())}},
                upsert=True,
            ) for p in body.custom_prices
        ])
    if connection.get("status") != body.status:
        await log_connection_event(connection, user, "request_" + body.status.lower(), connection.get("status"), body.status)
        verb = "approved" if body.status == "APPROVED" else "declined"
        verb_ka = "დადასტურდა" if verb == "approved" else "უარყოფილია"
        await notify(body.store_id, f"თქვენი პარტნიორობის მოთხოვნა {verb_ka}.", "connection_" + verb)
    return {**connection, **update}


class ConnectionRespondIn(BaseModel):
    connectionId: str = Field(min_length=1)
    status: str
    customDiscountPercent: Optional[float] = Field(default=None, ge=0, le=100)
    customPrices: List[dict] = []


@api.patch("/connections/respond")
async def respond_connection(body: ConnectionRespondIn, user: dict = Depends(require_role("supplier"))):
    distributor_id = _require_distributor_owner(user)
    connection = await db.store_distributor_connections.find_one(
        {"id": body.connectionId, "distributor_id": distributor_id}, {"_id": 0},
    )
    if not connection:
        raise HTTPException(404, "Connection request not found")
    try:
        prices = [
            CustomPriceIn(product_id=str(i.get("productId") or ""), custom_price=i.get("customPrice"))
            for i in body.customPrices
        ]
        payload = ConnectionApproveIn(
            store_id=connection["store_id"], status=body.status,
            discount_percent=body.customDiscountPercent, custom_prices=prices,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    await approve_connection(payload, user)
    return {"message": "გადაწყვეტილება წარმატებით შენახულია!"}


@api.delete("/connections/{connection_id}")
async def delete_connection(connection_id: str, user: dict = Depends(require_role("supplier", "retailer"))):
    if user["role"] == "supplier":
        side = {"distributor_id": _require_distributor_owner(user)}
    else:
        require_store_owner(user)
        side = {"store_id": store_owner_id(user)}
    connection = await db.store_distributor_connections.find_one({"id": connection_id, **side}, {"_id": 0})
    if not connection:
        raise HTTPException(404, "Connection not found")
    pair = {"store_id": connection["store_id"], "distributor_id": connection["distributor_id"]}
    await log_connection_event(connection, user, "connection_removed", connection.get("status"), "REMOVED")
    await db.custom_prices.delete_many(pair)
    await db.store_distributor_connections.delete_one({"id": connection_id})
    other_id = connection["store_id"] if user["role"] == "supplier" else connection["distributor_id"]
    await notify(other_id, "პარტნიორობა გაუქმდა.", "connection_removed")
    return {"ok": True}


class StorePricingIn(BaseModel):
    discount_percent: float = Field(default=0, ge=0, le=100)
    # custom_price None clears the override for that product
    custom_prices: List[dict] = []


class ProductOfferIn(BaseModel):
    product_id: str = Field(min_length=1)
    offer_price: float = Field(ge=0)
    store_ids: List[str] = Field(min_length=1)
    duration_days: Optional[int] = Field(default=3, ge=1, le=365)
    expires_at: Optional[datetime] = None

    @field_validator("expires_at")
    @classmethod
    def validate_expires_at(cls, value):
        if value is not None and (value.tzinfo is None or value <= datetime.now(timezone.utc)):
            raise ValueError("Offer expiry must be a future timezone-aware date.")
        return value


class PriceNegotiationIn(BaseModel):
    product_id: str = Field(min_length=1)
    quantity: int = Field(ge=1)
    proposed_price: float = Field(ge=0)
    comment: str = Field(default="", max_length=2000)


class PriceNegotiationResponseIn(BaseModel):
    action: str
    counter_price: Optional[float] = Field(default=None, ge=0)
    comment: str = Field(default="", max_length=2000)

    @field_validator("action")
    @classmethod
    def validate_action(cls, value):
        normalized = (value or "").upper()
        if normalized not in {"ACCEPT", "COUNTER", "REJECT"}:
            raise ValueError("action must be ACCEPT, COUNTER, or REJECT")
        return normalized


def _require_distributor_owner(user: dict) -> str:
    if user.get("supplier_access_role") == "branch_manager":
        raise HTTPException(403, "Only the distributor owner can manage partner pricing.")
    return supplier_owner_id(user)


@api.get("/supplier/offers/products")
async def list_offer_products(user: dict = Depends(require_role("supplier"))):
    distributor_id = _require_distributor_owner(user)
    products = await db.products.find(
        {"supplier_id": distributor_id},
        {"_id": 0, "id": 1, "name": 1, "price_per_unit": 1},
    ).to_list(5000)
    return products


@api.get("/supplier/offers")
async def list_product_offers(user: dict = Depends(require_role("supplier"))):
    distributor_id = _require_distributor_owner(user)
    await _expire_product_offers(distributor_id=distributor_id)
    offers = await db.product_offers.find(
        {"distributor_id": distributor_id}, {"_id": 0},
    ).sort("created_at", -1).to_list(2000)
    history = await db.product_offer_history.find(
        {"distributor_id": distributor_id}, {"_id": 0},
    ).sort("at", -1).to_list(2000)
    product_ids = list({row.get("product_id") for row in [*offers, *history] if row.get("product_id")})
    store_ids = list({row.get("store_id") for row in [*offers, *history] if row.get("store_id")})
    products = {
        product["id"]: product for product in await db.products.find(
            {"id": {"$in": product_ids}}, {"_id": 0, "id": 1, "name": 1},
        ).to_list(len(product_ids) or 1)
    }
    stores = {
        store["id"]: store for store in await db.users.find(
            {"id": {"$in": store_ids}}, {"_id": 0, "id": 1, "name": 1, "business_name": 1},
        ).to_list(len(store_ids) or 1)
    }
    for row in [*offers, *history]:
        row["product_name"] = products.get(row.get("product_id"), {}).get("name", row.get("product_id", ""))
        store = stores.get(row.get("store_id"), {})
        row["store_name"] = store.get("business_name") or store.get("name") or row.get("store_id", "")
    return {"offers": offers, "history": history}


@api.post("/supplier/offers", status_code=201)
async def send_product_offer(body: ProductOfferIn, user: dict = Depends(require_role("supplier"))):
    distributor_id = _require_distributor_owner(user)
    product = await db.products.find_one(
        {"id": body.product_id, "supplier_id": distributor_id},
        {"_id": 0, "id": 1, "name": 1, "price_per_unit": 1},
    )
    if not product:
        raise HTTPException(404, "Product not found")
    store_ids = list(dict.fromkeys(body.store_ids))
    connections = await db.store_distributor_connections.find(
        {"store_id": {"$in": store_ids}, "distributor_id": distributor_id, "status": "APPROVED"},
        {"_id": 0, "store_id": 1},
    ).to_list(len(store_ids))
    approved_ids = {c["store_id"] for c in connections}
    if approved_ids != set(store_ids):
        raise HTTPException(400, "Offers can only be sent to approved partner stores")

    await _expire_product_offers(distributor_id=distributor_id)
    now = now_iso()
    expires_at = body.expires_at.astimezone(timezone.utc) if body.expires_at else (
        datetime.now(timezone.utc) + timedelta(days=body.duration_days or 3)
    )
    offers_collection = db.product_offers
    history_collection = db.product_offer_history
    for store_id in store_ids:
        query = {"distributor_id": distributor_id, "store_id": store_id, "product_id": body.product_id}
        previous = await offers_collection.find_one(query, {"_id": 0})
        if previous and previous.get("status") == "active":
            await history_collection.insert_one(_offer_history_event(previous, "replaced", user, now))
        offer = {
            "id": (previous or {}).get("id") or str(uuid.uuid4()),
            **query,
            "offer_price": moneylib.as_json(moneylib.q(body.offer_price)),
            "created_at": now,
            "updated_at": now,
            "expiresAt": expires_at.isoformat(),
            "status": "active",
        }
        await offers_collection.update_one(query, {"$set": offer}, upsert=True)
        await history_collection.insert_one(_offer_history_event(offer, "sent", user, now))
    distributor = await db.users.find_one(
        {"id": distributor_id}, {"_id": 0, "business_name": 1, "name": 1},
    ) or {}
    distributor_name = distributor.get("business_name") or distributor.get("name") or "დისტრიბუტორმა"
    base_price = float(product.get("price_per_unit") or 0)
    for store_id in store_ids:
        await notify(
            store_id,
            f"🏷️ {distributor_name}-მ გამოგიგზავნათ სპეციალური შეთავაზება პროდუქტზე: "
            f"{product['name']}! ძველი ფასი: ₾{base_price:.2f} -> ახალი ფასი: ₾{body.offer_price:.2f}.",
            "product_offer",
            product_id=body.product_id,
            distributor_id=distributor_id,
            expires_at=expires_at.isoformat(),
        )
    return {"ok": True, "sent_count": len(store_ids)}


@api.delete("/supplier/offers/{offer_id}")
async def cancel_product_offer(offer_id: str, user: dict = Depends(require_role("supplier"))):
    distributor_id = _require_distributor_owner(user)
    await _expire_product_offers(distributor_id=distributor_id)
    offer = await db.product_offers.find_one({"id": offer_id, "distributor_id": distributor_id}, {"_id": 0})
    if not offer:
        raise HTTPException(404, "Product offer not found.")
    if offer.get("status") != "active":
        raise HTTPException(409, "Only an active product offer can be cancelled.")
    now = now_iso()
    result = await db.product_offers.update_one(
        {"id": offer_id, "distributor_id": distributor_id, "status": "active"},
        {"$set": {"status": "cancelled", "updated_at": now}},
    )
    if result.modified_count != 1:
        raise HTTPException(409, "Offer changed. Refresh and try again.")
    await db.product_offer_history.insert_one(_offer_history_event(offer, "cancelled", user, now))
    await notify(
        offer["store_id"], "დისტრიბუტორმა სპეციალური პროდუქტის შეთავაზება გააუქმა.",
        "product_offer_cancelled", product_id=offer["product_id"], distributor_id=distributor_id,
    )
    return {"ok": True, "status": "cancelled"}


async def _create_negotiated_order(negotiation: dict, final_price: float) -> dict:
    retailer = await db.users.find_one(
        {"id": negotiation["store_id"], "role": "retailer"}, {"_id": 0},
    )
    if not retailer:
        raise HTTPException(404, "Store not found")
    negotiation_note = f"ფასზე შეთანხმება #{negotiation['id']}"
    existing_order = await db.orders.find_one(
        {"retailer_id": negotiation["store_id"], "notes": negotiation_note}, {"_id": 0},
    )
    if existing_order:
        return existing_order
    product = await db.products.find_one(
        {"id": negotiation["product_id"], "supplier_id": negotiation["distributor_id"]},
        {"_id": 0, "id": 1, "name": 1, "image": 1, "stock": 1},
    )
    if not product:
        raise HTTPException(404, "პროდუქტი ვერ მოიძებნა")
    retailer.setdefault("business_name", retailer.get("name") or "მაღაზია")
    address = (retailer.get("address") or "").strip()
    if not address:
        raise HTTPException(400, "შეკვეთის შესაქმნელად მაღაზიის მისამართი სავალდებულოა")
    quantity = int(negotiation["quantity"])

    async def current_stock() -> int:
        branch_id = await resolve_store_branch(retailer, None)
        routing_address = await _store_routing_address(retailer, branch_id, address)
        city = await _store_city(retailer, branch_id)
        warehouse_id = await _warehouse_for_supplier_location(
            negotiation["distributor_id"], routing_address, city,
        )
        return await available_product_stock(
            negotiation["distributor_id"], product["id"], warehouse_id, product.get("stock", 0),
        )

    def insufficient_stock(stock: int) -> HTTPException:
        return HTTPException(409, f"❌ საწყობში არ არის საკმარისი რაოდენობა. მიმდინარე მარაგი: {stock} ცალი.")

    stock = await current_stock()
    if stock < quantity:
        raise insufficient_stock(stock)
    order_body = OrderIn(items=[OrderItem(
        product_id=product["id"],
        name=product["name"],
        image=product.get("image") or "",
        supplier_id=negotiation["distributor_id"],
        quantity=int(negotiation["quantity"]),
        unit_price=float(final_price),
    )], delivery_address=address, notes=negotiation_note)
    try:
        result = await create_order(order_body, retailer)
    except HTTPException as exc:
        if exc.status_code == 409 and "stock" in str(exc.detail).lower():
            raise insufficient_stock(await current_stock())
        raise
    if not result.get("orders"):
        raise HTTPException(500, "შეკვეთის შექმნა ვერ მოხერხდა")
    return result["orders"][0]


@api.post("/price-negotiations", status_code=201)
async def create_price_negotiation(body: PriceNegotiationIn, user: dict = Depends(require_role("retailer"))):
    require_store_owner(user)
    distributor_id = (await db.products.find_one(
        {"id": body.product_id}, {"_id": 0, "supplier_id": 1},
    ) or {}).get("supplier_id")
    if not distributor_id:
        raise HTTPException(404, "Product not found")
    store_id = store_owner_id(user)
    connection = await db.store_distributor_connections.find_one(
        {"store_id": store_id, "distributor_id": distributor_id, "status": "APPROVED"}, {"_id": 0, "id": 1},
    )
    if not connection:
        raise HTTPException(403, "An approved distributor connection is required to negotiate prices")
    product = await db.products.find_one(
        {"id": body.product_id, "supplier_id": distributor_id}, {"_id": 0, "name": 1},
    )
    negotiation_id = str(uuid.uuid4())
    now = now_iso()
    negotiation = {
        "id": negotiation_id,
        "store_id": store_id,
        "distributor_id": distributor_id,
        "product_id": body.product_id,
        "product_name": product["name"],
        "quantity": body.quantity,
        "proposed_price": body.proposed_price,
        "comment": body.comment.strip(),
        "status": "PENDING",
        "history": [{
            "by": "store", "action": "REQUESTED", "price": body.proposed_price,
            "comment": body.comment.strip(), "at": now,
        }],
        "created_at": now,
        "updated_at": now,
    }
    await db.price_negotiations.insert_one(dict(negotiation))
    store_name = user.get("business_name") or user.get("name") or "მაღაზია"
    await notify(
        distributor_id,
        f"💬 {store_name}-მ გამოგიგზავნათ ფასზე მოთხოვნა პროდუქტზე {product['name']}: "
        f"{body.quantity} ცალი, ₾{body.proposed_price:.2f}.",
        "negotiation_request",
        negotiation_id=negotiation_id,
    )
    return negotiation


@api.get("/supplier/price-negotiations")
async def list_supplier_price_negotiations(user: dict = Depends(require_role("supplier"))):
    distributor_id = _require_distributor_owner(user)
    negotiations = await db.price_negotiations.find(
        {"distributor_id": distributor_id, "status": "PENDING"},
        {"_id": 0},
    ).sort("updated_at", -1).to_list(2000)
    stores = {
        item["id"]: item for item in await db.users.find(
            {"id": {"$in": [n["store_id"] for n in negotiations]}},
            {"_id": 0, "id": 1, "name": 1, "business_name": 1, "email": 1, "phone": 1},
        ).to_list(2000)
    }
    return [{**n, "store": stores.get(n["store_id"], {})} for n in negotiations]


@api.get("/price-negotiations/mine")
async def list_my_price_negotiations(user: dict = Depends(require_role("retailer"))):
    store_id = store_owner_id(user)
    negotiations = await db.price_negotiations.find(
        {"store_id": store_id, "status": {"$in": ["PENDING", "COUNTERED"]}},
        {"_id": 0},
    ).sort("updated_at", -1).to_list(2000)
    distributors = {
        item["id"]: item for item in await db.users.find(
            {"id": {"$in": [n["distributor_id"] for n in negotiations]}},
            {"_id": 0, "id": 1, "name": 1, "business_name": 1},
        ).to_list(2000)
    }
    return [{**n, "distributor": distributors.get(n["distributor_id"], {})} for n in negotiations]


@api.post("/price-negotiations/{negotiation_id}/supplier-response")
async def respond_to_price_negotiation(
    negotiation_id: str,
    body: PriceNegotiationResponseIn,
    user: dict = Depends(require_role("supplier")),
):
    distributor_id = _require_distributor_owner(user)
    negotiation = await db.price_negotiations.find_one(
        {"id": negotiation_id, "distributor_id": distributor_id, "status": "PENDING"}, {"_id": 0},
    )
    if not negotiation:
        raise HTTPException(404, "Open price negotiation not found")
    now = now_iso()
    if body.action == "COUNTER":
        if body.counter_price is None:
            raise HTTPException(422, "counter_price is required for a counter-offer")
        event = {"by": "distributor", "action": "COUNTERED", "price": body.counter_price,
                 "comment": body.comment.strip(), "at": now}
        result = await db.price_negotiations.update_one(
            {"id": negotiation_id, "status": "PENDING"},
            {"$set": {"status": "COUNTERED", "counter_price": body.counter_price,
                      "counter_comment": body.comment.strip(), "updated_at": now},
             "$push": {"history": event}},
        )
        if not result.modified_count:
            raise HTTPException(409, "Price negotiation is already being handled")
        distributor = await db.users.find_one({"id": distributor_id}, {"_id": 0, "name": 1, "business_name": 1}) or {}
        distributor_name = distributor.get("business_name") or distributor.get("name") or "დისტრიბუტორმა"
        await notify(
            negotiation["store_id"],
            f"💬 {distributor_name}-მ გამოგიგზავნათ საპასუხო შეთავაზება პროდუქტზე "
            f"{negotiation['product_name']}: {body.counter_price:.2f} ₾.",
            "negotiation_counter",
            negotiation_id=negotiation_id,
        )
        return {"ok": True, "status": "COUNTERED"}
    if body.action == "REJECT":
        result = await db.price_negotiations.update_one(
            {"id": negotiation_id, "status": "PENDING"},
            {"$set": {"status": "REJECTED", "updated_at": now},
             "$push": {"history": {"by": "distributor", "action": "REJECTED", "at": now}}},
        )
        if not result.modified_count:
            raise HTTPException(409, "Price negotiation is already being handled")
        await notify(negotiation["store_id"], "დისტრიბუტორმა უარყო სპეციალური ფასის მოთხოვნა.",
                     "negotiation_rejected", negotiation_id=negotiation_id)
        return {"ok": True, "status": "REJECTED"}

    result = await db.price_negotiations.update_one(
        {"id": negotiation_id, "status": "PENDING"},
        {"$set": {"status": "PROCESSING", "agreed_price": negotiation["proposed_price"], "updated_at": now}},
    )
    if not result.modified_count:
        raise HTTPException(409, "Price negotiation is already being handled")
    try:
        order = await _create_negotiated_order(negotiation, float(negotiation["proposed_price"]))
    except Exception:
        await db.price_negotiations.update_one(
            {"id": negotiation_id, "status": "PROCESSING"}, {"$set": {"status": "PENDING", "updated_at": now_iso()}},
        )
        raise
    await db.price_negotiations.update_one(
        {"id": negotiation_id, "status": "PROCESSING"},
        {"$set": {"status": "ACCEPTED", "order_id": order["id"], "updated_at": now_iso()},
         "$push": {"history": {"by": "distributor", "action": "ACCEPTED", "price": negotiation["proposed_price"], "at": now}}},
    )
    await notify(negotiation["store_id"], f"მოთხოვნა მიღებულია. შეიქმნა შეკვეთა №{order['order_no']}.",
                 "negotiation_accepted", order_id=order["id"], negotiation_id=negotiation_id)
    return {"ok": True, "status": "ACCEPTED", "order": order}


@api.post("/price-negotiations/{negotiation_id}/store-response")
async def respond_to_supplier_counter(
    negotiation_id: str,
    body: PriceNegotiationResponseIn,
    user: dict = Depends(require_role("retailer")),
):
    require_store_owner(user)
    store_id = store_owner_id(user)
    negotiation = await db.price_negotiations.find_one(
        {"id": negotiation_id, "store_id": store_id, "status": "COUNTERED"}, {"_id": 0},
    )
    if not negotiation:
        raise HTTPException(404, "Counter-offer not found")
    now = now_iso()
    if body.action == "REJECT":
        result = await db.price_negotiations.update_one(
            {"id": negotiation_id, "status": "COUNTERED"},
            {"$set": {"status": "REJECTED", "updated_at": now},
             "$push": {"history": {"by": "store", "action": "REJECTED", "at": now}}},
        )
        if not result.modified_count:
            raise HTTPException(409, "Counter-offer is already being handled")
        await notify(negotiation["distributor_id"], "მაღაზიამ უარყო საპასუხო შეთავაზება.",
                     "negotiation_rejected", negotiation_id=negotiation_id)
        return {"ok": True, "status": "REJECTED"}
    if body.action == "COUNTER":
        if body.counter_price is None:
            raise HTTPException(422, "counter_price is required for a counter-offer")
        result = await db.price_negotiations.update_one(
            {"id": negotiation_id, "status": "COUNTERED"},
            {"$set": {"status": "PENDING", "proposed_price": body.counter_price,
                      "comment": body.comment.strip(), "updated_at": now},
             "$push": {"history": {"by": "store", "action": "COUNTERED", "price": body.counter_price,
                                   "comment": body.comment.strip(), "at": now}}},
        )
        if not result.modified_count:
            raise HTTPException(409, "Counter-offer is already being handled")
        await notify(
            negotiation["distributor_id"],
            f"💬 მაღაზიამ ხელახლა შემოგთავაზათ ფასი პროდუქტზე {negotiation['product_name']}: "
            f"{body.counter_price:.2f} ₾.",
            "negotiation_request",
            negotiation_id=negotiation_id,
        )
        return {"ok": True, "status": "PENDING"}

    result = await db.price_negotiations.update_one(
        {"id": negotiation_id, "status": "COUNTERED"},
        {"$set": {"status": "PROCESSING", "agreed_price": negotiation["counter_price"], "updated_at": now}},
    )
    if not result.modified_count:
        raise HTTPException(409, "Counter-offer is already being handled")
    try:
        order = await _create_negotiated_order(negotiation, float(negotiation["counter_price"]))
    except Exception:
        await db.price_negotiations.update_one(
            {"id": negotiation_id, "status": "PROCESSING"}, {"$set": {"status": "COUNTERED", "updated_at": now_iso()}},
        )
        raise
    await db.price_negotiations.update_one(
        {"id": negotiation_id, "status": "PROCESSING"},
        {"$set": {"status": "ACCEPTED", "order_id": order["id"], "updated_at": now_iso()},
         "$push": {"history": {"by": "store", "action": "ACCEPTED", "price": negotiation["counter_price"], "at": now}}},
    )
    await notify(negotiation["distributor_id"], f"მაღაზია დაეთანხმა შეთავაზებას. შეიქმნა შეკვეთა №{order['order_no']}.",
                 "negotiation_accepted", order_id=order["id"], negotiation_id=negotiation_id)
    return {"ok": True, "status": "ACCEPTED", "order": order}


@api.get("/connections/partners")
async def list_partner_stores(status: Optional[str] = None, user: dict = Depends(require_role("supplier"))):
    distributor_id = _require_distributor_owner(user)
    query = {"distributor_id": distributor_id}
    if status:
        if status.upper() not in CONNECTION_STATUSES:
            raise HTTPException(400, "Invalid status")
        query["status"] = status.upper()
    connections = await db.store_distributor_connections.find(query, {"_id": 0}).sort("updated_at", -1).to_list(2000)
    stores = {
        s["id"]: s for s in await db.users.find(
            {"id": {"$in": [c["store_id"] for c in connections]}},
            {"_id": 0, "id": 1, "name": 1, "business_name": 1, "city": 1, "email": 1, "phone": 1,
             "address": 1, "identification_number": 1},
        ).to_list(2000)
    }
    return [{**c, "store": stores.get(c["store_id"], {})} for c in connections]


@api.get("/connections/mine")
async def list_my_connections(user: dict = Depends(require_role("retailer"))):
    store_id = store_owner_id(user)
    connections = await db.store_distributor_connections.find({"store_id": store_id}, {"_id": 0}).to_list(2000)
    distributors = {
        d["id"]: d for d in await db.users.find(
            {"id": {"$in": [c["distributor_id"] for c in connections]}},
            {"_id": 0, "id": 1, "name": 1, "business_name": 1, "city": 1, "logo_url": 1,
             "business_sectors": 1, "servedSectors": 1},
        ).to_list(2000)
    }
    return [{**c, "distributor": distributors.get(c["distributor_id"], {})} for c in connections]


@api.get("/supplier/stores/{store_id}/pricing")
async def get_store_pricing(store_id: str, user: dict = Depends(require_role("supplier"))):
    distributor_id = _require_distributor_owner(user)
    connection = await db.store_distributor_connections.find_one(
        {"store_id": store_id, "distributor_id": distributor_id, "status": {"$in": ["PENDING", "APPROVED"]}},
        {"_id": 0},
    )
    if not connection:
        raise HTTPException(404, "Pending or approved connection not found")
    products = await db.products.find(
        {"supplier_id": distributor_id}, {"_id": 0, "id": 1, "name": 1, "image": 1, "category": 1, "price_per_unit": 1},
    ).to_list(5000)
    custom = {
        c["product_id"]: c["custom_price"] for c in await db.custom_prices.find(
            {"store_id": store_id, "distributor_id": distributor_id}, {"_id": 0, "product_id": 1, "custom_price": 1},
        ).to_list(50000)
    }
    discount = moneylib.dec(connection.get("discount_percent") or 0)
    return {
        "discount_percent": float(discount),
        "products": [
            {**p, "custom_price": custom.get(p["id"]),
             "final_price": custom.get(p["id"]) if p["id"] in custom
             else moneylib.as_json(moneylib.q(moneylib.dec(p.get("price_per_unit") or 0) * (Decimal(100) - discount) / Decimal(100)))}
            for p in products
        ],
    }


@api.put("/supplier/stores/{store_id}/pricing")
async def save_store_pricing(store_id: str, body: StorePricingIn, user: dict = Depends(require_role("supplier"))):
    distributor_id = _require_distributor_owner(user)
    connection = await db.store_distributor_connections.find_one(
        {"store_id": store_id, "distributor_id": distributor_id, "status": "APPROVED"}, {"_id": 0, "id": 1},
    )
    if not connection:
        raise HTTPException(404, "Approved connection not found")
    entries = {}
    for item in body.custom_prices:
        product_id = str(item.get("product_id") or "")
        price = item.get("custom_price")
        if price is not None:
            try:
                price = float(price)
            except (TypeError, ValueError):
                raise HTTPException(400, "Invalid custom price")
            if price < 0:
                raise HTTPException(400, "Custom price must be non-negative")
        entries[product_id] = price
    owned = {
        p["id"] for p in await db.products.find(
            {"id": {"$in": list(entries)}, "supplier_id": distributor_id}, {"_id": 0, "id": 1},
        ).to_list(len(entries) or 1)
    }
    if set(entries) - owned:
        raise HTTPException(400, "Products not owned by this distributor")
    now = now_iso()
    await db.store_distributor_connections.update_one(
        {"store_id": store_id, "distributor_id": distributor_id},
        {"$set": {"discount_percent": body.discount_percent, "updated_at": now}},
    )
    ops = []
    for product_id, price in entries.items():
        key = {"distributor_id": distributor_id, "store_id": store_id, "product_id": product_id}
        if price is None:
            ops.append(DeleteOne(key))
        else:
            ops.append(UpdateOne(
                key, {"$set": {"custom_price": price, "updated_at": now}, "$setOnInsert": {"id": str(uuid.uuid4())}},
                upsert=True,
            ))
    if ops:
        await db.custom_prices.bulk_write(ops)
    return {"ok": True}


@api.get("/cities")
async def list_georgian_cities():
    return GEORGIAN_CITIES


@api.get("/distributors/cities")
async def list_distributor_cities():
    suppliers = await db.users.find({"role": "supplier"}, {"_id": 0, "city": 1, "cities": 1}).to_list(1000)
    cities = {}
    for supplier in suppliers:
        for city in [*_supplier_cities(supplier), supplier.get("city", "")]:
            city = " ".join(str(city or "").split())
            if city.casefold() != "all":
                if city:
                    cities.setdefault(city.casefold(), city)
    warehouse_collection = getattr(db, "supplier_warehouses", None)
    warehouses = await warehouse_collection.find({"active": True}, {"_id": 0, "city": 1}).to_list(3000) if warehouse_collection is not None else []
    for warehouse in warehouses:
        city = " ".join(str(warehouse.get("city") or "").split())
        if city:
            cities.setdefault(city.casefold(), city)
    return sorted(cities.values(), key=str.casefold)


@api.get("/distributors")
async def list_distributors(category: Optional[str] = None, city: Optional[str] = None,
                            cities: Optional[str] = None,
                            search: Optional[str] = None,
                            user: Optional[dict] = Depends(get_current_user)):
    allowed_categories = await _allowed_categories_for_user(user)
    entity_type = await _entity_type_for_user(user)
    retailer_city = await _retailer_city(user)
    city_filter = [retailer_city] if retailer_city else _parse_city_filter(city, cities)
    is_retailer = bool(user and user.get("role") == "retailer")
    if is_retailer and city_filter:
        city_filter = city_filter[:1]
    if is_retailer and not city_filter:
        return []
    product_query = {}
    all_category = not category or category in ("All Products", "all")
    products = await db.products.find(product_query, {"_id": 0}).to_list(5000)
    supplier_ids = list({product.get("supplier_id") for product in products if product.get("supplier_id")})
    regional_warehouse_ids = None
    if is_retailer:
        regional_warehouse_ids = await _regional_warehouses_by_supplier(supplier_ids, city_filter[0])
        products = await _apply_regional_product_stock(products, city_filter[0])
        products = [
            product for product in products
            if product.get("supplier_id") in regional_warehouse_ids
            and product.get("warehouse_id") == regional_warehouse_ids[product["supplier_id"]]
        ]
    products_by_supplier = {}
    for product in products:
        products_by_supplier.setdefault(product.get("supplier_id"), []).append(product)

    supplier_ids = [supplier_id for supplier_id in products_by_supplier if supplier_id]
    if not supplier_ids:
        return []
    declared_by_supplier = await _declared_category_names(supplier_ids)
    suppliers = await db.users.find(
        {"id": {"$in": supplier_ids}, "role": "supplier"},
        {"_id": 0, "id": 1, "name": 1, "business_name": 1, "city": 1, "cities": 1, "logo_url": 1,
         "business_sectors": 1, "servedSectors": 1},
    ).to_list(1000)

    query = " ".join(str(search or "").split()).casefold()
    distributors = []
    for supplier in suppliers:
        if entity_type and not _supplier_serves_entity(supplier, entity_type):
            continue
        all_supplier_products = products_by_supplier.get(supplier["id"], [])
        declared = declared_by_supplier.get(supplier["id"])
        if allowed_categories is not None:
            all_supplier_products = [p for p in all_supplier_products if _category_allowed(p.get("category", "Other"), allowed_categories)]
            if declared is not None:
                declared = {c for c in declared if _category_allowed(c, allowed_categories)}
                if not declared:
                    continue
            elif not all_supplier_products:
                continue
        # A supplier with selected categories is listed only under them; otherwise fall back to its products' categories.
        if not all_category:
            if declared is not None:
                if category not in declared:
                    continue
            elif not any(product.get("category", "Other") == category for product in all_supplier_products):
                continue
        supplier_products = all_supplier_products if all_category else [
            product for product in all_supplier_products if product.get("category", "Other") == category
        ]
        if declared is not None:
            supplier_products = [p for p in supplier_products if p.get("category", "Other") in declared]
        supplier_cities = _supplier_cities(supplier)
        warehouse_collection = getattr(db, "supplier_warehouses", None)
        if regional_warehouse_ids is None:
            has_regional_warehouse = bool(city_filter and warehouse_collection is not None and await warehouse_collection.find_one({
                "supplier_id": supplier["id"], "city_lower": {"$in": [" ".join(c.split()).casefold() for c in city_filter]}, "active": True,
            }, {"_id": 0, "id": 1}))
            if not _supplier_serves_any_city(supplier, city_filter) and not has_regional_warehouse:
                continue
        business_name = supplier.get("business_name") or supplier.get("name") or ""
        if query and query not in business_name.casefold() and not any(
            query in str(product.get("name") or "").casefold() for product in supplier_products
        ):
            continue
        distributor_cities = supplier_cities or ([supplier["city"]] if supplier.get("city") else [])
        distributors.append({
            "id": supplier["id"],
            "business_name": business_name,
            "logo_url": supplier.get("logo_url") or None,
            "logo": supplier.get("logo_url") or None,
            "servedSectors": supplier.get("servedSectors") or supplier.get("business_sectors") or [],
            "city": supplier.get("city") or (distributor_cities[0] if distributor_cities else ""),
            "cities": distributor_cities,
            "categories": sorted(declared) if declared is not None else sorted({product.get("category", "Other") for product in all_supplier_products}),
            "product_count": len(supplier_products),
        })
    return sorted(distributors, key=lambda item: item["business_name"].casefold())

@api.post("/products")
async def create_product(
    body: ProductIn, warehouse_id: Optional[str] = None,
    user: dict = Depends(require_role("supplier")),
):
    require_supplier_permission(user, "inventory")
    if user.get("supplier_access_role") == "branch_manager":
        raise HTTPException(403, "Branch managers cannot create shared product records.")
    owner_id = supplier_owner_id(user)
    selected_warehouse_id = await supplier_warehouse_id(user, warehouse_id)
    warehouse_collection = getattr(db, "supplier_warehouses", None)
    if not selected_warehouse_id and warehouse_collection is not None:
        warehouse = await warehouse_collection.find_one(
            {"supplier_id": owner_id, "active": True, "is_default": True}, {"_id": 0, "id": 1},
        )
        selected_warehouse_id = warehouse["id"] if warehouse else None
    pid = str(uuid.uuid4())
    data = body.model_dump()
    data["category"], category_id = await resolve_product_category(
        data.get("name", ""), owner_id, data.get("category"),
    )
    data["category_id"] = category_id
    data["city"] = data.get("city") or user.get("city", "")
    initial_stock = data.pop("stock", 0)
    doc = {"id": pid, "supplier_id": owner_id, "supplier_name": user["business_name"],
           "warehouse_id": selected_warehouse_id, "stock": initial_stock, **data, "created_at": now_iso()}
    await db.products.insert_one(dict(doc))
    inventory_collection = getattr(db, "warehouse_inventory", None)
    if selected_warehouse_id and inventory_collection is not None:
        await inventory_collection.insert_one({
            "id": str(uuid.uuid4()), "supplier_id": owner_id, "product_id": pid,
            "warehouse_id": selected_warehouse_id, "stock": initial_stock, "updated_at": now_iso(),
        })
    return clean(doc)

@api.put("/products/{pid}")
async def update_product(
    pid: str, body: ProductIn, warehouse_id: Optional[str] = None,
    user: dict = Depends(require_role("supplier")),
):
    require_supplier_permission(user, "inventory")
    owner_id = supplier_owner_id(user)
    selected_warehouse_id = await supplier_warehouse_id(user, warehouse_id)
    warehouse_collection = getattr(db, "supplier_warehouses", None)
    prod = await db.products.find_one({"id": pid, "supplier_id": owner_id}, {"_id": 0})
    if not prod:
        raise HTTPException(404, "Product not found")
    if not selected_warehouse_id and warehouse_id is None and warehouse_collection is not None:
        if prod.get("warehouse_id"):
            selected_warehouse_id = await supplier_warehouse_id(user, prod["warehouse_id"])
        else:
            warehouse = await warehouse_collection.find_one(
                {"supplier_id": owner_id, "active": True, "is_default": True}, {"_id": 0, "id": 1},
            )
            selected_warehouse_id = warehouse["id"] if warehouse else None
    update_data = body.model_dump()
    stock_amount = update_data.pop("stock", 0)
    if warehouse_collection is None or (
        selected_warehouse_id is None and warehouse_id is None and not prod.get("warehouse_id")
    ):
        update_data["stock"] = stock_amount
    if user.get("supplier_access_role") == "branch_manager":
        await db.warehouse_inventory.update_one(
            {"supplier_id": owner_id, "product_id": pid, "warehouse_id": selected_warehouse_id},
            {"$set": {"stock": stock_amount, "updated_at": now_iso()}},
            upsert=True,
        )
        updated = dict(prod)
        updated["stock"] = stock_amount
        return updated
    update_data["category"], category_id = await resolve_product_category(
        update_data.get("name", ""), owner_id, update_data.get("category"),
    )
    update_data["category_id"] = category_id
    await db.products.update_one({"id": pid, "supplier_id": owner_id}, {"$set": update_data})
    inventory_collection = getattr(db, "warehouse_inventory", None)
    if selected_warehouse_id and inventory_collection is not None:
        await inventory_collection.update_one(
            {"supplier_id": owner_id, "product_id": pid, "warehouse_id": selected_warehouse_id},
            {"$set": {"stock": stock_amount, "updated_at": now_iso()},
             "$setOnInsert": {"id": str(uuid.uuid4()), "supplier_id": owner_id,
                              "product_id": pid, "warehouse_id": selected_warehouse_id}},
            upsert=True,
        )
    updated = await db.products.find_one({"id": pid, "supplier_id": owner_id}, {"_id": 0})
    if selected_warehouse_id:
        updated["stock"] = stock_amount
        updated["warehouse_id"] = selected_warehouse_id
    return updated

@api.delete("/products/{pid}")
async def delete_product(pid: str, user: dict = Depends(require_role("supplier"))):
    require_supplier_permission(user, "inventory")
    if user.get("supplier_access_role", "global_admin") != "global_admin":
        raise HTTPException(403, "Only the distributor owner can remove shared products.")
    owner_id = supplier_owner_id(user)
    res = await db.products.delete_one({"id": pid, "supplier_id": owner_id})
    if res.deleted_count == 0:
        raise HTTPException(404, "Product not found")
    return {"ok": True}


async def require_suppliers_with_iban(supplier_ids):
    suppliers = await db.users.find(
        {"id": {"$in": list(supplier_ids)}},
        {"_id": 0, "id": 1, "business_name": 1, "iban": 1, "bank_accounts": 1},
    ).to_list(100)
    suppliers = [_decrypt_sensitive_fields(s) for s in suppliers]
    missing = [s for s in suppliers if not (s.get("iban") or "").strip()
               and not any((account.get("iban") or "").strip() for account in s.get("bank_accounts", []))]
    if missing:
        names = ", ".join(s.get("business_name") or "distributor" for s in missing)
        raise HTTPException(
            400,
            f"Distributor bank account missing: {names} cannot receive card payments yet. "
            "Please choose another payment method.",
        )


# ---------- orders ----------
async def _post_whatsapp_alert(payload: dict) -> None:
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            response = await http.post(
                os.environ["WHATSAPP_NOTIFIER_URL"].rstrip("/") + "/notify/new-order",
                json=payload, headers={"x-notifier-secret": os.environ.get("NOTIFIER_SECRET", "")},
            )
            response.raise_for_status()
    except Exception as exc:
        logging.getLogger(__name__).error("WhatsApp alert failed for order %s: %s", payload["order"]["id"], exc)


def schedule_whatsapp_alert(order: dict, store_user: dict, supplier: Optional[dict]) -> None:
    """Fire-and-forget: never delays or fails order creation."""
    phone = (supplier or {}).get("phone")
    if not os.environ.get("WHATSAPP_NOTIFIER_URL") or not phone:
        return
    payload = {
        "order": {"id": order["id"], "totalAmount": order["total"]},
        "store": {"name": store_user.get("business_name") or store_user.get("name", "")},
        "distributor": {"phone": phone},
    }
    try:
        asyncio.get_running_loop().create_task(_post_whatsapp_alert(payload))
    except RuntimeError:
        pass


@api.post("/orders")
async def create_order(body: OrderIn, user: dict = Depends(require_store_permission("canManageOrders"))):
    if body.payment_method in {"tbc", "bog"}:
        raise HTTPException(400, "Use the selected bank checkout endpoint for bank card payments.")
    supplier_ids = {i.supplier_id for i in body.items}
    owner_id = store_owner_id(user)
    await require_approved_distributor_connections(owner_id, supplier_ids)
    requested_product_ids = list({item.product_id for item in body.items})
    product_docs = await db.products.find(
        {"id": {"$in": requested_product_ids}}, {"_id": 0},
    ).to_list(len(requested_product_ids) or 1)
    priced_products = {
        product["id"]: product for product in await _apply_partner_pricing(product_docs, owner_id)
    }
    canonical_items = []
    for submitted_item in body.items:
        product = priced_products.get(submitted_item.product_id)
        if not product or product.get("supplier_id") != submitted_item.supplier_id:
            raise HTTPException(409, "A product is no longer available from this distributor.")
        if not product.get("can_order"):
            raise HTTPException(403, {
                "code": "CONNECTION_REQUIRED",
                "message": "An approved distributor connection is required before ordering.",
                "distributor_ids": [submitted_item.supplier_id],
            })
        if submitted_item.quantity < int(product.get("moq", 1)):
            raise HTTPException(400, f"{product.get('name', submitted_item.name)} is below the minimum order quantity.")
        canonical_items.append(submitted_item.model_copy(update={
            "name": product.get("name", submitted_item.name),
            "image": product.get("image", submitted_item.image),
            "unit_price": store_order_unit_price(product, submitted_item.quantity),
        }))
    frozen = await db.users.find({"id": {"$in": list(supplier_ids)}, "billing_frozen": True}, {"_id": 0}).to_list(100)
    if frozen:
        names = ", ".join(f.get("business_name", "supplier") for f in frozen)
        raise HTTPException(403, f"Cannot place order: {names} is temporarily frozen due to overdue commission billing.")
    settings = await get_settings()
    online = body.payment_method == "online"
    branch_id = await resolve_store_branch(user, body.branch_id)
    grand_total_decimal = moneylib.total_sum(
        moneylib.dec(i.unit_price) * i.quantity for i in canonical_items
    )
    grand_total = moneylib.as_json(grand_total_decimal)
    if body.payment_method == "consignment":
        for sid in supplier_ids:
            terms = await db.credit_terms.find_one({"supplier_id": sid, "retailer_id": owner_id}, {"_id": 0})
            if not terms:
                raise HTTPException(
                    409,
                    "Ask the distributor to configure your store's credit limit and payment terms before placing a credit order.",
                )
            existing = await db.orders.find(
                {"supplier_id": sid, "retailer_id": owner_id, "external_order": {"$ne": True},
                 "payment_method": "consignment", "status": {"$ne": "Cancelled"}},
                {"_id": 0, "total": 1, "amount_paid": 1, "payment_status": 1,
                 "paid_at_checkout": 1, "external_order": 1, "id": 1},
            ).to_list(2000)
            outstanding = moneylib.ZERO
            for existing_order in existing:
                if "amount_paid" not in existing_order:
                    paid = existing_order.get("payment_status") == "Succeeded" or existing_order.get("paid_at_checkout")
                    balance = moneylib.ZERO if paid else moneylib.q(existing_order.get("total", 0) or 0)
                else:
                    _, raw_balance = order_payment_totals(existing_order)
                    balance = moneylib.q(raw_balance)
                outstanding += balance
            requested = moneylib.total_sum(
                moneylib.dec(item.unit_price) * item.quantity
                for item in canonical_items if item.supplier_id == sid
            )
            limit = moneylib.q(terms.get("credit_limit", 0) or 0)
            if outstanding + requested > limit:
                raise HTTPException(
                    409,
                    f"Order exceeds the available credit limit for {terms.get('retailer_name', 'this store')}.",
                )
    charge_id = None
    bank_transfer = body.payment_method == "bank_transfer"
    if bank_transfer:
        await require_suppliers_with_iban(supplier_ids)
    if online:
        await require_suppliers_with_iban(supplier_ids)
        saved_cards = _user_cards(user)
        if not saved_cards:
            raise HTTPException(400, "Add a verified payment card before paying online.")
        chosen = next((c for c in saved_cards if c["id"] == body.card_id), None) if body.card_id else saved_cards[0]
        if not chosen:
            raise HTTPException(400, "Selected card was not found.")
        try:
            charge_id = simulate_charge(chosen.get("sim_status", "ok"), grand_total)
        except CardError as e:
            raise HTTPException(402, f"Payment failed: {e}")
    created = []
    store_city = await _store_city(user, branch_id)
    routing_address = await _store_routing_address(user, branch_id, body.delivery_address)
    warehouse_by_supplier = {}
    for sid in supplier_ids:
        warehouse_by_supplier[sid] = await _warehouse_for_supplier_location(
            sid, routing_address, store_city,
        )
        if (store_city and getattr(db, "supplier_warehouses", None) is not None
                and not warehouse_by_supplier[sid]):
            raise HTTPException(409, "This distributor has no active warehouse serving your store's city.")
    for sid in supplier_ids:
        items = [i for i in canonical_items if i.supplier_id == sid]
        total_decimal = moneylib.total_sum(moneylib.dec(i.unit_price) * i.quantity for i in items)
        total = moneylib.as_json(total_decimal)
        supplier = await db.users.find_one({"id": sid})
        if not supplier or supplier.get("role") != "supplier":
            raise HTTPException(404, "A selected distributor was not found.")
        warehouse_id = warehouse_by_supplier[sid]
        await deduct_inventory(
            [{"supplier_id": sid, "product_id": i.product_id, "warehouse_id": warehouse_id, "quantity": i.quantity}
             for i in items],
            sale_source="app",
            out_of_stock_detail="Regional warehouse stock changed. Refresh availability and try again.",
        )
        store_doc = await db.users.find_one({"id": owner_id}, {"_id": 0}) or user
        commission = resolve_commission(settings, store_doc, supplier)
        fee = compute_fee(total, commission)
        payer = commission["fee_payer"]
        oid = str(uuid.uuid4())
        transfer_reference = await _next_payment_reference() if bank_transfer else ""
        order = {
            "id": oid, "order_no": "ORD-" + oid[:8].upper(), "source": "app",
            "retailer_id": owner_id, "retailer_name": user["business_name"],
            "retailer_tax_id": user.get("identification_number", ""),
            "retailer_establishment": user.get("establishment_type", ""),
            "supplier_id": sid, "supplier_name": supplier["business_name"] if supplier else "Supplier",
            "supplier_tax_id": supplier.get("identification_number", "") if supplier else "",
            "bank_account_snapshot": bank_account_snapshot(supplier),
            "items": [i.model_dump() for i in items], "total": total,
            "service_fee": fee, "fee_payer": payer, "fee_type": commission["fee_type"], "fee_value": commission["fee_value"],
            "fee_source": commission["fee_source"],
            "status": "Pending Payment" if bank_transfer else "Pending", "delivery_address": body.delivery_address,
            "branch_id": branch_id, "warehouse_id": warehouse_id,
            "notes": body.notes or "", "delivery_window": body.delivery_window or "",
            "payment_method": body.payment_method or "cash",
            "payment_reference": transfer_reference,
            "payment_state": "pending_payment" if bank_transfer else ("paid" if online else "unpaid"),
            "amount_paid": total if online else 0,
            "paymentStatus": "PAID" if online else "UNPAID", "paidAmount": total if online else 0.0,
            "totalAmount": total, "balance": 0.0 if online else total,
            "payment_entries": ([{
                "id": f"checkout-{oid}",
                "amount": total,
                "method": "card",
                "reference": charge_id or "",
                "note": "Paid at checkout",
                "recorded_by": "system",
                "recorded_at": now_iso(),
                "automatic": True,
            }] if online else []),
            "timeline": [{"status": "Pending Payment" if bank_transfer else "Pending", "at": now_iso()}],
            "created_at": now_iso(), "updated_at": now_iso(),
        }
        if online:
            payout = moneylib.as_json(moneylib.q(moneylib.dec(total) - moneylib.dec(fee)))
            order.update({"paid_at_checkout": True, "commission_settled": True, "commission_amount": fee,
                          "supplier_payout": payout, "payment_ref": charge_id})
            await db.payouts.insert_one({
                "id": str(uuid.uuid4()), "order_id": oid, "order_no": order["order_no"],
                "supplier_id": sid, "supplier_name": order["supplier_name"],
                "retailer_name": user["business_name"], "order_total": total, "commission": fee,
                "supplier_payout": payout, "currency": "GEL", "method": "checkout_card",
                "status": "settled", "created_at": now_iso(),
            })
        await db.orders.insert_one(dict(order))
        schedule_whatsapp_alert(order, user, supplier)
        if online:
            await notify(
                sid,
                f"მოგივიდა ახალი გადახდილი შეკვეთა №{order['order_no']} — {user['business_name']}, "
                f"ჯამი: ₾{total:.2f}; საკომისიოს შემდეგ ჩასარიცხი თანხა: ₾{order['supplier_payout']:.2f}.",
                "order", order_id=oid,
            )
        elif bank_transfer:
            await notify(
                sid,
                f"მოგივიდა ინვოისით შეკვეთა №{order['order_no']} — {user['business_name']}, ჯამი: ₾{total:.2f}. "
                f"დანიშნულების კოდი: {transfer_reference}.",
                "order", order_id=oid,
            )
        else:
            await notify(
                sid, f"მოგივიდა ახალი შეკვეთა! №{order['order_no']} — {user['business_name']}, ჯამი: ₾{total:.2f}.",
                "order", order_id=oid,
            )
        created.append(clean(order))
    return {"orders": created, "paid": online, "charged": grand_total if online else 0}


def _bank_terminal_status(status: str) -> str:
    if status == "Succeeded":
        return "Succeeded"
    if status in {"Failed", "Expired", "Returned", "PartialReturned"}:
        return status
    return "Pending"


async def _apply_bank_payment_result(payment: dict, provider_payment: dict) -> str:
    gateway = payment.get("gateway", "tbc")
    pay_id = str(payment["pay_id"])
    if provider_payment.get("payId") != pay_id:
        raise HTTPException(400, "Payment reference does not match.")
    merchant_payment_id = provider_payment.get("merchantPaymentId")
    if gateway == "bog" and not merchant_payment_id:
        raise HTTPException(502, "BOG response is missing the merchant payment reference.")
    if merchant_payment_id and merchant_payment_id != payment["id"]:
        raise HTTPException(400, "Merchant payment reference does not match.")
    try:
        provider_amount = moneylib.q(provider_payment.get("amount"))
        expected_amount = moneylib.q(payment.get("amount"))
    except moneylib.MoneyError:
        raise HTTPException(502, "Bank returned an invalid payment amount.")
    if str(provider_payment.get("currency") or "").upper() != "GEL" or provider_amount != expected_amount:
        raise HTTPException(400, "Payment amount or currency does not match.")

    provider_status = str(provider_payment.get("_provider_status") or provider_payment.get("status") or "")
    final_status = _bank_terminal_status(provider_status)
    if final_status == "Pending":
        await db.bank_payments.update_one(
            {"id": payment["id"]}, {"$set": {"provider_status": provider_status, "updated_at": now_iso()}}
        )
        return "Pending"
    if payment.get("status") in {"Succeeded", "Failed", "Expired", "Returned", "PartialReturned"}:
        return payment["status"]

    should_process = False
    if payment.get("status") == "Pending":
        claimed = await db.bank_payments.update_one(
            {"id": payment["id"], "status": "Pending"},
            {"$set": {
                "status": "Processing", "final_status": final_status,
                "provider_status": provider_status, "updated_at": now_iso(),
                "processing_started_at": now_iso(),
            }},
        )
        payment = await db.bank_payments.find_one({"id": payment["id"]}, {"_id": 0})
        should_process = claimed.modified_count == 1
        if not should_process and payment.get("status") == "Processing":
            return "Pending"
    elif payment.get("status") == "Processing":
        processing_started = datetime.fromisoformat(payment["processing_started_at"])
        if datetime.now(timezone.utc) - processing_started >= timedelta(seconds=30):
            claimed = await db.bank_payments.update_one(
                {"id": payment["id"], "status": "Processing",
                 "processing_started_at": payment["processing_started_at"]},
                {"$set": {"final_status": final_status, "provider_status": provider_status,
                          "processing_started_at": now_iso()}},
            )
            should_process = claimed.modified_count == 1
            if should_process:
                payment = await db.bank_payments.find_one({"id": payment["id"]}, {"_id": 0})
    if not should_process:
        if payment.get("status") in {"Succeeded", "Failed", "Expired", "Returned", "PartialReturned"}:
            return payment["status"]
        return "Pending"
    final_status = payment["final_status"]

    orders = await db.orders.find({"id": {"$in": payment["order_ids"]}}, {"_id": 0}).to_list(100)
    if final_status == "Succeeded":
        for order in orders:
            if is_external_order(order):
                continue
            order_total = moneylib.q(order.get("total"))
            fee = moneylib.q(order.get("service_fee"))
            payout = moneylib.q(order_total - fee)
            old_paid = min(moneylib.amount_or_zero(order.get("amount_paid")), order_total)
            new_payment = moneylib.q(max(moneylib.ZERO, order_total - old_paid))
            entries = list(order.get("payment_entries", []))
            entry_id = f"{payment['id']}-{order['id']}"
            if new_payment and not any(entry.get("id") == entry_id for entry in entries):
                entries.append({
                    "id": entry_id,
                    "amount": moneylib.as_json(new_payment),
                    "method": "card",
                    "reference": pay_id,
                    "note": "Paid through bank checkout",
                    "recorded_by": "system",
                    "recorded_at": now_iso(),
                    "automatic": True,
                })
            await db.orders.update_one({"id": order["id"]}, {"$set": {
                "payment_status": "Succeeded", "paid_at_checkout": True, "commission_settled": True,
                "commission_amount": moneylib.as_json(fee), "supplier_payout": moneylib.as_json(payout), "payment_ref": pay_id,
                "amount_paid": moneylib.as_json(order_total), "payment_entries": entries,
                "paymentStatus": "PAID", "paidAmount": moneylib.as_json(order_total),
                "totalAmount": moneylib.as_json(order_total), "balance": moneylib.as_json(moneylib.ZERO),
                "updated_at": now_iso(),
            }})
            payout_id = f"{gateway}_{order['id']}"
            await db.payouts.update_one({"id": payout_id}, {"$setOnInsert": {
                "id": payout_id, "order_id": order["id"], "order_no": order["order_no"],
                "supplier_id": order["supplier_id"], "supplier_name": order["supplier_name"],
                "retailer_name": order["retailer_name"], "order_total": moneylib.as_json(order_total),
                "commission": moneylib.as_json(fee), "supplier_payout": moneylib.as_json(payout), "currency": "GEL",
                "method": f"{gateway}_checkout", "status": "settled", "created_at": now_iso(),
            }}, upsert=True)
            await notify(
                order["supplier_id"],
                f"მოგივიდა ახალი გადახდილი შეკვეთა №{order['order_no']} — "
                f"{order['retailer_name']}, ჯამი: ₾{order_total:.2f}.",
                "order", order_id=order["id"],
                notification_id=f"{gateway}-order-{payment['id']}-{order['id']}",
            )
    else:
        for order in orders:
            released = await db.orders.update_one(
                {"id": order["id"], "stock_released": {"$ne": True}}, {"$set": {
                "status": "Cancelled", "payment_status": final_status, "updated_at": now_iso(),
                "stock_released": True,
            }, "$push": {"timeline": {"status": "Cancelled", "at": now_iso()}}})
            if released.modified_count:
                for reserved in order.get("items", []):
                    await release_product_stock(
                        order.get("supplier_id"), reserved["product_id"],
                        order.get("warehouse_id"), reserved["quantity"],
                    )
    await db.bank_payments.update_one({"id": payment["id"]}, {"$set": {
        "status": final_status, "updated_at": now_iso(),
    }})
    audit_status = "success" if final_status == "Succeeded" else "error"
    await log_financial_event(
        f"bank_payment_{final_status.lower()}",
        {"id": "system", "name": "Payment gateway"}, "bank_payment", payment["id"],
        before={"status": payment.get("status", "Pending")}, after={"status": final_status},
        status=audit_status, amount=payment.get("amount"), currency=payment.get("currency", "GEL"),
        gateway=gateway,
    )
    return final_status


async def _sync_tbc_payment(payment: dict) -> str:
    tbc_credentials.set(gateway_credentials(await get_settings(), "tbc"))
    try:
        provider_payment = await get_tbc_payment(payment["pay_id"])
    except (httpx.HTTPError, TBCGatewayError) as error:
        logger.exception("Could not verify TBC payment status")
        raise HTTPException(502, "Could not verify payment with the bank. Please try again.")
    return await _apply_bank_payment_result(payment, provider_payment)


async def _sync_bog_payment(payment: dict) -> str:
    bog_credentials.set(gateway_credentials(await get_settings(), "bog"))
    try:
        bog_payment = await get_bog_order(payment["pay_id"])
    except (httpx.HTTPError, BOGGatewayError):
        logger.exception("Could not verify BOG payment status")
        raise HTTPException(502, "Could not verify payment with the bank. Please try again.")
    provider_order_status = bog_payment.get("order_status")
    if not isinstance(provider_order_status, dict):
        raise HTTPException(502, "BOG returned an invalid payment status.")
    order_status = str(provider_order_status.get("key") or "")
    purchase_units = bog_payment.get("purchase_units")
    if not isinstance(purchase_units, dict):
        raise HTTPException(502, "BOG returned invalid payment details.")
    status = {
        "completed": "Succeeded",
        "rejected": "Failed",
        "refunded": "Returned",
        "refunded_partially": "PartialReturned",
    }.get(order_status, "Pending")
    try:
        amount = purchase_units.get("request_amount")
        currency = purchase_units.get("currency_code")
        normalized_payment = {
            "payId": bog_payment.get("order_id"),
            "merchantPaymentId": bog_payment.get("external_order_id"),
            "amount": amount,
            "currency": currency,
            "status": status,
            "_provider_status": order_status,
        }
    except (AttributeError, TypeError):
        raise HTTPException(502, "BOG returned an invalid payment response.")
    return await _apply_bank_payment_result(payment, normalized_payment)


async def _start_bank_checkout(gateway: str, body: OrderIn, request: Request, user: dict):
    platform_settings = await get_settings()
    if platform_settings.get("payment_provider") == "stripe":
        raise HTTPException(503, "Stripe checkout is not supported yet. Select TBC or BOG in system settings.")
    credentials = gateway_credentials(platform_settings, gateway)
    (tbc_credentials if gateway == "tbc" else bog_credentials).set(credentials)
    try:
        if gateway == "tbc":
            validate_tbc_configuration()
        else:
            validate_bog_configuration()
    except (TBCGatewayError, BOGGatewayError) as error:
        raise HTTPException(503, str(error))
    frontend_url = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")
    if not frontend_url:
        raise HTTPException(503, "Set APP_BASE_URL to enable bank checkout return URLs.")
    if not body.items or not body.delivery_address.strip():
        raise HTTPException(400, "Order items and delivery address are required.")
    branch_id = await resolve_store_branch(user, body.branch_id)
    owner_id = store_owner_id(user)
    routing_address = await _store_routing_address(user, branch_id, body.delivery_address)
    store_city = await _store_city(user, branch_id)
    product_ids = [item.product_id for item in body.items]
    supplier_ids = {item.supplier_id for item in body.items}
    if len(product_ids) != len(set(product_ids)):
        raise HTTPException(400, "Each product may only appear once in a checkout.")
    await require_approved_distributor_connections(owner_id, supplier_ids)

    products = {}
    order_warehouses = {}
    for item in body.items:
        product = await db.products.find_one(
            {"id": item.product_id, "supplier_id": item.supplier_id}, {"_id": 0}
        )
        if not product:
            raise HTTPException(404, "One or more products are no longer available.")
        if item.quantity < int(product.get("moq", 1)):
            raise HTTPException(400, f"{product['name']} is below the minimum order quantity.")
        if item.supplier_id not in order_warehouses:
            order_warehouses[item.supplier_id] = await _warehouse_for_supplier_location(
                item.supplier_id, routing_address, store_city,
            )
            if (store_city and getattr(db, "supplier_warehouses", None) is not None
                    and not order_warehouses[item.supplier_id]):
                raise HTTPException(409, "This distributor has no active warehouse serving your store's city.")
        warehouse_id = order_warehouses[item.supplier_id]
        available = await available_product_stock(item.supplier_id, item.product_id, warehouse_id, product.get("stock", 0))
        if available < item.quantity:
            raise HTTPException(409, f"Insufficient stock for {product['name']}.")
        products[item.product_id] = product

    priced_products = await _apply_partner_pricing(list(products.values()), owner_id)
    products = {
        product["id"]: {
            **product,
            "checkout_unit_price": store_order_unit_price(
                product, next(item.quantity for item in body.items if item.product_id == product["id"]),
            ),
        }
        for product in priced_products
    }
    await require_suppliers_with_iban(supplier_ids)
    frozen = await db.users.find(
        {"id": {"$in": list(supplier_ids)}, "billing_frozen": True}, {"_id": 0, "business_name": 1}
    ).to_list(100)
    if frozen:
        names = ", ".join(supplier.get("business_name", "supplier") for supplier in frozen)
        raise HTTPException(403, f"Cannot place order: {names} is temporarily frozen.")

    settings = await get_settings()
    reserved_items = await deduct_inventory(
        [{"supplier_id": item.supplier_id, "product_id": item.product_id,
          "warehouse_id": order_warehouses[item.supplier_id], "quantity": item.quantity}
         for item in body.items],
        sale_source="app",
        out_of_stock_detail="Stock changed while starting checkout. Please review your cart.",
    )

    payment_id = str(uuid.uuid4())
    order_documents = []
    store_owner = await db.users.find_one({"id": owner_id}, {"_id": 0}) or user
    for supplier_id in supplier_ids:
        order_items = [item for item in body.items if item.supplier_id == supplier_id]
        supplier = await db.users.find_one({"id": supplier_id})
        normalized_items = [{
            "product_id": item.product_id, "name": products[item.product_id]["name"],
            "image": products[item.product_id].get("image", ""),
            "supplier_id": supplier_id, "quantity": item.quantity,
            "unit_price": products[item.product_id]["checkout_unit_price"],
        } for item in order_items]
        total_decimal = moneylib.total_sum(
            moneylib.dec(item["unit_price"]) * item["quantity"] for item in normalized_items
        )
        total = moneylib.as_json(total_decimal)
        commission = resolve_commission(settings, store_owner, supplier)
        fee = compute_fee(total, commission)
        order_documents.append({
            "id": order_uuid, "order_no": "ORD-" + order_uuid[:8].upper(), "source": "app",
            "retailer_id": owner_id,             "retailer_name": store_owner.get("business_name", user["business_name"]),
            "retailer_tax_id": store_owner.get("identification_number", ""),
            "retailer_establishment": store_owner.get("establishment_type", ""),
            "supplier_id": supplier_id,
            "supplier_name": supplier.get("business_name", "Supplier") if supplier else "Supplier",
            "supplier_tax_id": supplier.get("identification_number", "") if supplier else "",
            "bank_account_snapshot": bank_account_snapshot(supplier),
            "items": normalized_items, "total": total, "service_fee": fee,
            "fee_payer": commission["fee_payer"], "fee_type": commission["fee_type"],
            "fee_value": commission["fee_value"], "fee_source": commission["fee_source"], "status": "Pending",
            "payment_status": "Pending", "payment_method": gateway,
            "amount_paid": 0, "payment_entries": [],
            "branch_id": branch_id, "warehouse_id": order_warehouses[supplier_id],
            "delivery_address": body.delivery_address, "notes": body.notes or "",
            "delivery_window": body.delivery_window or "",
            "timeline": [{"status": "Pending", "at": now_iso()}],
            "created_at": now_iso(), "updated_at": now_iso(),
            f"{gateway}_payment_id": payment_id,
        })
    amount = moneylib.as_json(moneylib.total_sum(order.get("total") for order in order_documents))
    return_url = f"{frontend_url}/orders?payment_id={payment_id}&payment_gateway={gateway}"

    try:
        if gateway == "tbc":
            pay_id, provider_response = await create_tbc_payment(
                payment_id, amount, return_url, request.client.host if request.client else ""
            )
            if provider_response.get("status") != "Created":
                raise TBCGatewayError("TBC did not create the payment.")
            approval_url = next(
                link["uri"] for link in provider_response.get("links", [])
                if link.get("rel") == "approval_url"
            )
        else:
            basket_items = [
                {
                    "product_id": item.product_id,
                    "name": products[item.product_id]["name"],
                    "quantity": item.quantity,
                    "unit_price": products[item.product_id]["checkout_unit_price"],
                }
                for item in body.items
            ]
            pay_id, provider_response = await create_bog_order(
                payment_id, amount, return_url, bog_callback_url(), basket_items
            )
            approval_url = provider_response["_links"]["redirect"]["href"]
        await db.orders.insert_many(order_documents)
        await db.bank_payments.insert_one({
            "id": payment_id, "pay_id": pay_id, "gateway": gateway, "retailer_id": owner_id,
            "order_ids": [order["id"] for order in order_documents],
            "reserved_items": reserved_items, "amount": amount, "currency": "GEL",
            "status": "Pending", "provider_status": "Created", "created_at": now_iso(),
            "updated_at": now_iso(),
            "platform_split": compute_platform_split(amount, platform_settings, "app"),
        })
        await log_financial_event(
            "bank_payment_pending", user, "bank_payment", payment_id,
            status="pending", amount=amount, currency="GEL", gateway=gateway,
        )
        return {"payment_id": payment_id, "redirect_url": approval_url}
    except (httpx.HTTPError, TBCGatewayError, BOGGatewayError, KeyError, StopIteration) as error:
        for reserved in reserved_items:
            await release_product_stock(
                reserved["supplier_id"], reserved["product_id"],
                reserved["warehouse_id"], reserved["quantity"],
            )
        await db.orders.delete_many({f"{gateway}_payment_id": payment_id})
        await db.bank_payments.delete_one({"id": payment_id})
        logger.exception("Could not initiate %s checkout", gateway.upper())
        raise HTTPException(502, "Could not start bank payment. Please try again.")


def _idempotent(scope: str, user: dict, key: Optional[str], payload, handler):
    return safeguards.run_idempotent(
        getattr(db, "idempotency_keys", None), f"{scope}:{user['id']}", key, payload, handler,
    )


@api.post("/payments/tbc/checkout")
async def start_tbc_checkout(body: OrderIn, request: Request,
                             idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
                             user: dict = Depends(require_store_permission("canManageOrders"))):
    return await _idempotent("tbc-checkout", user, idempotency_key, body.model_dump(mode="json"),
                             lambda: _start_bank_checkout("tbc", body, request, user))


@api.post("/payments/bog/checkout")
async def start_bog_checkout(body: OrderIn, request: Request,
                             idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
                             user: dict = Depends(require_store_permission("canManageOrders"))):
    return await _idempotent("bog-checkout", user, idempotency_key, body.model_dump(mode="json"),
                             lambda: _start_bank_checkout("bog", body, request, user))


@api.post("/payments/tbc/callback")
async def tbc_payment_callback(request: Request):
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(400, "Invalid bank callback payload.")
    if not isinstance(payload, dict):
        raise HTTPException(400, "Invalid bank callback payload.")
    pay_id = payload.get("PaymentId") or payload.get("paymentId") or payload.get("payId")
    if not isinstance(pay_id, str) or not pay_id:
        raise HTTPException(400, "Payment ID is required.")
    payment = await db.bank_payments.find_one({"pay_id": pay_id}, {"_id": 0})
    if not payment:
        raise HTTPException(404, "Payment not found.")
    status = await _sync_tbc_payment(payment)
    return {"ok": True, "status": status}


@api.post("/payments/bog/callback")
async def bog_payment_callback(request: Request):
    raw_body = await request.body()
    signature = request.headers.get("Callback-Signature", "")
    try:
        if not signature or not verify_callback_signature(raw_body, signature):
            raise HTTPException(401, "Invalid BOG callback signature.")
    except BOGGatewayError as error:
        logger.exception("Could not validate BOG callback")
        raise HTTPException(503, str(error))
    try:
        payload = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(400, "Invalid bank callback payload.")
    if not isinstance(payload, dict) or not isinstance(payload.get("body"), dict):
        raise HTTPException(400, "Invalid bank callback payload.")
    pay_id = payload["body"].get("order_id")
    if not isinstance(pay_id, str) or not pay_id:
        raise HTTPException(400, "Payment ID is required.")
    payment = await db.bank_payments.find_one(
        {"pay_id": pay_id, "gateway": "bog"}, {"_id": 0}
    )
    if not payment:
        raise HTTPException(404, "Payment not found.")
    status = await _sync_bog_payment(payment)
    return {"ok": True, "status": status}


@api.get("/payments/tbc/{payment_id}")
async def get_tbc_checkout_status(payment_id: str, user: dict = Depends(get_current_user)):
    payment = await db.bank_payments.find_one(
        {"id": payment_id, "retailer_id": store_owner_id(user)}, {"_id": 0}
    )
    if not payment:
        raise HTTPException(404, "Payment not found.")
    assigned_branch_id = user.get("assigned_branch_id") if user.get("role") == "retailer" and user.get("store_access_role") != "global_admin" else None
    if assigned_branch_id and not await db.orders.find_one({
        "id": {"$in": payment.get("order_ids", [])}, "branch_id": assigned_branch_id,
    }, {"_id": 1}):
        raise HTTPException(404, "Payment not found.")
    return {"payment_id": payment_id, "status": payment["status"], "order_ids": payment["order_ids"]}


@api.get("/payments/bog/{payment_id}")
async def get_bog_checkout_status(payment_id: str, user: dict = Depends(get_current_user)):
    payment = await db.bank_payments.find_one(
        {"id": payment_id, "gateway": "bog", "retailer_id": store_owner_id(user)}, {"_id": 0}
    )
    if not payment:
        raise HTTPException(404, "Payment not found.")
    assigned_branch_id = user.get("assigned_branch_id") if user.get("role") == "retailer" and user.get("store_access_role") != "global_admin" else None
    if assigned_branch_id and not await db.orders.find_one({
        "id": {"$in": payment.get("order_ids", [])}, "branch_id": assigned_branch_id,
    }, {"_id": 1}):
        raise HTTPException(404, "Payment not found.")
    if payment["status"] not in {"Succeeded", "Failed", "Expired", "Returned", "PartialReturned"}:
        status = await _sync_bog_payment(payment)
    else:
        status = payment["status"]
    return {"payment_id": payment_id, "status": status, "order_ids": payment["order_ids"]}


def _page(limit: Optional[int], offset: int, default_limit: int) -> tuple:
    size = default_limit if limit is None else max(1, min(int(limit), 1000))
    return size, max(0, int(offset))


@api.get("/orders")
async def list_orders(
    response: Response,
    branch_id: Optional[str] = None, warehouse_id: Optional[str] = None,
    cities: Optional[str] = None,
    limit: Optional[int] = None, offset: int = 0, status: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    if user["role"] == "retailer":
        q = {"retailer_id": store_owner_id(user)}
    elif user["role"] == "supplier":
        require_supplier_permission(user, "orders")
        q = {"supplier_id": supplier_owner_id(user), "$or": [
            {"payment_method": {"$nin": ["tbc", "bog"]}}, {"payment_status": "Succeeded"},
        ]}
        selected_warehouse_id = await supplier_warehouse_id(user, warehouse_id)
        if selected_warehouse_id:
            q["warehouse_id"] = selected_warehouse_id
    else:
        q = {}
    if user["role"] == "retailer":
        selected_branch = await resolve_store_branch(user, branch_id)
        q["branch_id"] = selected_branch
    if status and status != "All":
        q["status"] = status
    city_filter = _parse_city_filter(None, cities)
    if city_filter:
        city_regex = "|".join(re.escape(c) for c in city_filter)
        q["$and"] = [*q.get("$and", []), {"delivery_address": {"$regex": city_regex, "$options": "i"}}]
    size, skip = _page(limit, offset, 500)
    response.headers["X-Total-Count"] = str(await db.orders.count_documents(q))
    docs = await db.orders.find(q, {"_id": 0}).sort("created_at", -1).skip(skip).limit(size).to_list(size)
    for d in docs:
        d.setdefault("payment_method", "cash")
        d.setdefault("amount_paid", d.get("total", 0) if d.get("paid_at_checkout") or d.get("payment_status") == "Succeeded" else 0)
        d.setdefault("payment_entries", [])
        d.update(order_payment_fields(d))
        d["lifecycle_status"] = lifecycle_status(d)
    return await _attach_supplier_logos(docs)


@api.get("/store/branches")
async def list_store_branches(user: dict = Depends(require_role("retailer"))):
    owner_id = store_owner_id(user)
    query = {"retailer_id": owner_id}
    if user.get("store_access_role", "global_admin") != "global_admin":
        query["id"] = user.get("assigned_branch_id")
    branches = await db.store_branches.find(query, {"_id": 0}).sort("created_at", 1).to_list(500)
    if branches:
        return branches
    if user.get("store_access_role", "global_admin") != "global_admin":
        return []
    owner = await db.users.find_one({"id": owner_id}, {"_id": 0}) or user
    return [{
        "id": owner.get("default_branch_id") or owner_id,
        "retailer_id": owner_id,
        "name": owner.get("business_name") or owner.get("name") or "Main branch",
        "address": owner.get("address") or "",
        "phone": owner.get("phone") or "",
        "is_default": True,
        "active": True,
    }]


@api.get("/store/staff")
async def list_store_staff(user: dict = Depends(require_role("retailer"))):
    require_store_owner(user)
    staff = await db.users.find(
        {"retailer_id": store_owner_id(user), "role": "retailer"},
        {"_id": 0, "password_hash": 0, "card_token": 0},
    ).sort("created_at", 1).to_list(1000)
    return [{
        "id": member["id"], "name": member.get("name", ""),
        "email": member.get("email", ""), "branch_id": member.get("assigned_branch_id", ""),
        "role": member.get("store_access_role", "staff"),
        "branch_role": member.get("branch_role", "Staff"),
        "active": member.get("active", True),
        "permissions": effective_store_permissions(member),
    } for member in staff]


@api.post("/store/staff")
async def create_store_staff(body: StoreStaffIn, user: dict = Depends(require_role("retailer"))):
    require_store_owner(user)
    owner_id = store_owner_id(user)
    branch = await db.store_branches.find_one({
        "id": body.branch_id, "retailer_id": owner_id, "active": True,
    }, {"_id": 0})
    if not branch:
        raise HTTPException(404, "Active store branch not found.")
    email = body.email.lower()
    if await db.users.find_one({"email": email}, {"_id": 1}):
        raise HTTPException(400, "Email already registered.")
    owner = await db.users.find_one({"id": owner_id}, {"_id": 0, "password_hash": 0})
    if not owner:
        raise HTTPException(404, "Store owner not found.")
    temporary_password = secrets.token_urlsafe(12)
    role_name = "Branch Manager" if body.role == "branch_manager" else "Staff"
    permissions = body.permissions or default_store_permissions(body.role)
    member = {
        "id": str(uuid.uuid4()), "email": email,
        "password_hash": hash_password(temporary_password),
        "name": body.name, "role": "retailer", "retailer_id": owner_id,
        "store_access_role": body.role, "branch_role": role_name, "permissions": permissions,
        "assigned_branch_id": body.branch_id, "business_name": owner.get("business_name") or owner.get("name", ""),
        "address": branch.get("address") or "", "phone": branch.get("phone") or owner.get("phone", ""),
        "identification_number": owner.get("identification_number", ""),
        "establishment_type": owner.get("establishment_type", ""),
        "status": "active", "active": True, "email_verified": True,
        "must_change_password": True, "created_at": now_iso(),
    }
    await db.users.insert_one(member)
    await _ensure_admin_contacts(member["id"])
    return {
        "id": member["id"], "name": member["name"], "email": member["email"],
        "branch_id": body.branch_id, "role": body.role, "branch_role": role_name,
        "active": True, "permissions": permissions, "temporary_password": temporary_password,
    }


@api.put("/store/staff/{staff_id}")
async def update_store_staff(
    staff_id: str, body: StoreStaffStatusIn, user: dict = Depends(require_role("retailer")),
):
    require_store_owner(user)
    updates = {}
    if body.active is not None:
        updates["active"] = body.active
    if body.permissions is not None:
        updates["permissions"] = body.permissions
    if body.role is not None:
        updates["store_access_role"] = body.role
        updates["branch_role"] = "Branch Manager" if body.role == "branch_manager" else "Staff"
    if body.branch_id is not None:
        branch = await db.store_branches.find_one({
            "id": body.branch_id, "retailer_id": store_owner_id(user), "active": True,
        }, {"_id": 0})
        if not branch:
            raise HTTPException(404, "Active store branch not found.")
        updates["assigned_branch_id"] = body.branch_id
    if not updates:
        raise HTTPException(400, "Nothing to update.")
    result = await db.users.update_one({
        "id": staff_id, "retailer_id": store_owner_id(user), "role": "retailer",
    }, {"$set": {**updates, "updated_at": now_iso()}})
    if result.matched_count == 0:
        raise HTTPException(404, "Store staff member not found.")
    return {"id": staff_id, **updates}


@api.post("/store/branches")
async def create_store_branch(body: StoreBranchIn, user: dict = Depends(require_role("retailer"))):
    require_store_owner(user)
    owner_id = store_owner_id(user)
    branch_id = str(uuid.uuid4())
    now = now_iso()
    branch = {
        "id": branch_id, "retailer_id": owner_id, **body.model_dump(),
        "is_default": False, "created_at": now, "updated_at": now,
    }
    await db.store_branches.insert_one(dict(branch))
    return branch


@api.put("/store/branches/{branch_id}")
async def update_store_branch(
    branch_id: str,
    body: StoreBranchIn,
    user: dict = Depends(require_role("retailer")),
):
    require_store_owner(user)
    owner_id = store_owner_id(user)
    branch = await db.store_branches.find_one(
        {"id": branch_id, "retailer_id": owner_id}, {"_id": 0},
    )
    if not branch:
        raise HTTPException(404, "Branch not found.")
    if branch.get("is_default") and not body.active:
        raise HTTPException(409, "The default branch must remain active.")
    updated = {**body.model_dump(), "updated_at": now_iso()}
    await db.store_branches.update_one({"id": branch_id, "retailer_id": owner_id}, {"$set": updated})
    if branch.get("is_default"):
        await db.users.update_one({"id": owner_id}, {"$set": {
            "address": body.address, "phone": body.phone,
        }})
    return {**branch, **updated}


@api.delete("/store/branches/{branch_id}")
async def delete_store_branch(branch_id: str, user: dict = Depends(require_role("retailer"))):
    require_store_owner(user)
    owner_id = store_owner_id(user)
    branch = await db.store_branches.find_one(
        {"id": branch_id, "retailer_id": owner_id}, {"_id": 0},
    )
    if not branch:
        raise HTTPException(404, "Branch not found.")
    if branch.get("is_default"):
        raise HTTPException(409, "The default branch cannot be deleted.")
    debt, open_orders = await outstanding_debt({"retailer_id": owner_id, "branch_id": branch_id})
    if debt > 0:
        await log_financial_event(
            "branch_delete_blocked", user, "branch", branch_id,
            before={"debt": debt, "open_orders": open_orders},
        )
        raise HTTPException(
            409,
            f"ფილიალის წაშლა შეუძლებელია, რადგან მასზე ფიქსირდება დავალიანება/ნისია (₾{debt:.2f}, "
            f"{open_orders} შეკვეთა). წაშლა დაშვებულია მხოლოდ დავალიანების სრულად დაფარვის შემდეგ.",
        )
    if await db.orders.find_one({"retailer_id": owner_id, "branch_id": branch_id}, {"_id": 1}):
        raise HTTPException(409, "Branches with order history cannot be deleted. Mark the branch inactive instead.")
    await db.store_branches.delete_one({"id": branch_id, "retailer_id": owner_id})
    return {"ok": True}


@api.get("/store/analytics")
async def store_analytics(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user: dict = Depends(require_store_permission("canViewFinancials")),
):
    selected_range = _analytics_date_range(date_from, date_to)
    owner_id = store_owner_id(user)
    branches = await db.store_branches.find(
        {"retailer_id": owner_id}, {"_id": 0},
    ).sort("created_at", 1).to_list(500)
    if not branches:
        branches = await list_store_branches(user)
    all_orders = await db.orders.find(
        {"retailer_id": owner_id, "external_order": {"$ne": True}, "status": "Delivered"},
        {"_id": 0, "branch_id": 1, "items": 1, "id": 1},
    ).to_list(10000)
    sales_query = {"retailer_id": owner_id, **_analytics_date_query("sold_at", selected_range)}
    expense_query = {"retailer_id": owner_id, **_analytics_date_query("expense_date", selected_range)}
    sales = await db.pos_sales.find(sales_query, {"_id": 0}).to_list(50000)
    expenses = await db.store_expenses.find(expense_query, {"_id": 0}).to_list(50000)
    purchase_costs = {}
    for order in all_orders:
        branch_id = order.get("branch_id") or user.get("default_branch_id")
        for item in order.get("items", []):
            product_id = item.get("product_id")
            if not product_id:
                continue
            cost = moneylib.q(item.get("unit_price", 0) or 0)
            quantity = moneylib.dec(item.get("quantity", 0) or 0)
            stats = purchase_costs.setdefault((branch_id, product_id), [moneylib.ZERO, Decimal(0)])
            stats[0] += moneylib.q(cost * quantity)
            stats[1] += quantity
    branch_results = []
    for branch in branches:
        branch_id = branch["id"]
        totals = {"revenue": moneylib.ZERO, "cost": moneylib.ZERO, "units": Decimal(0)}
        products = {}
        for sale in sales:
            if sale.get("branch_id") != branch_id:
                continue
            for line in sale.get("items", []):
                quantity = moneylib.dec(line.get("quantity", 0) or 0)
                revenue = moneylib.q(quantity * moneylib.q(line.get("retail_price", 0) or 0))
                cost = moneylib.q(quantity * moneylib.q(line.get("unit_cost", 0) or 0))
                totals["revenue"] += revenue
                totals["cost"] += cost
                totals["units"] += quantity
                item_id = line.get("product_id") or line.get("sku") or line.get("product_name")
                entry = products.setdefault(item_id, {
                    "product_id": line.get("product_id"),
                    "product_name": line.get("product_name") or line.get("sku") or line.get("product_id") or "",
                    "quantity_sold": Decimal(0), "revenue": moneylib.ZERO, "net_profit": moneylib.ZERO,
                })
                entry["quantity_sold"] += quantity
                entry["revenue"] += revenue
                entry["net_profit"] += revenue - cost
        revenue_decimal = moneylib.q(totals["revenue"])
        cost_decimal = moneylib.q(totals["cost"])
        expenses_decimal = moneylib.total_sum(
            expense.get("amount", 0) or 0 for expense in expenses if expense.get("branch_id") == branch_id
        )
        gross_profit_decimal = moneylib.q(revenue_decimal - cost_decimal)
        net_profit_decimal = moneylib.q(gross_profit_decimal - expenses_decimal)
        revenue = moneylib.as_json(revenue_decimal)
        branch_expenses = moneylib.as_json(expenses_decimal)
        gross_profit = moneylib.as_json(gross_profit_decimal)
        net_profit = moneylib.as_json(net_profit_decimal)
        operating_margin = moneylib.divide(net_profit_decimal * Decimal(100), revenue_decimal)
        branch_results.append({
            **branch,
            "revenue": revenue,
            "cost_of_goods": moneylib.as_json(cost_decimal),
            "gross_profit": gross_profit,
            "operating_expenses": branch_expenses,
            "net_profit": net_profit,
            "operating_margin": moneylib.as_json(operating_margin) if operating_margin is not None else 0,
            "units_sold": moneylib.as_json(moneylib.q(totals["units"])),
            "top_products": sorted(
                ({**product, "quantity_sold": moneylib.as_json(moneylib.q(product["quantity_sold"])),
                  "revenue": moneylib.as_json(moneylib.q(product["revenue"])),
                  "net_profit": moneylib.as_json(moneylib.q(product["net_profit"]))}
                 for product in products.values()),
                key=lambda product: product["quantity_sold"], reverse=True,
            )[:10],
        })
    ranked = sorted(branch_results, key=lambda branch: (branch["net_profit"], branch["revenue"]), reverse=True)
    demand = []
    for branch in branch_results:
        for product in branch["top_products"][:5]:
            peers = [
                other_product["quantity_sold"]
                for other in branch_results if other["id"] != branch["id"]
                for other_product in other["top_products"]
                if product["product_id"] and other_product.get("product_id") == product["product_id"]
            ]
            if peers and product["quantity_sold"] > max(peers) * 1.25:
                demand.append({
                    "branch_id": branch["id"],
                    "branch_name": branch["name"],
                    "product_id": product["product_id"],
                    "product_name": product["product_name"],
                    "recommendation": "higher_demand",
                })
            elif peers and product["quantity_sold"] < min(peers) * 0.75:
                demand.append({
                    "branch_id": branch["id"],
                    "branch_name": branch["name"],
                    "product_id": product["product_id"],
                    "product_name": product["product_name"],
                    "recommendation": "lower_demand",
                })
    cross_branch_benchmarks = {}
    purchased_product_ids = list({product_id for _branch_id, product_id in purchase_costs})
    all_sales = await db.pos_sales.find(
        {"items.product_id": {"$in": purchased_product_ids}}, {"_id": 0},
    ).to_list(100000) if purchased_product_ids else []
    for sale in all_sales:
        for line in sale.get("items", []):
            product_id = line.get("product_id")
            retailer_id = sale.get("retailer_id")
            if not product_id or retailer_id == owner_id:
                continue
            benchmark = cross_branch_benchmarks.setdefault(product_id, {"retailers": set(), "prices": []})
            benchmark["retailers"].add(retailer_id)
            benchmark["prices"].append(moneylib.q(line.get("retail_price", 0) or 0))
    safe_benchmarks = {
        product_id: {
            "retailer_count": len(value["retailers"]),
            "median_retail_price": moneylib.as_json(_pricing_median(value["prices"])),
        }
        for product_id, value in cross_branch_benchmarks.items()
        if len(value["retailers"]) >= 3 and value["prices"]
    }
    return {
        "branches": branch_results,
        "leaderboard": [{"branch_id": branch["id"], "branch_name": branch["name"], "revenue": branch["revenue"], "net_profit": branch["net_profit"], "operating_margin": branch["operating_margin"]} for branch in ranked],
        "demand_recommendations": demand[:50],
        "market_benchmarks": safe_benchmarks,
        "purchase_cost_coverage": {
            "branches_with_delivered_orders": len({branch_id for branch_id, _product_id in purchase_costs}),
        },
    }


@api.get("/store/branch-expenses")
async def list_store_expenses(branch_id: Optional[str] = None, user: dict = Depends(require_store_permission("canViewFinancials"))):
    owner_id = store_owner_id(user)
    query = {"retailer_id": owner_id}
    if branch_id:
        branch = await db.store_branches.find_one({"id": branch_id, "retailer_id": owner_id}, {"_id": 1})
        if not branch:
            raise HTTPException(404, "Branch not found.")
        query["branch_id"] = branch_id
    return await db.store_expenses.find(query, {"_id": 0}).sort("expense_date", -1).to_list(2000)


@api.post("/store/branch-expenses")
async def create_store_expense(body: StoreExpenseIn, user: dict = Depends(require_store_permission("canViewFinancials"))):
    owner_id = store_owner_id(user)
    branch = await db.store_branches.find_one(
        {"id": body.branch_id, "retailer_id": owner_id, "active": True}, {"_id": 0, "id": 1},
    )
    if not branch:
        raise HTTPException(404, "Active store branch not found.")
    expense_date = body.expense_date
    if expense_date.tzinfo is None:
        expense_date = expense_date.replace(tzinfo=timezone.utc)
    expense_date = expense_date.astimezone(timezone.utc)
    expense = {
        "id": str(uuid.uuid4()),
        "retailer_id": owner_id,
        **body.model_dump(exclude={"expense_date"}),
        "category": body.category.strip(),
        "note": body.note.strip(),
        "amount": moneylib.as_json(moneylib.q(body.amount)),
        "expense_date": expense_date.isoformat(),
        "created_at": now_iso(),
    }
    await db.store_expenses.insert_one(dict(expense))
    return expense


@api.post("/admin/pricing/benchmarks")
async def ingest_external_price_benchmarks(
    body: ExternalMarketPriceBatchIn,
    user: dict = Depends(require_role("admin")),
):
    if any(entry.currency != "GEL" for entry in body.benchmarks):
        raise HTTPException(422, "External benchmark prices must be converted to GEL before ingestion.")
    product_ids = list({entry.product_id for entry in body.benchmarks})
    products = await db.products.find({"id": {"$in": product_ids}}, {"_id": 0, "id": 1}).to_list(len(product_ids))
    existing_ids = {product["id"] for product in products}
    missing = sorted(set(product_ids) - existing_ids)
    if missing:
        raise HTTPException(404, {"message": "Benchmark product not found.", "product_ids": missing})

    accepted = 0
    updated = 0
    for entry in body.benchmarks:
        price = moneylib.q(entry.price)
        observed_at = entry.observed_at.astimezone(timezone.utc)
        fingerprint_value = "|".join((
            entry.product_id, entry.source.casefold(), entry.source_url,
            observed_at.isoformat(), str(price),
        ))
        fingerprint = hashlib.sha256(fingerprint_value.encode("utf-8")).hexdigest()
        result = await db.market_price_benchmarks.update_one(
            {"fingerprint": fingerprint},
            {"$set": {
                "product_id": entry.product_id, "source": entry.source.strip(),
                "source_url": entry.source_url, "price": Decimal128(price), "currency": "GEL",
                "confidence": Decimal128(entry.confidence), "observed_at": observed_at,
                "status": "active", "updated_at": datetime.now(timezone.utc),
            }, "$setOnInsert": {
                "fingerprint": fingerprint, "created_at": datetime.now(timezone.utc),
                "created_by": user["id"],
            }},
            upsert=True,
        )
        if result.upserted_id:
            accepted += 1
        else:
            updated += 1
    return {"accepted": accepted, "updated": updated, "received": len(body.benchmarks)}


def _pricing_decimal(value) -> Decimal:
    if hasattr(value, "to_decimal"):
        value = value.to_decimal()
    return moneylib.q(value)


def _pricing_median(values: List[Decimal]) -> Optional[Decimal]:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return moneylib.q(ordered[middle])
    return moneylib.q((ordered[middle - 1] + ordered[middle]) / Decimal(2))


@api.post("/store/pricing/advisor")
async def store_pricing_advisor(
    body: StorePricingAdvisorIn,
    user: dict = Depends(require_store_permission("canChangePrices")),
):
    owner_id = store_owner_id(user)
    order = await db.orders.find_one({
        "id": body.order_id, "retailer_id": owner_id, "status": "Delivered", "external_order": {"$ne": True},
    }, {"_id": 0, "items": 1, "branch_id": 1})
    if not order:
        raise HTTPException(404, "Delivered purchase not found.")
    item = next((entry for entry in order.get("items", []) if entry.get("product_id") == body.product_id), None)
    if not item:
        raise HTTPException(404, "Purchased product not found.")
    unit_cost = moneylib.q(item.get("unit_price", 0) or 0)
    sales = await db.pos_sales.find(
        {"items.product_id": body.product_id}, {"_id": 0, "retailer_id": 1, "items": 1},
    ).to_list(100000)
    internal_prices_by_retailer = {}
    for sale in sales:
        retailer_id = sale.get("retailer_id")
        if not retailer_id or retailer_id == owner_id:
            continue
        for line in sale.get("items", []):
            if line.get("product_id") == body.product_id:
                try:
                    observed_price = _pricing_decimal(line.get("retail_price"))
                except moneylib.MoneyError:
                    continue
                if observed_price > 0:
                    internal_prices_by_retailer.setdefault(retailer_id, []).append(observed_price)
    internal_retailer_medians = [median for retailer_prices in internal_prices_by_retailer.values()
                                 if (median := _pricing_median(retailer_prices)) is not None]
    internal_median = _pricing_median(internal_retailer_medians) if len(internal_retailer_medians) >= 3 else None

    external_prices_by_source = {}
    benchmarks = getattr(db, "market_price_benchmarks", None)
    if benchmarks is not None:
        observed_after = datetime.now(timezone.utc) - timedelta(days=30)
        external_rows = await benchmarks.find({
            "product_id": body.product_id, "status": "active", "currency": "GEL",
            "observed_at": {"$gte": observed_after},
        }, {"_id": 0, "source": 1, "price": 1, "confidence": 1, "observed_at": 1}).to_list(1000)
        for observation in external_rows:
            source = str(observation.get("source") or "").strip()
            if not source:
                continue
            try:
                confidence = _pricing_decimal(observation.get("confidence", Decimal("1")))
                observed_price = _pricing_decimal(observation.get("price"))
            except moneylib.MoneyError:
                continue
            if confidence >= Decimal("0.80") and observed_price > 0:
                external_prices_by_source.setdefault(source.casefold(), []).append(observed_price)
    provider_medians = [median for source_prices in external_prices_by_source.values()
                        if (median := _pricing_median(source_prices)) is not None]
    external_median = _pricing_median(provider_medians) if len(provider_medians) >= 3 else None

    target_margin = Decimal("0.25")
    margin_floor = moneylib.q(unit_cost / (Decimal(1) - target_margin)) if unit_cost else moneylib.ZERO
    if internal_median is not None and external_median is not None:
        market_reference = moneylib.q(
            internal_median * Decimal("0.70") + external_median * Decimal("0.30"),
        )
        basis = "internal_and_external_benchmark"
    elif internal_median is not None:
        market_reference = internal_median
        basis = "internal_market_benchmark"
    elif external_median is not None:
        market_reference = external_median
        basis = "external_market_benchmark"
    else:
        market_reference = None
        basis = "target_margin_estimate"

    competitive_target = moneylib.q(market_reference * Decimal("0.98")) if market_reference is not None else margin_floor
    recommended = max(margin_floor, competitive_target)
    planned = max(moneylib.ZERO, moneylib.q(body.planned_retail_price)) if body.planned_retail_price is not None else recommended
    profit = moneylib.q(planned - unit_cost)
    margin = moneylib.divide(profit * Decimal(100), planned)
    markup = moneylib.divide(profit * Decimal(100), unit_cost)
    return {
        "product_id": body.product_id,
        "unit_cost": moneylib.as_json(unit_cost),
        "planned_retail_price": moneylib.as_json(planned),
        "net_profit_per_unit": moneylib.as_json(profit),
        "profit_margin_percent": moneylib.as_json(margin),
        "markup_percent": moneylib.as_json(markup),
        "recommended_retail_price": moneylib.as_json(recommended),
        "target_margin_floor": moneylib.as_json(margin_floor),
        "market_reference_price": moneylib.as_json(market_reference) if market_reference is not None else None,
        "market_median_retail_price": moneylib.as_json(internal_median or external_median)
        if internal_median is not None or external_median is not None else None,
        "internal_market_median_retail_price": moneylib.as_json(internal_median) if internal_median is not None else None,
        "internal_market_sample_retailers": len(internal_retailer_medians) if internal_median is not None else 0,
        "external_market_median_retail_price": moneylib.as_json(external_median) if external_median is not None else None,
        "external_market_sample_sources": len(provider_medians) if external_median is not None else 0,
        "market_sample_retailers": len(internal_retailer_medians) if internal_median is not None else 0,
        "recommendation_basis": "market_benchmark" if market_reference is not None else "target_margin_estimate",
        "pricing_method": basis,
        "recommendation_note": "Market anchor is undercut by 2% when the 25% gross-margin floor permits it."
        if market_reference is not None else "No trusted market benchmark; recommendation uses a 25% gross-margin target.",
    }


@api.get("/store/integrations")
async def list_store_integrations(user: dict = Depends(require_store_permission("canManageApi"))):
    return await db.store_integrations.find(
        {"retailer_id": store_owner_id(user)}, {"_id": 0, "token_hash": 0},
    ).sort("created_at", -1).to_list(100)


@api.post("/store/integrations")
async def create_store_integration(
    body: StoreIntegrationIn,
    user: dict = Depends(require_store_permission("canManageApi")),
):
    integration_id = str(uuid.uuid4())
    token = "dlpos_" + secrets.token_urlsafe(32)
    integration = {
        "id": integration_id,
        "retailer_id": store_owner_id(user),
        "software": body.software,
        "location_name": body.location_name,
        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "token_prefix": token[:12],
        "active": True,
        "created_at": now_iso(),
        "last_sync_at": None,
    }
    await db.store_integrations.insert_one(dict(integration))
    return {key: value for key, value in integration.items() if key != "token_hash"} | {"token": token}


@api.post("/store/integrations/{integration_id}/rotate")
async def rotate_store_integration(integration_id: str, user: dict = Depends(require_store_permission("canManageApi"))):
    owner_id = store_owner_id(user)
    integration = await db.store_integrations.find_one(
        {"id": integration_id, "retailer_id": owner_id}, {"_id": 0},
    )
    if not integration:
        raise HTTPException(404, "Integration not found.")
    token = "dlpos_" + secrets.token_urlsafe(32)
    await db.store_integrations.update_one({"id": integration_id, "retailer_id": owner_id}, {"$set": {
        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "token_prefix": token[:12],
        "active": True,
        "updated_at": now_iso(),
    }})
    return {
        **{key: value for key, value in integration.items() if key != "token_hash"},
        "token_prefix": token[:12],
        "active": True,
        "token": token,
    }


@api.delete("/store/integrations/{integration_id}")
async def disable_store_integration(integration_id: str, user: dict = Depends(require_store_permission("canManageApi"))):
    result = await db.store_integrations.update_one(
        {"id": integration_id, "retailer_id": store_owner_id(user)},
        {"$set": {"active": False, "updated_at": now_iso()}, "$unset": {"token_hash": ""}},
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Integration not found.")
    return {"ok": True}


async def get_pos_integration(authorization: Optional[str]) -> dict:
    scheme, separator, token = (authorization or "").partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.startswith("dlpos_"):
        raise HTTPException(401, "A valid POS integration bearer token is required.")
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    integration = await db.store_integrations.find_one(
        {"token_hash": token_hash, "active": True}, {"_id": 0, "token_hash": 0},
    )
    if not integration:
        raise HTTPException(401, "POS integration token is invalid or revoked.")
    return integration


@api.get("/store/integrations/orders")
async def integration_order_feed(
    authorization: Optional[str] = Header(None),
    branch_id: Optional[str] = None,
    updated_since: Optional[str] = None,
    after_id: Optional[str] = None,
):
    integration = await get_pos_integration(authorization)
    query = {
        "retailer_id": integration["retailer_id"],
        "external_order": {"$ne": True},
        "status": "Delivered",
    }
    if branch_id:
        branch = await db.store_branches.find_one(
            {"id": branch_id, "retailer_id": integration["retailer_id"]}, {"_id": 0, "id": 1},
        )
        if not branch:
            raise HTTPException(404, "Branch not found.")
        query["branch_id"] = branch_id
    parsed_updated_since = None
    if updated_since:
        try:
            datetime.fromisoformat(updated_since.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(422, "updated_since must be an ISO-8601 timestamp.")
        if after_id:
            query["$or"] = [
                {"updated_at": {"$gt": updated_since}},
                {"updated_at": updated_since, "id": {"$gt": after_id}},
            ]
        else:
            query["updated_at"] = {"$gte": updated_since}
    orders = await db.orders.find(query, {"_id": 0}).sort([("updated_at", 1), ("id", 1)]).to_list(1001)
    has_more = len(orders) > 1000
    orders = orders[:1000]
    await db.store_integrations.update_one({"id": integration["id"]}, {"$set": {"last_sync_at": now_iso()}})
    return {
        "orders": orders,
        "synced_at": now_iso(),
        "next_updated_since": orders[-1].get("updated_at") if has_more and orders else None,
        "next_id": orders[-1].get("id") if has_more and orders else None,
        "has_more": has_more,
    }


@api.post("/store/integrations/sales")
async def ingest_pos_sales(
    body: List[POSSaleIn],
    authorization: Optional[str] = Header(None),
):
    if len(body) > 200:
        raise HTTPException(422, "A sync batch may contain at most 200 sales.")
    integration = await get_pos_integration(authorization)
    retailer_id = integration["retailer_id"]
    processed, duplicate_ids = [], []
    for sale in body:
        branch = await db.store_branches.find_one(
            {"id": sale.branch_id, "retailer_id": retailer_id, "active": True}, {"_id": 0},
        )
        if not branch:
            raise HTTPException(404, f"Branch not found: {sale.branch_id}")
        existing = await db.pos_sales.find_one(
            {"retailer_id": retailer_id, "source_sale_id": sale.sale_id}, {"_id": 0, "id": 1},
        )
        if existing:
            duplicate_ids.append(sale.sale_id)
            continue
        purchased = await db.orders.find({
            "retailer_id": retailer_id,
            "branch_id": sale.branch_id,
            "status": "Delivered",
            "external_order": {"$ne": True},
        }, {"_id": 0, "items": 1}).to_list(10000)
        costs = {}
        for order in purchased:
            for item in order.get("items", []):
                key = item.get("product_id")
                if key:
                    stat = costs.setdefault(key, [moneylib.ZERO, Decimal(0)])
                    quantity = moneylib.dec(item.get("quantity", 0) or 0)
                    stat[0] += moneylib.dec(item.get("unit_price", 0) or 0) * quantity
                    stat[1] += quantity
        normalized = []
        for item in sale.items:
            product_id = item.product_id
            product = None
            if product_id:
                product = await db.products.find_one({"id": product_id}, {"_id": 0, "id": 1, "name": 1, "sku": 1})
            if not product and item.sku:
                product = await db.products.find_one({"sku": item.sku}, {"_id": 0, "id": 1, "name": 1, "sku": 1})
            product_id = (product or {}).get("id") or product_id
            if not product_id or product_id not in costs or costs[product_id][1] <= 0:
                raise HTTPException(422, "Each POS item must match a product purchased and delivered to this branch.")
            normalized.append({
                "product_id": product_id,
                "sku": item.sku or (product or {}).get("sku", ""),
                "product_name": item.product_name or (product or {}).get("name", ""),
                "quantity": float(item.quantity),
                "retail_price": moneylib.as_json(moneylib.q(item.retail_price)),
                "unit_cost": float((costs[product_id][0] / costs[product_id][1]).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
            })
        sold_at = sale.sold_at
        if sold_at.tzinfo is None:
            sold_at = sold_at.replace(tzinfo=timezone.utc)
        sold_at = sold_at.astimezone(timezone.utc)
        document = {
            "id": str(uuid.uuid4()),
            "retailer_id": retailer_id,
            "branch_id": sale.branch_id,
            "integration_id": integration["id"],
            "source_sale_id": sale.sale_id,
            "sold_at": sold_at.isoformat(),
            "items": normalized,
            "created_at": now_iso(),
        }
        await db.pos_sales.insert_one(document)
        processed.append(sale.sale_id)
    await db.store_integrations.update_one({"id": integration["id"]}, {"$set": {"last_sync_at": now_iso()}})
    return {"accepted": processed, "duplicates": duplicate_ids}


@api.get("/store/finance")
async def store_finance(
    supplier_id: Optional[str] = None,
    branch_id: Optional[str] = None,
    payment_status: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user: dict = Depends(require_store_permission("canViewFinancials")),
):
    selected_range = _analytics_date_range(start_date or date_from, end_date or date_to)
    owner_id = store_owner_id(user)
    query = {"retailer_id": owner_id, "external_order": {"$ne": True}, "status": {"$ne": "Cancelled"}}
    if supplier_id:
        query["supplier_id"] = supplier_id
    if branch_id:
        branch = await db.store_branches.find_one(
            {"id": branch_id, "retailer_id": owner_id}, {"_id": 1},
        )
        if not branch:
            raise HTTPException(404, "Branch not found.")
        query["branch_id"] = branch_id
    account_orders = await db.orders.find(query, {"_id": 0}).sort("created_at", -1).to_list(2000)
    history_query = {**query, **_analytics_date_query("created_at", selected_range)}
    orders = account_orders if not selected_range else await db.orders.find(
        history_query, {"_id": 0},
    ).sort("created_at", -1).to_list(2000)
    supplier_ids = list({order["supplier_id"] for order in account_orders if order.get("supplier_id")})
    terms_docs = await db.credit_terms.find(
        {"retailer_id": owner_id, "supplier_id": {"$in": supplier_ids}}, {"_id": 0},
    ).to_list(1000) if supplier_ids else []
    terms_by_supplier = {terms["supplier_id"]: terms for terms in terms_docs}
    finance_orders = []
    for order in orders:
        view = finance_order_view(order, terms_by_supplier.get(order.get("supplier_id")))
        if payment_status and payment_status != "all" and view["payment_status"] != payment_status:
            continue
        finance_orders.append(view)

    accounts = []
    supplier_users = await db.users.find(
        {"id": {"$in": supplier_ids}, "role": "supplier"},
        {"_id": 0, "id": 1, "business_name": 1},
    ).to_list(len(supplier_ids)) if supplier_ids else []
    supplier_names = {supplier["id"]: supplier.get("business_name", "") for supplier in supplier_users}
    for sid in supplier_ids:
        terms = terms_by_supplier.get(sid, {})
        delivered = [
            order for order in account_orders
            if order.get("supplier_id") == sid
            and order.get("status") == "Delivered"
            and order.get("status") != "Cancelled"
        ]
        outstanding = moneylib.total_sum(order_payment_totals(order)[1] for order in delivered)
        limit = moneylib.q(terms.get("credit_limit", 0) or 0)
        due_days = int(terms.get("payment_due_days", 14))
        due_dates = [
            finance_order_view(order, terms).get("payment_due_date")
            for order in delivered if order_payment_totals(order)[1] > 0
        ]
        due_dates = sorted(value for value in due_dates if value)
        accounts.append({
            "supplier_id": sid,
            "supplier_name": supplier_names.get(sid) or next(
                (order.get("supplier_name", "") for order in orders if order.get("supplier_id") == sid), ""
            ),
            "credit_limit": moneylib.as_json(limit),
            "outstanding_balance": moneylib.as_json(outstanding),
            "available_credit": moneylib.as_json(max(moneylib.ZERO, limit - outstanding)),
            "payment_due_days": due_days,
            "next_due_date": due_dates[0] if due_dates else None,
        })
    accounts.sort(key=lambda account: account["supplier_name"].casefold())
    supplier_names = {account["supplier_id"]: account["supplier_name"] for account in accounts}
    due_calendar = []
    for order in account_orders:
        if order.get("status") != "Delivered" or order_payment_totals(order)[1] <= 0:
            continue
        terms = terms_by_supplier.get(order.get("supplier_id"), {})
        view = finance_order_view(order, terms)
        due_date = view.get("payment_due_date")
        if due_date:
            due_calendar.append({
                "date": due_date[:10], "due_at": due_date, "supplier_id": order.get("supplier_id"),
                "supplier_name": supplier_names.get(order.get("supplier_id"), order.get("supplier_name", "")),
                "order_id": order["id"], "order_no": order.get("order_no", ""),
                "amount_due": moneylib.as_json(moneylib.q(view["balance_due"])),
                "payment_status": view["payment_status"],
            })
    due_calendar.sort(key=lambda item: (item["date"], item["supplier_name"].casefold(), item["order_no"]))
    return {"accounts": accounts, "orders": finance_orders, "due_calendar": due_calendar,
            "date_range": {"start_date": selected_range[0].isoformat() if selected_range[0] else None,
                   "end_date": selected_range[1].isoformat() if selected_range[1] else None}
            if selected_range else None}


@api.get("/supplier/credit-accounts")
async def supplier_credit_accounts(
    warehouse_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user: dict = Depends(require_role("supplier")),
):
    require_supplier_permission(user, "finance")
    owner_id = supplier_owner_id(user)
    selected_range = _analytics_date_range(start_date, end_date)
    order_query = {
        "supplier_id": owner_id, "retailer_id": {"$exists": True}, "external_order": {"$ne": True},
        "status": {"$ne": "Cancelled"},
    }
    selected_warehouse_id = await supplier_warehouse_id(user, warehouse_id)
    if selected_warehouse_id:
        order_query["warehouse_id"] = selected_warehouse_id
    all_orders = await db.orders.find(
        order_query,
        {"_id": 0},
    ).sort("created_at", -1).to_list(5000)
    history_query = {**order_query, **_analytics_date_query("created_at", selected_range)}
    orders = all_orders if not selected_range else await db.orders.find(
        history_query, {"_id": 0},
    ).sort("created_at", -1).to_list(5000)
    retailer_ids = list({order["retailer_id"] for order in all_orders if order.get("retailer_id")})
    retailers = await db.users.find(
        {"id": {"$in": retailer_ids}, "role": "retailer"},
        {"_id": 0, "id": 1, "business_name": 1},
    ).to_list(len(retailer_ids)) if retailer_ids else []
    retailer_names = {retailer["id"]: retailer.get("business_name", "") for retailer in retailers}
    terms_docs = await db.credit_terms.find(
        {"supplier_id": owner_id, "retailer_id": {"$in": retailer_ids}}, {"_id": 0},
    ).to_list(1000) if retailer_ids else []
    terms_by_retailer = {terms["retailer_id"]: terms for terms in terms_docs}
    accounts = []
    for retailer_id in retailer_ids:
        lifetime_orders = [order for order in all_orders if order.get("retailer_id") == retailer_id]
        store_orders = [order for order in orders if order.get("retailer_id") == retailer_id]
        delivered_orders = [order for order in lifetime_orders if order.get("status") == "Delivered"]
        terms = terms_by_retailer.get(retailer_id, {})
        outstanding = moneylib.total_sum(order_payment_totals(order)[1] for order in delivered_orders)
        limit = moneylib.q(terms.get("credit_limit", 0) or 0)
        due_calendar = []
        for order in delivered_orders:
            view = finance_order_view(order, terms)
            if view["balance_due"] <= 0 or not view.get("payment_due_date"):
                continue
            due_calendar.append({
                "date": view["payment_due_date"][:10], "due_at": view["payment_due_date"],
                "order_id": order["id"], "order_no": order.get("order_no", ""),
                "amount_due": moneylib.as_json(moneylib.q(view["balance_due"])),
                "payment_status": view["payment_status"],
            })
        due_calendar.sort(key=lambda item: (item["date"], item["order_no"]))
        accounts.append({
            "retailer_id": retailer_id,
            "retailer_name": retailer_names.get(retailer_id) or next(
                (order.get("retailer_name", "") for order in lifetime_orders), ""
            ),
            "credit_limit": moneylib.as_json(limit),
            "outstanding_balance": moneylib.as_json(outstanding),
            "available_credit": moneylib.as_json(max(moneylib.ZERO, limit - outstanding)),
            "payment_due_days": int(terms.get("payment_due_days", 14)),
            "period_sales": moneylib.as_json(moneylib.total_sum(
                order.get("total") for order in store_orders if order.get("status") != "Cancelled"
            )),
            "period_order_count": len(store_orders),
            "due_calendar": due_calendar,
            "orders": [finance_order_view(order, terms) for order in store_orders],
        })
    accounts.sort(key=lambda account: account["retailer_name"].casefold())
    return accounts


@api.put("/supplier/stores/{retailer_id}/credit")
async def update_store_credit_terms(
    retailer_id: str,
    body: StoreCreditTermsIn,
    user: dict = Depends(require_role("supplier")),
):
    require_supplier_permission(user, "finance")
    if user.get("supplier_access_role", "global_admin") != "global_admin":
        raise HTTPException(403, "Only the distributor owner can change store credit terms.")
    owner_id = supplier_owner_id(user)
    relationship = await db.orders.find_one({
        "supplier_id": owner_id, "retailer_id": retailer_id, "external_order": {"$ne": True},
    }, {"_id": 0, "retailer_name": 1})
    if not relationship:
        raise HTTPException(404, "Store not found for this distributor.")
    retailer = await db.users.find_one({"id": retailer_id, "role": "retailer"}, {"_id": 0, "business_name": 1})
    if not retailer:
        raise HTTPException(404, "Store not found.")
    now = now_iso()
    previous_terms = await db.credit_terms.find_one(
        {"supplier_id": owner_id, "retailer_id": retailer_id}, {"_id": 0},
    )
    terms = {
        "supplier_id": owner_id,
        "retailer_id": retailer_id,
        "supplier_name": user.get("business_name", ""),
        "retailer_name": retailer.get("business_name") or relationship.get("retailer_name", ""),
        "credit_limit": moneylib.as_json(moneylib.q(body.credit_limit)),
        "payment_due_days": body.payment_due_days,
        "updated_at": now,
    }
    await db.credit_terms.update_one(
        {"supplier_id": owner_id, "retailer_id": retailer_id},
        {"$set": terms, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    await log_financial_event(
        "credit_terms_changed", user, "credit_terms", f"{owner_id}:{retailer_id}",
        before={k: previous_terms.get(k) for k in ("credit_limit", "payment_due_days")} if previous_terms else None,
        after={"credit_limit": terms["credit_limit"], "payment_due_days": terms["payment_due_days"]},
    )
    return terms


@api.post("/supplier/orders/{oid}/payments")
async def record_order_payment(
    oid: str,
    body: OrderPaymentIn,
    warehouse_id: Optional[str] = None,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    user: dict = Depends(require_role("supplier")),
):
    return await _idempotent(
        f"order-payment:{oid}", user, idempotency_key, body.model_dump(mode="json"),
        lambda: _record_order_payment(oid, body, warehouse_id, user),
    )


async def _record_order_payment(oid: str, body: OrderPaymentIn, warehouse_id: Optional[str], user: dict):
    require_supplier_permission(user, "finance")
    owner_id = supplier_owner_id(user)
    selected_warehouse_id = await supplier_warehouse_id(user, warehouse_id)
    order_query = {"id": oid, "supplier_id": owner_id}
    if selected_warehouse_id:
        order_query["warehouse_id"] = selected_warehouse_id
    order = await db.orders.find_one(order_query, {"_id": 0})
    if not order or order.get("external_order"):
        raise HTTPException(404, "Order not found.")
    if order.get("status") == "Cancelled":
        raise HTTPException(409, "Payments cannot be recorded for a cancelled order.")
    total, balance_float = order_payment_totals(order)
    balance = moneylib.q(balance_float)
    amount = moneylib.q(body.amount)
    if amount <= 0:
        raise HTTPException(422, "Payment amount must be at least ₾0.01.")
    if amount > balance:
        raise HTTPException(409, "Payment amount exceeds the remaining order balance.")
    paid_before = moneylib.q(total) - balance
    amount_value = moneylib.as_json(amount)
    entry = {
        "id": str(uuid.uuid4()),
        "amount": amount_value,
        "method": body.method,
        "reference": body.reference.strip(),
        "note": body.note.strip(),
        "recorded_by": user.get("business_name") or user.get("name", ""),
        "recorded_at": now_iso(),
        "automatic": False,
        "bank_account_snapshot": order.get("bank_account_snapshot"),
    }
    result = await db.orders.update_one(
        {
            "id": oid,
            "supplier_id": owner_id,
            "status": {"$ne": "Cancelled"},
            "$expr": {
                "$lte": [
                    {"$add": [{"$ifNull": ["$amount_paid", 0]}, amount_value]},
                    "$total",
                ],
            },
        },
        {
            "$inc": {"amount_paid": amount_value},
            "$push": {"payment_entries": entry},
            "$set": {"updated_at": now_iso()},
        },
    )
    if result.modified_count != 1:
        raise HTTPException(409, "Order balance changed. Refresh and try again.")
    await sync_order_payment_fields(oid)
    await log_financial_event(
        "payment_recorded", user, "order", oid,
        before={"amount_paid": moneylib.as_json(paid_before), "balance": moneylib.as_json(balance)},
        after={"amount_paid": moneylib.as_json(paid_before + amount), "balance": moneylib.as_json(balance - amount)},
        payment_entry_id=entry["id"], amount=amount_value,
    )
    updated = await db.orders.find_one({"id": oid}, {"_id": 0})
    terms = await db.credit_terms.find_one(
        {"supplier_id": owner_id, "retailer_id": order.get("retailer_id")}, {"_id": 0},
    )
    return finance_order_view(updated, terms)


@api.post("/orders/{oid}/reorder")
async def reorder_preview(oid: str, user: dict = Depends(require_role("retailer"))):
    """Current price/stock for the products of a past order, ready to drop into the cart."""
    order = await db.orders.find_one({"id": oid, "retailer_id": store_owner_id(user)}, {"_id": 0})
    if not order:
        raise HTTPException(404, "Order not found.")
    ids = [i.get("product_id") for i in order.get("items", []) if i.get("product_id")]
    products = {p["id"]: p for p in await db.products.find({"id": {"$in": ids}}, {"_id": 0}).to_list(len(ids) or 1)} if ids else {}
    retailer_id = store_owner_id(user)
    priced_products = await _apply_partner_pricing(list(products.values()), retailer_id) if products else []
    products = {product["id"]: product for product in priced_products}
    available, skipped = [], []
    for item in order.get("items", []):
        p = products.get(item.get("product_id"))
        wanted = int(item.get("quantity") or 1)
        if p and not p.get("can_order"):
            skipped.append({"name": p.get("name") or item.get("name"), "reason": "connection_required"})
            continue
        if not p or int(p.get("stock") or 0) <= 0:
            skipped.append({"name": item.get("name"), "reason": "unavailable"})
            continue
        stock = int(p.get("stock") or 0)
        qty = max(int(p.get("moq") or 1), min(wanted, stock))
        if qty > stock:
            skipped.append({"name": item.get("name"), "reason": "unavailable"})
            continue
        available.append({
            "id": p["id"], "name": p.get("name"), "image": p.get("image", ""),
            "supplier_id": p.get("supplier_id"), "supplier_name": p.get("supplier_name", ""),
            "moq": p.get("moq", 1), "tier_pricing": p.get("tier_pricing", []),
            "price_per_unit": store_order_unit_price(p, qty), "stock": stock,
            "quantity": qty, "limited": qty < wanted,
        })
    return {"items": available, "skipped": skipped}


@api.get("/orders/{oid}/invoice.pdf")
async def order_invoice_pdf(
    oid: str, warehouse_id: Optional[str] = None, user: dict = Depends(get_current_user),
):
    order = await db.orders.find_one({"id": oid, "external_order": {"$ne": True}}, {"_id": 0})
    if not order:
        raise HTTPException(404, "Order not found.")
    if user["role"] == "retailer":
        if order.get("retailer_id") != store_owner_id(user):
            raise HTTPException(404, "Order not found.")
        require_store_owner(user)
        assigned_branch_id = user.get("assigned_branch_id") if user.get("store_access_role") != "global_admin" else None
        if assigned_branch_id and order.get("branch_id") != assigned_branch_id:
            raise HTTPException(404, "Order not found.")
    if user["role"] == "supplier":
        require_supplier_permission(user, "finance")
        selected_warehouse_id = await supplier_warehouse_id(user, warehouse_id)
        if order.get("supplier_id") != supplier_owner_id(user) or (
            selected_warehouse_id and order.get("warehouse_id") != selected_warehouse_id
        ):
            raise HTTPException(404, "Order not found.")
    if user["role"] not in {"retailer", "supplier"}:
        raise HTTPException(403, "Not allowed.")
    if order.get("status") == "Cancelled":
        raise HTTPException(409, "ინვოისი გაუქმებული შეკვეთისთვის ხელმისაწვდომი არ არის.")
    pdf = await _render_order_invoice(order)
    return StreamingResponse(
        io.BytesIO(pdf),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{order["order_no"]}-invoice.pdf"'},
    )


async def _render_order_invoice(order: dict) -> bytes:
    order.setdefault("amount_paid", order.get("total", 0) if order.get("paid_at_checkout") or order.get("payment_status") == "Succeeded" else 0)
    supplier = await db.users.find_one(
        {"id": order.get("supplier_id")}, {"_id": 0, "password_hash": 0},
    ) or {}
    supplier = _decrypt_sensitive_fields(supplier)
    buyer = await db.users.find_one(
        {"id": order.get("retailer_id")}, {"_id": 0, "password_hash": 0},
    ) or {}
    terms = await db.credit_terms.find_one(
        {"supplier_id": order.get("supplier_id"), "retailer_id": order.get("retailer_id")},
        {"_id": 0},
    )
    due_date = finance_order_view(order, terms).get("payment_due_date")
    connections = getattr(db, "store_distributor_connections", None)
    connection = (await connections.find_one(
        {"store_id": order.get("retailer_id"), "distributor_id": order.get("supplier_id")},
        {"_id": 0, "discount_percent": 1},
    ) if connections is not None else None) or {}
    product_ids = [i.get("product_id") for i in order.get("items", []) if i.get("product_id")]
    products_collection = getattr(db, "products", None)
    products = {
        p["id"]: p for p in (await products_collection.find(
            {"id": {"$in": product_ids}}, {"_id": 0, "id": 1, "sku": 1, "discount_exempt": 1},
        ).to_list(len(product_ids) or 1) if products_collection is not None and product_ids else [])
    }
    order["items"] = [
        {**i, "sku": i.get("sku") or products.get(i.get("product_id"), {}).get("sku", ""),
         "discount_exempt": bool(i.get("discount_exempt") or products.get(i.get("product_id"), {}).get("discount_exempt"))}
        for i in order.get("items", [])
    ]
    order["discount_percent"] = float(connection.get("discount_percent") or 0)
    return build_order_invoice_pdf(order, supplier=supplier, buyer=buyer, due_date=due_date)


@api.post("/orders/{oid}/invoice/share")
async def share_order_invoice(
    oid: str, body: OrderInvoiceShareIn, user: dict = Depends(get_current_user),
):
    order = await db.orders.find_one({"id": oid, "external_order": {"$ne": True}}, {"_id": 0})
    if not order:
        raise HTTPException(404, "Order not found.")
    if user["role"] == "retailer":
        if order.get("retailer_id") != store_owner_id(user):
            raise HTTPException(404, "Order not found.")
    elif user["role"] == "supplier":
        if order.get("supplier_id") != supplier_owner_id(user):
            raise HTTPException(404, "Order not found.")
    else:
        raise HTTPException(403, "Not allowed.")
    new_email = str(body.email).strip().lower() if body.email else ""
    recipient = new_email or str(user.get("accountant_email") or user.get("email") or "").strip()
    if not recipient:
        raise HTTPException(422, "Accountant email is not set.")
    sender_name = user.get("business_name") or user.get("name") or "Distro Logistics user"
    ref = order.get("payment_reference", "")
    if order.get("status") == "Cancelled":
        raise HTTPException(409, "ინვოისი გაუქმებული შეკვეთისთვის ხელმისაწვდომი არ არის.")
    order_no = order.get("order_no", "")
    pdf = await _render_order_invoice(order)
    html = (
        f"<h2>Invoice {html_escape(order_no)} / ინვოისი {html_escape(order_no)}</h2>"
        f"<p>Sent by: {html_escape(sender_name)}</p>"
        f"<p>Total: ₾{float(order.get('total', 0) or 0):.2f}</p>"
        f"<p>Payment method: {html_escape(str(order.get('payment_method') or 'cash'))}</p>"
        + (f"<p><strong>Payment reference:</strong> {html_escape(ref)}</p>" if ref else "")
        + f"<p>The full invoice PDF is attached to this email (Invoice_{html_escape(order_no)}.pdf). / "
          "ინვოისის სრული PDF დოკუმენტი მიმაგრებულია ამ წერილზე.</p>"
    )
    sent, reason = await try_send_email_detailed(
        to=recipient,
        subject=f"Invoice {order_no} from {sender_name}",
        html=html,
        attachments=[{"filename": f"Invoice_{order_no}.pdf", "content": pdf, "content_type": "application/pdf"}],
    )
    if not sent:
        raise HTTPException(503, f"ინვოისის გაგზავნა ვერ მოხერხდა. მიზეზი: {reason}")
    if new_email and new_email != (user.get("accountant_email") or "").lower():
        await db.users.update_one({"id": user["id"]}, {"$set": {"accountant_email": new_email}})
    return {"ok": True, "email": recipient}


@api.get("/supplier/stores")
async def list_supplier_stores(
    warehouse_id: Optional[str] = None, user: dict = Depends(require_role("supplier")),
):
    require_supplier_permission(user, "orders")
    owner_id = supplier_owner_id(user)
    order_query = {"supplier_id": owner_id}
    selected_warehouse_id = await supplier_warehouse_id(user, warehouse_id)
    if selected_warehouse_id:
        order_query["warehouse_id"] = selected_warehouse_id
    orders = await db.orders.find(
        order_query,
        {"_id": 0, "retailer_id": 1, "retailer_name": 1, "delivery_address": 1, "customer_phone": 1, "created_at": 1},
    ).sort("created_at", -1).to_list(2000)
    retailer_ids = list({
        order["retailer_id"] for order in orders
        if order.get("retailer_id")
    })
    retailers = await db.users.find(
        {"id": {"$in": retailer_ids}, "role": "retailer"},
        {"_id": 0, "id": 1, "phone": 1, "address": 1},
    ).to_list(len(retailer_ids)) if retailer_ids else []
    retailer_profiles = {retailer["id"]: retailer for retailer in retailers}

    stores = {}
    for order in orders:
        retailer_id = order.get("retailer_id") or ""
        retailer = retailer_profiles.get(retailer_id, {})
        name = (order.get("retailer_name") or "").strip()
        address = (order.get("delivery_address") or retailer.get("address") or "").strip()
        if not name or not address:
            continue
        key = retailer_id or f"{name.casefold()}|{address.casefold()}"
        store = stores.setdefault(key, {
            "id": key,
            "name": name,
            "address": address,
            "phone": (order.get("customer_phone") or retailer.get("phone") or "").strip(),
        })
        if not store["phone"]:
            store["phone"] = (order.get("customer_phone") or retailer.get("phone") or "").strip()
    return sorted(stores.values(), key=lambda store: store["name"].casefold())


@api.post("/external-orders")
async def create_external_order(
    body: ManualExternalOrderIn,
    warehouse_id: Optional[str] = None,
    user: dict = Depends(require_role("supplier")),
):
    require_supplier_permission(user, "orders")
    owner_id = supplier_owner_id(user)
    selected_warehouse_id = await supplier_warehouse_id(user, warehouse_id)
    routed_warehouse_id = selected_warehouse_id or await _warehouse_for_supplier_location(
        owner_id, body.delivery_address,
    )
    order_id = str(uuid.uuid4())
    order_no = "EXT-" + order_id[:8].upper()
    item_product_id = str(uuid.uuid4())
    if body.product_id:
        product = await db.products.find_one({"id": body.product_id, "supplier_id": owner_id}, {"_id": 0, "id": 1})
        if not product:
            raise HTTPException(404, "Product not found.")
        item_product_id = product["id"]
        await deduct_inventory(
            [{"supplier_id": owner_id, "product_id": item_product_id,
              "warehouse_id": routed_warehouse_id, "quantity": body.quantity}],
            sale_source="external", reference=order_no,
            out_of_stock_detail="Insufficient stock for this product.",
        )
    item = {
        "product_id": item_product_id,
        "name": body.item_name,
        "image": "",
        "supplier_id": owner_id,
        "quantity": body.quantity,
        "unit_price": moneylib.as_json(moneylib.q(body.unit_price)),
    }
    order = {
        "id": order_id,
        "order_no": order_no,
        "retailer_id": "",
        "retailer_name": body.customer_name,
        "retailer_tax_id": "",
        "retailer_establishment": "",
        "supplier_id": owner_id,
        "warehouse_id": routed_warehouse_id,
        "supplier_name": user.get("business_name") or user.get("name", ""),
        "supplier_tax_id": user.get("identification_number", ""),
        "items": [item],
        "total": moneylib.as_json(moneylib.q(moneylib.dec(body.unit_price) * body.quantity)),
        "service_fee": 0,
        "fee_payer": "",
        "fee_type": "",
        "fee_value": 0,
        "status": "Processing",
        "delivery_address": body.delivery_address,
        "customer_phone": body.customer_phone.strip(),
        "notes": body.notes or "",
        "delivery_window": body.delivery_window or "",
        "payment_method": "external",
        "amount_paid": 0,
        "payment_entries": [],
        "payment_status": "External",
        "external_order": True,
        "source": "external",
        "sale_source": "external",
        "is_external": True,
        "external_order_source": "supplier_manual_entry",
        "timeline": [{"status": "Processing", "at": now_iso()}],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.orders.insert_one(dict(order))
    return clean(order)


class ExternalSaleLine(BaseModel):
    product_id: Optional[str] = Field(default=None, max_length=100)
    sku: Optional[str] = Field(default=None, max_length=100)
    barcode: Optional[str] = Field(default=None, max_length=100)
    external_id: Optional[str] = Field(default=None, max_length=100)
    quantity: int = Field(ge=1, le=1000000)
    unit_price: Optional[float] = Field(default=None, ge=0)


class ExternalSaleSyncIn(BaseModel):
    external_ref: Optional[str] = Field(default=None, max_length=120)
    source_system: str = Field(default="", max_length=60)
    customer_name: str = Field(default="External sale", max_length=160)
    items: List[ExternalSaleLine] = Field(min_length=1, max_length=500)


class InventorySyncLine(BaseModel):
    product_id: Optional[str] = Field(default=None, max_length=100)
    sku: Optional[str] = Field(default=None, max_length=100)
    barcode: Optional[str] = Field(default=None, max_length=100)
    external_id: Optional[str] = Field(default=None, max_length=100)
    quantity: int = Field(ge=0, le=100000000)


class InventorySyncIn(BaseModel):
    source_system: str = Field(default="", max_length=60)
    mode: str = Field(default="set", pattern="^(set|add)$")
    items: List[InventorySyncLine] = Field(min_length=1, max_length=5000)


async def _find_supplier_product(owner_id: str, line) -> Optional[dict]:
    for field in ("product_id", "sku", "barcode", "external_id"):
        value = (getattr(line, field, None) or "").strip()
        if not value:
            continue
        keys = ("id", "sku", "barcode", "external_id") if field == "product_id" else (field,)
        for key in keys:
            product = await db.products.find_one({"supplier_id": owner_id, key: value}, {"_id": 0})
            if product:
                return product
        return None
    return None


class ErpSaleLine(BaseModel):
    productId: str = Field(min_length=1, max_length=100)
    quantity: int = Field(ge=1, le=1000000)
    price: Optional[float] = Field(default=None, ge=0)


class ErpSaleIn(BaseModel):
    storeName: str = Field(min_length=1, max_length=160)
    items: List[ErpSaleLine] = Field(min_length=1, max_length=500)
    externalRef: Optional[str] = Field(default=None, max_length=120)
    sourceSystem: str = Field(default="", max_length=60)


async def _default_warehouse_id(owner_id: str) -> Optional[str]:
    warehouse_collection = getattr(db, "supplier_warehouses", None)
    if warehouse_collection is None:
        return None
    default = await warehouse_collection.find_one(
        {"supplier_id": owner_id, "active": True, "is_default": True}, {"_id": 0, "id": 1},
    )
    return default["id"] if default else None


async def record_external_sale(
    supplier: dict, owner_id: str, customer_name: str, lines: list, external_ref: Optional[str],
    source_system: str, warehouse_id: Optional[str],
) -> dict:
    """Create a source='external' (0% commission) order and deduct central stock immediately."""
    if external_ref:
        existing = await db.orders.find_one({"supplier_id": owner_id, "external_ref": external_ref}, {"_id": 0})
        if existing:
            return {**clean(existing), "duplicate": True}
    selected_warehouse_id = warehouse_id or await _default_warehouse_id(owner_id)

    merged, missing = {}, []
    for index, line in enumerate(lines):
        product = await _find_supplier_product(owner_id, line)
        if not product:
            missing.append(index)
            continue
        price = moneylib.as_json(moneylib.q(line.unit_price if line.unit_price is not None
                                            else product.get("price_per_unit", 0)))
        if product["id"] in merged:
            merged[product["id"]]["quantity"] += line.quantity
        else:
            merged[product["id"]] = {
                "product_id": product["id"], "name": product["name"], "image": product.get("image", ""),
                "supplier_id": owner_id, "quantity": line.quantity, "unit_price": price,
            }
    if missing:
        raise HTTPException(404, f"Products not found for item positions: {missing}")
    items = list(merged.values())

    order_id = str(uuid.uuid4())
    order_no = "EXT-" + order_id[:8].upper()
    await deduct_inventory(
        [{"supplier_id": owner_id, "product_id": i["product_id"],
          "warehouse_id": selected_warehouse_id, "quantity": i["quantity"]} for i in items],
        sale_source="external", reference=order_no,
        out_of_stock_detail="Insufficient stock for one or more products.",
    )
    total = moneylib.as_json(moneylib.total_sum(moneylib.dec(i["unit_price"]) * i["quantity"] for i in items))
    now = now_iso()
    order = {
        "id": order_id, "order_no": order_no, "source": "external", "sale_source": "external",
        "retailer_id": "", "retailer_name": customer_name.strip() or "External sale",
        "retailer_tax_id": "", "retailer_establishment": "",
        "supplier_id": owner_id, "warehouse_id": selected_warehouse_id,
        "supplier_name": supplier.get("business_name") or supplier.get("name", ""),
        "supplier_tax_id": supplier.get("identification_number", ""),
        "items": items, "total": total, "service_fee": 0, "fee_payer": "", "fee_type": "", "fee_value": 0,
        "status": "Delivered", "delivered_at": now, "delivery_address": "",
        "notes": "", "delivery_window": "", "payment_method": "external",
        "amount_paid": total, "payment_entries": [], "payment_status": "External",
        "external_order": True, "is_external": True,
        "external_order_source": source_system or "api",
        "timeline": [{"status": "Delivered", "at": now}],
        "created_at": now, "updated_at": now,
    }
    if external_ref:
        order["external_ref"] = external_ref
    await db.orders.insert_one(dict(order))
    return {**clean(order), "duplicate": False}


@api.post("/orders/external")
@api.post("/external-orders/sync")
async def sync_external_sale(
    body: ExternalSaleSyncIn,
    warehouse_id: Optional[str] = None,
    user: dict = Depends(require_role("supplier")),
):
    """Record a sale made outside the app (manual entry / ERP) and deduct central stock immediately."""
    require_supplier_permission(user, "orders")
    owner_id = supplier_owner_id(user)
    selected = await supplier_warehouse_id(user, warehouse_id)
    return await record_external_sale(
        user, owner_id, body.customer_name, body.items, body.external_ref, body.source_system, selected,
    )


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


async def api_key_supplier(request: Request) -> dict:
    key = (request.headers.get("x-api-key") or "").strip()
    if not key:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer ") and auth[7:].strip().startswith("dk_"):
            key = auth[7:].strip()
    if not key.startswith("dk_"):
        raise HTTPException(401, "Missing or invalid API key.")
    record = await db.api_keys.find_one({"key_hash": hash_api_key(key)}, {"_id": 0})
    if record:
        await db.api_keys.update_one({"id": record["id"]}, {"$set": {"last_used_at": now_iso()}})
    supplier = await db.users.find_one(
        {"id": record["supplier_id"], "role": "supplier"}, {"_id": 0, "password_hash": 0},
    ) if record else None
    if not supplier or supplier.get("status") in ("blocked", "suspended", "rejected"):
        raise HTTPException(401, "Missing or invalid API key.")
    return supplier


@api.post("/v1/sync/external-sale")
async def erp_sync_external_sale(body: ErpSaleIn, supplier: dict = Depends(api_key_supplier)):
    """Webhook for external ERPs (FINA, Oris, scripts). Authenticated by the distributor's API key."""
    lines = [ExternalSaleLine(product_id=i.productId, quantity=i.quantity, unit_price=i.price) for i in body.items]
    return await record_external_sale(
        supplier, supplier["id"], body.storeName, lines, body.externalRef, body.sourceSystem or "erp", None,
    )


def _integration_info(record: Optional[dict]) -> dict:
    return {
        "has_key": bool(record),
        "key_prefix": (record or {}).get("prefix", ""),
        "created_at": (record or {}).get("created_at"),
        "last_used_at": (record or {}).get("last_used_at"),
        "webhook_path": "/api/v1/sync/external-sale",
    }


def _require_integration_owner(user: dict) -> None:
    if user.get("role") != "supplier" or user.get("supplier_access_role", "global_admin") != "global_admin":
        raise HTTPException(403, "Only the distributor owner can manage API keys.")


@api.get("/supplier/integrations")
async def get_supplier_integrations(user: dict = Depends(require_role("supplier"))):
    _require_integration_owner(user)
    return _integration_info(await db.api_keys.find_one({"supplier_id": user["id"]}, {"_id": 0}))


@api.post("/supplier/integrations/api-key")
async def rotate_supplier_api_key(user: dict = Depends(require_role("supplier"))):
    """Generate (or replace) the API key. The full key is returned only once; only its hash is stored."""
    _require_integration_owner(user)
    key = "dk_" + secrets.token_urlsafe(32)
    record = {"id": str(uuid.uuid4()), "supplier_id": user["id"], "key_hash": hash_api_key(key),
              "prefix": key[:10], "created_at": now_iso()}
    await db.api_keys.delete_many({"supplier_id": user["id"]})
    await db.api_keys.insert_one(dict(record))
    return {**_integration_info(record), "api_key": key}


@api.delete("/supplier/integrations/api-key")
async def revoke_supplier_api_key(user: dict = Depends(require_role("supplier"))):
    _require_integration_owner(user)
    await db.api_keys.delete_many({"supplier_id": user["id"]})
    return {"has_key": False}


@api.post("/inventory/sync")
async def sync_inventory(
    body: InventorySyncIn,
    warehouse_id: Optional[str] = None,
    user: dict = Depends(require_role("supplier")),
):
    """Set (default) or add (restock) product quantities pushed from an external ERP / spreadsheet import."""
    require_supplier_permission(user, "inventory")
    owner_id = supplier_owner_id(user)
    selected_warehouse_id = await supplier_warehouse_id(user, warehouse_id)
    warehouse_collection = getattr(db, "supplier_warehouses", None)
    if not selected_warehouse_id and warehouse_collection is not None:
        default = await warehouse_collection.find_one(
            {"supplier_id": owner_id, "active": True, "is_default": True}, {"_id": 0, "id": 1},
        )
        selected_warehouse_id = default["id"] if default else None
    inventory = getattr(db, "warehouse_inventory", None)
    use_warehouse = bool(selected_warehouse_id and inventory is not None)

    updated, not_found = [], []
    for index, line in enumerate(body.items):
        product = await _find_supplier_product(owner_id, line)
        if not product:
            not_found.append(index)
            continue
        if use_warehouse:
            key = {"supplier_id": owner_id, "product_id": product["id"], "warehouse_id": selected_warehouse_id}
            current_doc = await inventory.find_one(key, {"_id": 0, "stock": 1})
            current = int(current_doc.get("stock", 0) or 0) if current_doc else int(product.get("stock", 0) or 0)
            new_stock = line.quantity if body.mode == "set" else current + line.quantity
            await inventory.update_one(
                key,
                {"$set": {"stock": new_stock, "updated_at": now_iso()},
                 "$setOnInsert": {"id": str(uuid.uuid4()), **key}},
                upsert=True,
            )
        else:
            current = int(product.get("stock", 0) or 0)
            new_stock = line.quantity if body.mode == "set" else current + line.quantity
            await db.products.update_one(
                {"id": product["id"], "supplier_id": owner_id},
                {"$set": {"stock": new_stock, "updated_at": now_iso()}},
            )
        movements = getattr(db, "inventory_movements", None)
        if movements is not None:
            await movements.insert_one({
                "id": str(uuid.uuid4()), "type": "sync_" + body.mode, "sale_source": None,
                "reference": body.source_system, "supplier_id": owner_id, "product_id": product["id"],
                "warehouse_id": selected_warehouse_id if use_warehouse else None,
                "quantity": new_stock - current, "created_at": now_iso(),
            })
        updated.append({"index": index, "product_id": product["id"], "name": product.get("name", ""),
                        "previous_stock": current, "stock": new_stock})
    return {"mode": body.mode, "source_system": body.source_system, "updated": updated,
            "updated_count": len(updated), "not_found": not_found}


_geocode_lock = asyncio.Lock()
_last_geocode_at = 0.0


async def _geocode_address(address: str) -> dict:
    global _last_geocode_at
    async with _geocode_lock:
        wait_seconds = 1.05 - (time.monotonic() - _last_geocode_at)
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)
        try:
            async with httpx.AsyncClient(timeout=15, headers={
                "User-Agent": "DistroLogistics/1.0",
                "Accept-Language": "ka,en",
            }) as http:
                response = await http.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={"q": address, "format": "jsonv2", "limit": 1, "countrycodes": "ge"},
                )
                response.raise_for_status()
                results = response.json()
        except (httpx.HTTPError, ValueError) as error:
            logger.exception("OpenStreetMap geocoding request failed")
            raise HTTPException(502, "Address lookup is temporarily unavailable. Please try again.")
        finally:
            _last_geocode_at = time.monotonic()
        if not isinstance(results, list) or not results:
            raise HTTPException(422, "Could not locate an address. Add a clearer street address and city.")
        try:
            return {"lat": float(results[0]["lat"]), "lon": float(results[0]["lon"])}
        except (KeyError, TypeError, ValueError) as error:
            logger.exception("OpenStreetMap returned invalid geocoding coordinates")
            raise HTTPException(502, "Address lookup returned invalid coordinates.") from error


@api.post("/delivery-routes/optimize")
async def optimize_delivery_route(
    body: DeliveryRouteIn,
    warehouse_id: Optional[str] = None,
    user: dict = Depends(require_role("supplier")),
):
    require_supplier_permission(user, "routes")
    owner_id = supplier_owner_id(user)
    selected_warehouse_id = await supplier_warehouse_id(user, warehouse_id)
    if not selected_warehouse_id:
        raise HTTPException(400, "Select a warehouse before optimizing a delivery route.")
    if (body.origin_lat is None) != (body.origin_lon is None):
        raise HTTPException(400, "Both current-location coordinates are required.")

    active_order_query = {
        "supplier_id": owner_id,
        "warehouse_id": selected_warehouse_id,
        "status": {"$in": ["Processing", "In Transit"]},
        "$or": [{"payment_method": {"$nin": ["tbc", "bog"]}}, {"payment_status": "Succeeded"}],
    }
    if body.order_ids:
        if len(set(body.order_ids)) != len(body.order_ids):
            raise HTTPException(400, "Delivery IDs must be unique.")
        active_order_query["id"] = {"$in": body.order_ids}
    active_orders = await db.orders.find(active_order_query, {"_id": 0}).sort("created_at", 1).to_list(50)
    if body.order_ids and {order["id"] for order in active_orders} != set(body.order_ids):
        raise HTTPException(400, "One or more selected orders are not eligible for delivery routing.")
    if len(set(body.replace_route_ids)) != len(body.replace_route_ids):
        raise HTTPException(400, "Route IDs to replace must be unique.")
    if body.replace_route_ids:
        routes_to_replace = await db.delivery_routes.find({
            "id": {"$in": body.replace_route_ids},
            "supplier_id": owner_id, "warehouse_id": selected_warehouse_id,
            "status": "assigned",
        }, {"_id": 0, "id": 1, "stops.order_id": 1}).to_list(100)
        if {route["id"] for route in routes_to_replace} != set(body.replace_route_ids):
            raise HTTPException(409, "One or more scheduled routes to combine were not found.")
        replaced_order_ids = {
            stop["order_id"]
            for saved_route in routes_to_replace
            for stop in saved_route.get("stops", [])
        }
        active_replaced_orders = await db.orders.find({
            "id": {"$in": list(replaced_order_ids)},
            "supplier_id": owner_id, "warehouse_id": selected_warehouse_id,
            "status": {"$in": ["Processing", "In Transit"]},
            "$or": [{"payment_method": {"$nin": ["tbc", "bog"]}}, {"payment_status": "Succeeded"}],
        }, {"_id": 0, "id": 1}).to_list(24)
        active_replaced_order_ids = {order["id"] for order in active_replaced_orders}
        if not active_replaced_order_ids.issubset(set(body.order_ids or [])):
            raise HTTPException(400, "The combined route must keep every active delivery from the selected scheduled routes.")
    existing_routes = await db.delivery_routes.find(
        {
            "supplier_id": owner_id, "warehouse_id": selected_warehouse_id,
            "status": "assigned",
            "id": {"$nin": body.replace_route_ids},
        },
        {"_id": 0, "stops.order_id": 1},
    ).to_list(100)
    reserved_order_ids = {
        stop["order_id"]
        for saved_route in existing_routes
        for stop in saved_route.get("stops", [])
    }
    active_orders = [order for order in active_orders if order["id"] not in reserved_order_ids]
    if not active_orders:
        raise HTTPException(404, "There are no unassigned active deliveries to route.")
    if len(active_orders) > 24:
        raise HTTPException(400, "Route optimization supports up to 24 active stops at a time.")

    warehouse = await db.supplier_warehouses.find_one(
        {"id": selected_warehouse_id, "supplier_id": owner_id}, {"_id": 0},
    ) or {}
    if body.origin_lat is not None and body.origin_lon is not None:
        if not (-90 <= body.origin_lat <= 90 and -180 <= body.origin_lon <= 180):
            raise HTTPException(422, "Current-location coordinates are out of range.")
        origin = {"lat": body.origin_lat, "lon": body.origin_lon}
    else:
        warehouse_address = ", ".join(
            part.strip() for part in (warehouse.get("address"), warehouse.get("city"), "Georgia")
            if part and part.strip()
        )
        if not warehouse_address or warehouse_address == "Georgia":
            raise HTTPException(400, "Add an address to the selected warehouse or share your current location.")
        origin = warehouse.get("route_coordinates")
        if (
            warehouse.get("route_origin_address") != warehouse_address
            or not isinstance(origin, dict)
            or not isinstance(origin.get("lat"), (float, int))
            or not isinstance(origin.get("lon"), (float, int))
        ):
            origin = await _geocode_address(warehouse_address)
            await db.supplier_warehouses.update_one({"id": selected_warehouse_id, "supplier_id": owner_id}, {"$set": {
                "route_coordinates": origin, "route_origin_address": warehouse_address,
            }})

    stops = []
    for order in active_orders:
        address = ", ".join(
            part.strip() for part in (
                order.get("delivery_address"), warehouse.get("city"), "Georgia",
            ) if part and part.strip()
        )
        coordinates = order.get("route_coordinates")
        if (
            order.get("route_address") != order.get("delivery_address", "")
            or not isinstance(coordinates, dict)
            or not isinstance(coordinates.get("lat"), (int, float))
            or not isinstance(coordinates.get("lon"), (int, float))
        ):
            try:
                coordinates = await _geocode_address(address)
            except HTTPException as error:
                if error.status_code == 422:
                    raise HTTPException(422, f"Could not locate delivery for order {order.get('order_no', '')}. Check its delivery address.")
                raise
            await db.orders.update_one({"id": order["id"], "supplier_id": owner_id}, {
                "$set": {"route_coordinates": coordinates, "route_address": order.get("delivery_address", "")}
            })
        stops.append({
            "order_id": order["id"],
            "order_no": order.get("order_no", ""),
            "retailer_name": order.get("retailer_name", ""),
            "address": order.get("delivery_address", ""),
            "delivery_window": order.get("delivery_window", ""),
            "status": order.get("status", ""),
            "is_external": bool(order.get("external_order") or order.get("is_external")),
            "lat": coordinates["lat"],
            "lon": coordinates["lon"],
        })

    coordinates = [f"{origin['lon']},{origin['lat']}"] + [f"{stop['lon']},{stop['lat']}" for stop in stops]
    coordinate_path = ";".join(coordinates)
    try:
        async with httpx.AsyncClient(timeout=45) as http:
            response = await http.get(
                f"https://router.project-osrm.org/trip/v1/driving/{coordinate_path}",
                params={
                    "source": "first", "destination": "any", "roundtrip": "false",
                    "overview": "full", "geometries": "geojson", "steps": "false",
                },
                headers={"User-Agent": "DistroLogistics/1.0"},
            )
            response.raise_for_status()
            route_result = response.json()
    except (httpx.HTTPError, ValueError):
        logger.exception("OpenStreetMap route optimization request failed")
        raise HTTPException(502, "Driving route optimization is temporarily unavailable. Please try again.")

    try:
        trip = route_result["trips"][0]
        geometry = trip["geometry"]["coordinates"]
        waypoints = route_result["waypoints"]
        if len(waypoints) != len(stops) + 1 or not geometry:
            raise ValueError("Route result does not include every requested stop.")
        ordered_stops = sequence_stops(stops, waypoints)
        route = {
            "id": str(uuid.uuid4()),
            "supplier_id": owner_id, "warehouse_id": selected_warehouse_id,
            "supplier_name": user.get("business_name") or user.get("name", ""),
            "origin": origin,
            "stops": ordered_stops,
            "geometry": geometry,
            "distance_meters": round(float(trip["distance"])),
            "duration_seconds": round(float(trip["duration"])),
            "provider": "OpenStreetMap / OSRM",
            "status": "draft",
            "driver_name": "",
            "driver_phone": "",
            "scheduled_at": "",
            "share_token_hash": "",
            "share_expires_at": "",
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        await db.delivery_routes.insert_one(dict(route))
        return {key: value for key, value in route.items() if key != "share_token_hash"}
    except (KeyError, IndexError, TypeError, ValueError) as error:
        logger.exception("OpenStreetMap returned an invalid optimized route")
        raise HTTPException(502, "The routing service returned an invalid route. Please try again.") from error


@api.get("/drivers")
async def list_supplier_drivers(
    warehouse_id: Optional[str] = None, user: dict = Depends(require_role("supplier")),
):
    require_supplier_permission(user, "drivers")
    owner_id = supplier_owner_id(user)
    query = {"supplier_id": owner_id}
    selected_warehouse_id = await supplier_warehouse_id(user, warehouse_id)
    if selected_warehouse_id:
        query["warehouse_id"] = selected_warehouse_id
    return await db.drivers.find(query, {"_id": 0}).sort("name", 1).to_list(250)


@api.post("/drivers")
async def create_supplier_driver(
    body: DriverIn, warehouse_id: Optional[str] = None,
    user: dict = Depends(require_role("supplier")),
):
    require_supplier_permission(user, "drivers")
    owner_id = supplier_owner_id(user)
    selected_warehouse_id = await supplier_warehouse_id(user, warehouse_id)
    if not selected_warehouse_id:
        warehouse = await db.supplier_warehouses.find_one(
            {"supplier_id": owner_id, "active": True, "is_default": True}, {"_id": 0, "id": 1},
        )
        selected_warehouse_id = warehouse["id"] if warehouse else None
    driver = {
        "id": str(uuid.uuid4()),
        "supplier_id": owner_id, "warehouse_id": selected_warehouse_id,
        "name": body.name,
        "phone": body.phone,
        "vehicle_plate": body.vehicle_plate,
        "personal_id": body.personal_id.strip(),
        "transport_type": body.transport_type.strip(),
        "working_days": body.working_days,
        "active": body.active,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.drivers.insert_one(dict(driver))
    return driver


@api.put("/drivers/{driver_id}")
async def update_supplier_driver(
    driver_id: str,
    body: DriverIn,
    warehouse_id: Optional[str] = None,
    user: dict = Depends(require_role("supplier")),
):
    require_supplier_permission(user, "drivers")
    owner_id = supplier_owner_id(user)
    selected_warehouse_id = await supplier_warehouse_id(user, warehouse_id)
    driver_query = {"id": driver_id, "supplier_id": owner_id}
    if selected_warehouse_id:
        driver_query["warehouse_id"] = selected_warehouse_id
    result = await db.drivers.update_one(
        driver_query,
        {"$set": {
            "name": body.name,
            "phone": body.phone,
            "vehicle_plate": body.vehicle_plate,
            "personal_id": body.personal_id.strip(),
            "transport_type": body.transport_type.strip(),
            "working_days": body.working_days,
            "active": body.active,
            "updated_at": now_iso(),
        }},
    )
    if not result.matched_count:
        raise HTTPException(404, "Driver not found.")
    return await db.drivers.find_one(driver_query, {"_id": 0})


@api.delete("/drivers/{driver_id}")
async def delete_supplier_driver(
    driver_id: str, warehouse_id: Optional[str] = None,
    user: dict = Depends(require_role("supplier")),
):
    require_supplier_permission(user, "drivers")
    owner_id = supplier_owner_id(user)
    selected_warehouse_id = await supplier_warehouse_id(user, warehouse_id)
    driver_query = {"id": driver_id, "supplier_id": owner_id}
    if selected_warehouse_id:
        driver_query["warehouse_id"] = selected_warehouse_id
    existing = await db.drivers.find_one(driver_query, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Driver not found.")
    assigned = await db.delivery_routes.find_one({
        "supplier_id": owner_id, "driver_id": driver_id, "status": "assigned",
        "scheduled_at": {"$gte": now_iso()},
    }, {"_id": 0, "id": 1})
    if assigned:
        raise HTTPException(409, "Driver has a scheduled route. Reassign or remove that route first.")
    await db.drivers.delete_one(driver_query)
    return {"ok": True}


@api.get("/delivery-routes")
async def list_delivery_routes(
    warehouse_id: Optional[str] = None, user: dict = Depends(require_role("supplier")),
):
    require_supplier_permission(user, "routes")
    owner_id = supplier_owner_id(user)
    query = {"supplier_id": owner_id}
    selected_warehouse_id = await supplier_warehouse_id(user, warehouse_id)
    if selected_warehouse_id:
        query["warehouse_id"] = selected_warehouse_id
    routes = await db.delivery_routes.find(
        query, {"_id": 0, "share_token_hash": 0},
    ).sort("updated_at", -1).to_list(100)
    return routes


async def _supplier_live_driver_snapshot(supplier_id: str, warehouse_id: Optional[str] = None) -> List[dict]:
    query = {"supplier_id": supplier_id, "status": "assigned", "tracking_active": True}
    if warehouse_id:
        query["warehouse_id"] = warehouse_id
    routes = await db.delivery_routes.find(query, {"_id": 0, "share_token_hash": 0}).to_list(250)
    live_drivers = []
    for route in routes:
        order_ids = [stop.get("order_id") for stop in route.get("stops", []) if stop.get("order_id")]
        orders = await db.orders.find({
            "id": {"$in": order_ids}, "supplier_id": supplier_id, "status": "In Transit",
        }, {"_id": 0, "id": 1, "order_no": 1, "retailer_name": 1}).to_list(24)
        if not orders:
            continue
        live_drivers.append({
            "route_id": route["id"], "driver_id": route.get("driver_id"),
            "driver_name": route.get("driver_name", ""), "driver_phone": route.get("driver_phone", ""),
            "warehouse_id": route.get("warehouse_id"), "driver_location": route.get("driver_location"),
            "location_updated_at": (route.get("driver_location") or {}).get("recorded_at"),
            "geometry": route.get("geometry", []),
            "orders": orders,
        })
    return live_drivers


@api.get("/supplier/live-drivers")
async def list_live_supplier_drivers(
    warehouse_id: Optional[str] = None,
    user: dict = Depends(require_role("supplier")),
):
    require_supplier_permission(user, "routes")
    selected_warehouse_id = await supplier_warehouse_id(user, warehouse_id)
    return {"drivers": await _supplier_live_driver_snapshot(supplier_owner_id(user), selected_warehouse_id)}


@app.websocket("/ws/supplier/live-drivers")
async def supplier_live_driver_socket(websocket: WebSocket):
    await websocket.accept()
    user = await authenticate_websocket(websocket)
    if not user:
        return
    if user.get("role") != "supplier":
        await websocket.close(code=1008, reason="Distributor account required")
        return
    try:
        require_supplier_permission(user, "routes")
        requested_warehouse = websocket.query_params.get("warehouse_id")
        warehouse_id = await supplier_warehouse_id(user, requested_warehouse)
    except HTTPException:
        await websocket.close(code=1008, reason="Route access denied")
        return
    supplier_id = supplier_owner_id(user)
    await websocket.send_json({
        "type": "snapshot",
        "drivers": await _supplier_live_driver_snapshot(supplier_id, warehouse_id),
    })
    location_sockets.connect_supplier(supplier_id, warehouse_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        location_sockets.disconnect_supplier(supplier_id, websocket)


@api.post("/delivery-routes/{route_id}/reorder")
async def reorder_delivery_route_stops(
    route_id: str,
    body: RouteStopOrderIn,
    warehouse_id: Optional[str] = None,
    user: dict = Depends(require_role("supplier")),
):
    require_supplier_permission(user, "routes")
    owner_id = supplier_owner_id(user)
    selected_warehouse_id = await supplier_warehouse_id(user, warehouse_id)
    route_query = {"id": route_id, "supplier_id": owner_id}
    if selected_warehouse_id:
        route_query["warehouse_id"] = selected_warehouse_id
    route = await db.delivery_routes.find_one(route_query, {"_id": 0})
    if not route:
        raise HTTPException(404, "Delivery route not found.")

    stops_by_id = {stop.get("order_id"): stop for stop in route.get("stops", [])}
    if len(body.stop_order) != len(stops_by_id) or set(body.stop_order) != set(stops_by_id):
        raise HTTPException(400, "Stop order must include every route delivery exactly once.")
    ordered_stops = [
        {**stops_by_id[order_id], "sequence": sequence}
        for sequence, order_id in enumerate(body.stop_order, start=1)
    ]
    coordinates = [route["origin"], *ordered_stops]
    coordinate_path = ";".join(f"{point['lon']},{point['lat']}" for point in coordinates)
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            response = await http.get(
                f"https://router.project-osrm.org/route/v1/driving/{coordinate_path}",
                params={"overview": "full", "geometries": "geojson", "steps": "false"},
                headers={"User-Agent": "DistroLogistics/1.0"},
            )
            response.raise_for_status()
            route_result = response.json()
        optimized = route_result["routes"][0]
        geometry = optimized["geometry"]["coordinates"]
        if not geometry:
            raise ValueError("Route result does not include geometry.")
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as error:
        logger.exception("OpenStreetMap failed to recalculate reordered delivery stops")
        raise HTTPException(502, "Could not recalculate the route in the selected stop order.") from error

    updated = {
        "stops": ordered_stops,
        "geometry": geometry,
        "distance_meters": round(float(optimized["distance"])),
        "duration_seconds": round(float(optimized["duration"])),
        "provider": "OpenStreetMap / OSRM",
        "traffic_aware": False,
        "share_token_hash": "",
        "share_expires_at": "",
        "updated_at": now_iso(),
    }
    result = await db.delivery_routes.update_one(route_query, {"$set": updated})
    if result.modified_count != 1:
        raise HTTPException(409, "Route changed while its stops were being reordered. Refresh and try again.")
    return {**route, **updated}


@api.put("/delivery-routes/{route_id}/assignment")
async def assign_delivery_route(
    route_id: str,
    body: RouteAssignmentIn,
    warehouse_id: Optional[str] = None,
    user: dict = Depends(require_role("supplier")),
):
    require_supplier_permission(user, "routes")
    owner_id = supplier_owner_id(user)
    selected_warehouse_id = await supplier_warehouse_id(user, warehouse_id)
    route_query = {"id": route_id, "supplier_id": owner_id}
    if selected_warehouse_id:
        route_query["warehouse_id"] = selected_warehouse_id
    route = await db.delivery_routes.find_one(
        route_query, {"_id": 0},
    )
    if not route:
        raise HTTPException(404, "Delivery route not found.")

    replace_route_ids = body.replace_route_ids
    if len(set(replace_route_ids)) != len(replace_route_ids) or route_id in replace_route_ids:
        raise HTTPException(400, "Route IDs to replace must be unique and cannot include the new route.")
    routes_to_replace = []
    if replace_route_ids:
        routes_to_replace = await db.delivery_routes.find({
            "id": {"$in": replace_route_ids},
            "supplier_id": owner_id, "warehouse_id": route.get("warehouse_id"),
            "status": "assigned",
        }, {"_id": 0, "id": 1, "driver_id": 1, "scheduled_at": 1, "stops.order_id": 1}).to_list(100)
        if {saved_route["id"] for saved_route in routes_to_replace} != set(replace_route_ids):
            raise HTTPException(409, "One or more scheduled routes to combine were not found.")
        georgia_tz = ZoneInfo("Asia/Tbilisi")
        scheduled_day = body.scheduled_at.astimezone(georgia_tz).date()
        if any(
            saved_route.get("driver_id") != body.driver_id
            or datetime.fromisoformat(saved_route["scheduled_at"]).astimezone(georgia_tz).date() != scheduled_day
            for saved_route in routes_to_replace
        ):
            raise HTTPException(409, "Only routes for the same driver and scheduled date can be combined.")

    route_order_ids = [stop["order_id"] for stop in route.get("stops", [])]
    eligible_orders = await db.orders.find({
        "id": {"$in": route_order_ids},
        "supplier_id": owner_id, "warehouse_id": route.get("warehouse_id"),
        "status": {"$in": ["Processing", "In Transit"]},
        "$or": [{"payment_method": {"$nin": ["tbc", "bog"]}}, {"payment_status": "Succeeded"}],
    }, {"_id": 0, "id": 1}).to_list(24)
    eligible_order_ids = {order["id"] for order in eligible_orders}
    if eligible_order_ids != set(route_order_ids):
        raise HTTPException(409, "One or more deliveries are no longer eligible for route assignment.")
    if routes_to_replace:
        replaced_active_order_ids = {
            stop["order_id"]
            for saved_route in routes_to_replace
            for stop in saved_route.get("stops", [])
            if stop.get("order_id") in eligible_order_ids
        }
        if not replaced_active_order_ids.issubset(set(route_order_ids)):
            raise HTTPException(400, "The combined route must keep every active delivery from the scheduled routes.")
    assigned_routes = await db.delivery_routes.find(
        {
            "supplier_id": owner_id, "warehouse_id": route.get("warehouse_id"),
            "status": "assigned",
            "id": {"$nin": [route_id, *replace_route_ids]},
        },
        {"_id": 0, "stops.order_id": 1},
    ).to_list(100)
    assigned_order_ids = {
        stop["order_id"]
        for saved_route in assigned_routes
        for stop in saved_route.get("stops", [])
    }
    if assigned_order_ids.intersection(route_order_ids):
        raise HTTPException(409, "One or more deliveries are already assigned to another route.")

    driver = await db.drivers.find_one(
        {"id": body.driver_id, "supplier_id": owner_id, "warehouse_id": route.get("warehouse_id")}, {"_id": 0},
    )
    if not driver:
        raise HTTPException(404, "Driver not found.")
    if driver.get("active", True) is False:
        raise HTTPException(409, "This driver is inactive and cannot be assigned.")
    georgia_tz = ZoneInfo("Asia/Tbilisi")
    scheduled_weekday = body.scheduled_at.astimezone(georgia_tz).isoweekday()
    if scheduled_weekday not in driver.get("working_days", [1, 2, 3, 4, 5]):
        raise HTTPException(409, "This driver is not scheduled to work on the selected weekday.")

    if body.traffic_route:
        route_stops = {stop["order_id"]: stop for stop in route["stops"]}
        if (
            len(body.traffic_route.stop_order) != len(route_stops)
            or set(body.traffic_route.stop_order) != set(route_stops)
        ):
            raise HTTPException(400, "Traffic-optimized route does not match the saved deliveries.")
        ordered_stops = [
            {**route_stops[order_id], "sequence": sequence}
            for sequence, order_id in enumerate(body.traffic_route.stop_order, start=1)
        ]
    else:
        ordered_stops = route["stops"]

    updated = {
        "stops": ordered_stops,
        "driver_id": driver["id"],
        "driver_name": driver["name"],
        "driver_phone": driver["phone"],
        "scheduled_at": body.scheduled_at.astimezone(timezone.utc).isoformat(),
        "status": "assigned",
        "provider": "Google Maps · Live traffic" if body.traffic_route else route["provider"],
        "share_token_hash": "",
        "share_expires_at": "",
        "updated_at": now_iso(),
    }
    if body.traffic_route:
        updated.update({
            "geometry": [list(point) for point in body.traffic_route.geometry],
            "distance_meters": body.traffic_route.distance_meters,
            "duration_seconds": body.traffic_route.duration_seconds,
            "traffic_aware": True,
        })
    await db.delivery_routes.update_one(route_query, {"$set": updated})
    if replace_route_ids:
        await db.delivery_routes.delete_many({
            "id": {"$in": replace_route_ids},
            "supplier_id": owner_id, "warehouse_id": route.get("warehouse_id"),
            "status": "assigned",
        })
    return {
        **{key: value for key, value in route.items() if key not in {"_id", "share_token_hash"}},
        **{key: value for key, value in updated.items() if key != "share_token_hash"},
    }


@api.post("/delivery-routes/{route_id}/dispatch")
async def dispatch_delivery_route(
    route_id: str, warehouse_id: Optional[str] = None,
    user: dict = Depends(require_role("supplier")),
):
    require_supplier_permission(user, "routes")
    owner_id = supplier_owner_id(user)
    selected_warehouse_id = await supplier_warehouse_id(user, warehouse_id)
    route_query = {"id": route_id, "supplier_id": owner_id, "status": "assigned"}
    if selected_warehouse_id:
        route_query["warehouse_id"] = selected_warehouse_id
    route = await db.delivery_routes.find_one(
        route_query,
        {"_id": 0, "driver_phone": 1, "driver_name": 1},
    )
    if not route:
        raise HTTPException(404, "Assigned route not found.")
    share_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    await db.delivery_routes.update_one(route_query, {"$set": {
        "share_token_hash": hashlib.sha256(share_token.encode("utf-8")).hexdigest(),
        "share_expires_at": expires_at.isoformat(),
        "updated_at": now_iso(),
    }})
    return {
        "share_token": share_token,
        "driver_name": route.get("driver_name", ""),
        "driver_phone": route["driver_phone"],
        "expires_at": expires_at.isoformat(),
    }


@api.delete("/delivery-routes/{route_id}")
async def delete_delivery_route(
    route_id: str, warehouse_id: Optional[str] = None,
    user: dict = Depends(require_role("supplier")),
):
    require_supplier_permission(user, "routes")
    owner_id = supplier_owner_id(user)
    selected_warehouse_id = await supplier_warehouse_id(user, warehouse_id)
    route_query = {"id": route_id, "supplier_id": owner_id}
    if selected_warehouse_id:
        route_query["warehouse_id"] = selected_warehouse_id
    result = await db.delivery_routes.delete_one(route_query)
    if not result.deleted_count:
        raise HTTPException(404, "Delivery route not found.")
    return {"ok": True}


@api.get("/delivery-routes/shared/{share_token}")
async def get_shared_delivery_route(share_token: str):
    route = await _load_shared_route(share_token)
    route_order_ids = [stop.get("order_id") for stop in route.get("stops", []) if stop.get("order_id")]
    live_orders = {
        order["id"]: order for order in await db.orders.find({
            "id": {"$in": route_order_ids}, "supplier_id": route["supplier_id"],
        }, {"_id": 0}).to_list(24)
    }
    shared_stops = []
    for stop in route.get("stops", []):
        order = live_orders.get(stop.get("order_id"), {})
        shared_stops.append({
            **stop,
            "is_external": bool(stop.get("is_external") or stop.get("external_order")
                                or order.get("external_order") or order.get("is_external")),
            "status": order.get("status", stop.get("status")),
            "lifecycle_status": lifecycle_status(order) if order else "",
            "items": [
                {"name": item.get("name", ""), "quantity": item.get("quantity", 0)}
                for item in order.get("items", [])
            ],
            "payment_method": order.get("payment_method", ""),
            **(order_payment_fields(order) if order else {}),
        })
    return {
        "id": route["id"],
        "supplier_name": route.get("supplier_name", ""),
        "driver_name": route.get("driver_name", ""),
        "driver_phone": route.get("driver_phone", ""),
        "scheduled_at": route.get("scheduled_at", ""),
        "origin": route["origin"],
        "stops": shared_stops,
        "geometry": route["geometry"],
        "distance_meters": route["distance_meters"],
        "duration_seconds": route["duration_seconds"],
        "provider": route["provider"],
        "status": route["status"],
        "started_at": route.get("started_at", ""),
        "tracking_active": bool(route.get("tracking_active")),
    }


async def _load_shared_route(share_token: str) -> dict:
    token_hash = hashlib.sha256(share_token.encode("utf-8")).hexdigest()
    route = await db.delivery_routes.find_one(
        {"share_token_hash": token_hash, "status": "assigned"}, {"_id": 0},
    )
    if not route:
        raise HTTPException(404, "This driver route link is invalid or has been revoked.")
    try:
        expires_at = datetime.fromisoformat(route["share_expires_at"])
    except (KeyError, TypeError, ValueError) as error:
        logger.exception("Assigned delivery route has an invalid share-link expiry")
        raise HTTPException(410, "This driver route link has expired.") from error
    if expires_at <= datetime.now(timezone.utc):
        raise HTTPException(410, "This driver route link has expired.")
    return route


@api.post("/delivery-routes/shared/{share_token}/location")
async def update_shared_driver_location(share_token: str, body: DriverLocationIn):
    route = await _load_shared_route(share_token)
    if not route.get("tracking_active") or not route.get("started_at"):
        raise HTTPException(409, "Driver location is accepted only while the route is in progress.")
    recorded_at = now_iso()
    location = {
        "lat": body.lat, "lon": body.lon,
        "accuracy_meters": body.accuracy_meters, "recorded_at": recorded_at,
    }
    result = await db.delivery_routes.update_one(
        {"id": route["id"], "status": "assigned", "tracking_active": True},
        {"$set": {"driver_location": location, "updated_at": recorded_at}},
    )
    if result.modified_count != 1:
        raise HTTPException(409, "Route tracking is no longer active.")

    order_ids = [stop.get("order_id") for stop in route.get("stops", []) if stop.get("order_id")]
    active_orders = await db.orders.find({
        "id": {"$in": order_ids}, "supplier_id": route["supplier_id"], "status": "In Transit",
    }, {"_id": 0, "id": 1, "retailer_id": 1}).to_list(24)
    if not active_orders:
        await db.delivery_routes.update_one(
            {"id": route["id"]}, {"$set": {"tracking_active": False}, "$unset": {"driver_location": ""}},
        )
        raise HTTPException(409, "No deliveries on this route are in transit.")

    event = {
        "type": "location", "route_id": route["id"], "driver_id": route.get("driver_id"),
        "driver_name": route.get("driver_name", ""), "driver_phone": route.get("driver_phone", ""),
        "warehouse_id": route.get("warehouse_id"), "driver_location": location,
        "geometry": route.get("geometry", []),
    }
    await location_sockets.broadcast_supplier(route["supplier_id"], route.get("warehouse_id"), event)
    for order in active_orders:
        if order.get("retailer_id"):
            await location_sockets.broadcast_order(order["id"], {
                "type": "location", "order_id": order["id"],
                "driver_name": route.get("driver_name", ""), "driver_location": location,
            })
    return {"ok": True, "recorded_at": recorded_at}


async def _store_order_tracking_data(order: dict) -> dict:
    route = await db.delivery_routes.find_one({
        "supplier_id": order["supplier_id"], "tracking_active": True,
        "stops.order_id": order["id"],
    }, {"_id": 0, "id": 1, "driver_name": 1, "driver_location": 1})
    destination = order.get("route_coordinates") or {}
    return {
        "order_id": order["id"], "status": order["status"],
        "driver_name": route.get("driver_name", "") if route else "",
        "driver_location": route.get("driver_location") if route else None,
        "destination": {"lat": destination.get("lat"), "lon": destination.get("lon")}
        if destination.get("lat") is not None and destination.get("lon") is not None else None,
    }


@api.get("/orders/{oid}/tracking")
async def get_store_order_tracking(oid: str, user: dict = Depends(require_role("retailer"))):
    owner_id = store_owner_id(user)
    order = await db.orders.find_one({"id": oid, "retailer_id": owner_id}, {"_id": 0})
    if not order:
        raise HTTPException(404, "Order not found.")
    assigned_branch_id = user.get("assigned_branch_id") if user.get("store_access_role") != "global_admin" else None
    if assigned_branch_id and order.get("branch_id") != assigned_branch_id:
        raise HTTPException(404, "Order not found.")
    if order.get("status") != "In Transit":
        raise HTTPException(409, "Live tracking is available only while the order is in transit.")
    return await _store_order_tracking_data(order)


@app.websocket("/ws/orders/{order_id}/tracking")
async def store_order_tracking_socket(websocket: WebSocket, order_id: str):
    await websocket.accept()
    user = await authenticate_websocket(websocket)
    if not user:
        return
    if user.get("role") != "retailer":
        await websocket.close(code=1008, reason="Store account required")
        return
    owner_id = store_owner_id(user)
    order = await db.orders.find_one({"id": order_id, "retailer_id": owner_id}, {"_id": 0})
    assigned_branch_id = user.get("assigned_branch_id") if user.get("store_access_role") != "global_admin" else None
    if not order or (assigned_branch_id and order.get("branch_id") != assigned_branch_id):
        await websocket.close(code=1008, reason="Order access denied")
        return
    if order.get("status") != "In Transit":
        await websocket.close(code=1008, reason="Order is not in transit")
        return
    await websocket.send_json({"type": "snapshot", **await _store_order_tracking_data(order)})
    location_sockets.connect_order(order_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        location_sockets.disconnect_order(order_id, websocket)


@api.post("/delivery-routes/shared/{share_token}/start")
async def start_shared_delivery_route(share_token: str):
    route = await _load_shared_route(share_token)
    order_ids = [stop["order_id"] for stop in route.get("stops", []) if stop.get("order_id")]
    orders = await db.orders.find({
        "id": {"$in": order_ids}, "supplier_id": route["supplier_id"], "status": "Processing",
        "$or": [{"payment_method": {"$nin": ["tbc", "bog"]}}, {"payment_status": "Succeeded"}],
    }, {"_id": 0}).to_list(24)
    for order in orders:
        await apply_order_status(order, "In Transit")
    await db.delivery_routes.update_one(
        {"id": route["id"], "status": "assigned"},
        {"$set": {
            "started_at": route.get("started_at") or now_iso(),
            "tracking_active": bool(orders) or bool(route.get("tracking_active")),
        }},
    )
    return {"in_transit": [order["id"] for order in orders]}


@api.post("/delivery-routes/shared/{share_token}/orders/{oid}/deliver")
async def deliver_shared_route_order(share_token: str, oid: str, body: DriverDeliverIn):
    route = await _load_shared_route(share_token)
    if oid not in {stop.get("order_id") for stop in route.get("stops", [])}:
        raise HTTPException(404, "Order is not part of this route.")
    order = await db.orders.find_one({"id": oid, "supplier_id": route["supplier_id"]}, {"_id": 0})
    if not order:
        raise HTTPException(404, "Order not found.")
    if order.get("status") not in {"Processing", "In Transit"}:
        raise HTTPException(409, "Only approved or in-transit orders can be delivered.")
    if order.get("payment_method") in {"tbc", "bog"} and order.get("payment_status") != "Succeeded":
        raise HTTPException(409, "Order actions are unavailable until the bank confirms payment.")
    if order.get("payment_method") == "bank_transfer" and order_payment_fields(order)["paymentStatus"] != "PAID":
        raise HTTPException(409, "Order actions are unavailable until the transfer is confirmed.")
    total, balance = order_payment_totals(order)
    if body.payment == "cash" and balance > 0 and not order.get("external_order"):
        entry = {
            "id": str(uuid.uuid4()), "amount": balance, "method": "cash", "reference": "",
            "note": "Cash collected by driver on delivery",
            "recorded_by": route.get("driver_name", "driver"), "recorded_at": now_iso(), "automatic": True,
        }
        result = await db.orders.update_one(
            {"id": oid, "status": {"$in": ["Processing", "In Transit"]}},
            {"$inc": {"amount_paid": balance}, "$push": {"payment_entries": entry}},
        )
        if result.modified_count != 1:
            raise HTTPException(409, "Order changed. Refresh and try again.")
    elif body.payment == "credit":
        await db.orders.update_one({"id": oid}, {"$set": {"delivered_on_credit": True}})
    order = await db.orders.find_one({"id": oid}, {"_id": 0})
    await apply_order_status(order, "Delivered")
    await sync_order_payment_fields(oid)
    await db.delivery_routes.update_one(
        {"id": route["id"], "stops.order_id": oid}, {"$set": {"stops.$.status": "Delivered"}},
    )
    final = await db.orders.find_one({"id": oid}, {"_id": 0})
    route_order_ids = [stop.get("order_id") for stop in route.get("stops", []) if stop.get("order_id")]
    remaining = await db.orders.find({
        "id": {"$in": route_order_ids}, "supplier_id": route["supplier_id"],
        "status": {"$in": ["Processing", "In Transit"]},
    }, {"_id": 0, "id": 1}).to_list(24)
    if not remaining:
        await db.delivery_routes.update_one(
            {"id": route["id"]},
            {"$set": {"tracking_active": False, "updated_at": now_iso()}, "$unset": {"driver_location": ""}},
        )
        await location_sockets.broadcast_supplier(route["supplier_id"], route.get("warehouse_id"), {
            "type": "route_completed", "route_id": route["id"],
        })
    return {"id": oid, "status": final["status"], "lifecycle_status": lifecycle_status(final), **order_payment_fields(final)}


@api.post("/orders/{oid}/waybill")
async def create_order_waybill(
    oid: str,
    body: WaybillDispatchIn,
    user: dict = Depends(require_role("supplier")),
):
    require_supplier_permission(user, "orders")
    owner_id = supplier_owner_id(user)
    selected_warehouse_id = await supplier_warehouse_id(user)
    order_query = {"id": oid, "supplier_id": owner_id}
    if selected_warehouse_id:
        order_query["warehouse_id"] = selected_warehouse_id
    order = await db.orders.find_one(order_query, {"_id": 0})
    if not order:
        raise HTTPException(404, "Order not found")
    if order.get("status") not in {"Processing", "In Transit", "Delivered"}:
        raise HTTPException(409, "A waybill can only be generated for an accepted order.")

    seller = await db.users.find_one({"id": owner_id}, {"_id": 0}) or user
    buyer = await db.users.find_one({"id": order.get("retailer_id")}, {"_id": 0}) or {}
    items = [{
        "name": item.get("name", ""),
        "quantity": item.get("quantity", 0),
        "unit": item.get("unit") or "ერთეული",
        "unit_price": moneylib.as_json(moneylib.q(item.get("unit_price", 0))),
        "line_total": moneylib.as_json(moneylib.q(moneylib.dec(item.get("quantity", 0)) * moneylib.dec(item.get("unit_price", 0)))),
    } for item in order.get("items", [])]
    if not items:
        raise HTTPException(422, "Order has no products to include in the waybill.")

    now = datetime.now(ZoneInfo("Asia/Tbilisi"))
    waybill_number = f"WBL-{now:%Y%m%d}-{uuid.uuid4().hex[:10].upper()}"
    document = {
        "waybill_no": waybill_number,
        "issued_at": now.strftime("%d.%m.%Y %H:%M"),
        "order_no": order.get("order_no", oid),
        "delivery_address": order.get("delivery_address", ""),
        "seller": {
            "name": seller.get("business_name") or order.get("supplier_name", ""),
            "tax_id": seller.get("identification_number") or order.get("supplier_tax_id", ""),
            "address": seller.get("address", ""), "phone": seller.get("phone", ""),
        },
        "buyer": {
            "name": buyer.get("business_name") or order.get("retailer_name", ""),
            "tax_id": buyer.get("identification_number") or order.get("retailer_tax_id", ""),
            "address": order.get("delivery_address") or buyer.get("address", ""),
            "phone": buyer.get("phone", ""),
        },
        "dispatch": body.model_dump(),
        "items": items,
        "total": moneylib.as_json(moneylib.total_sum(item["line_total"] for item in items)),
    }
    html = build_waybill_html(document).encode("utf-8")
    return StreamingResponse(
        io.BytesIO(html), media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{waybill_number}.html"'},
    )

VALID_STATUS = ["Pending Payment", "Pending", "Processing", "In Transit", "Delivered", "Cancelled"]


async def apply_order_status(order: dict, status: str, actor_is_retailer: bool = False,
                             reason: Optional[str] = None, rejected: bool = False) -> None:
    now = now_iso()
    entry = {"status": status, "at": now}
    if reason:
        entry["reason"] = reason
    set_fields = {
        "status": status, "updated_at": now,
        "timeline": [*order.get("timeline", []), entry],
    }
    if status == "Cancelled":
        set_fields["rejected"] = rejected
        set_fields["rejection_reason"] = (reason or "") if rejected else ""
    if status == "Delivered" and not order.get("delivered_at"):
        set_fields["delivered_at"] = now
        if not order.get("external_order"):
            set_fields["commission_amount"] = order.get("service_fee", moneylib.as_json(moneylib.percent_of(order.get("total", 0), 5)))
    await db.orders.update_one({"id": order["id"]}, {"$set": set_fields})
    if status != "In Transit":
        await location_sockets.broadcast_order(order["id"], {"type": "status", "status": status})
    target = order["supplier_id"] if actor_is_retailer else order["retailer_id"]
    status_ka = {
        "Pending Payment": "ელოდება გადარიცხვას",
        "Pending": "მოლოდინშია", "Processing": "დამტკიცებულია", "In Transit": "გზაშია",
        "Delivered": "მიწოდებულია", "Cancelled": "გაუქმებულია",
    }[status]
    if rejected:
        status_ka = "უარყოფილია" + (f" ({reason})" if reason else "")
    if target:
        await notify(
            target, f"შეკვეთის №{order['order_no']} სტატუსი შეიცვალა: {status_ka}.",
            "status", order_id=order["id"],
        )


@api.put("/orders/{oid}/status")
async def update_order_status(oid: str, body: StatusUpdate, user: dict = Depends(get_current_user)):
    order = await db.orders.find_one({"id": oid})
    if not order:
        raise HTTPException(404, "Order not found")
    requested = str(body.status or "").strip()
    rejected = requested.upper() == "REJECTED"
    status = STATUS_BY_LIFECYCLE.get(requested.upper(), requested)
    if status not in VALID_STATUS:
        raise HTTPException(400, "Invalid status")
    # supplier owns status transitions; retailer may only cancel own pending order
    if user["role"] == "supplier":
        require_supplier_permission(user, "orders")
        selected_warehouse_id = await supplier_warehouse_id(user)
        if order["supplier_id"] != supplier_owner_id(user) or (
            selected_warehouse_id and order.get("warehouse_id") != selected_warehouse_id
        ):
            raise HTTPException(404, "Order not found")
        if user.get("billing_frozen") and status != "Cancelled":
            raise HTTPException(403, "Account frozen due to an overdue commission invoice. Settle the outstanding invoice to resume accepting orders.")
        if rejected and order.get("status") != "Pending":
            raise HTTPException(409, "Only NEW orders can be rejected.")
    elif user["role"] == "retailer":
        owner_id = store_owner_id(user)
        if not effective_store_permissions(user)["canManageOrders"]:
            raise HTTPException(403, "Permission required: canManageOrders")
        assigned_branch_id = user.get("assigned_branch_id") if user.get("store_access_role") != "global_admin" else None
        if (
            order["retailer_id"] != owner_id
            or (assigned_branch_id and order.get("branch_id") != assigned_branch_id)
            or status != "Cancelled" or rejected or order.get("status") != "Pending"
        ):
            raise HTTPException(403, "Not allowed")
    elif user["role"] != "admin":
        raise HTTPException(403, "Not allowed")
    if order.get("payment_method") in {"tbc", "bog"} and order.get("payment_status") != "Succeeded":
        raise HTTPException(409, "Order actions are unavailable until the bank confirms payment.")
    await apply_order_status(order, status, user["role"] == "retailer", (body.reason or "").strip() or None, rejected)
    updated = await db.orders.find_one({"id": oid}, {"_id": 0})
    updated["lifecycle_status"] = lifecycle_status(updated)
    return updated


async def _mark_order_bank_paid(order: dict, reference: str, source: str) -> None:
    if order.get("external_order"):
        raise HTTPException(409, "External orders cannot be auto-paid.")
    total = moneylib.as_json(moneylib.q(order.get("total", 0) or 0))
    ref = str(reference or order.get("payment_reference") or "").strip()
    entry_id = f"{source}-{order['id']}"
    entries = list(order.get("payment_entries", []))
    if not any(entry.get("id") == entry_id for entry in entries):
        entries.append({
            "id": entry_id,
            "amount": total,
            "method": "bank_transfer",
            "reference": ref,
            "note": "Bank transfer confirmed",
            "recorded_by": "system",
            "recorded_at": now_iso(),
            "automatic": True,
        })
    await db.orders.update_one({"id": order["id"]}, {"$set": {
        "amount_paid": total,
        "paymentStatus": "PAID",
        "paidAmount": total,
        "totalAmount": total,
        "balance": 0.0,
        "payment_state": "paid",
        "payment_entries": entries,
        "updated_at": now_iso(),
    }})
    latest = await db.orders.find_one({"id": order["id"]}, {"_id": 0})
    if latest and latest.get("status") == "Pending Payment":
        await apply_order_status(latest, "Pending")
        latest = await db.orders.find_one({"id": order["id"]}, {"_id": 0})
    if latest:
        await notify(
            latest["retailer_id"],
            f"შეკვეთის №{latest['order_no']} საბანკო გადარიცხვა დადასტურდა.",
            "payment", order_id=latest["id"],
        )
        await notify(
            latest["supplier_id"],
            f"შეკვეთის №{latest['order_no']} საბანკო გადარიცხვა დადასტურდა.",
            "payment", order_id=latest["id"],
        )


@api.post("/supplier/orders/{oid}/confirm-bank-transfer")
async def confirm_order_bank_transfer(oid: str, user: dict = Depends(require_role("supplier"))):
    require_supplier_permission(user, "orders")
    query = {"id": oid, "supplier_id": supplier_owner_id(user)}
    selected_warehouse_id = await supplier_warehouse_id(user)
    if selected_warehouse_id:
        query["warehouse_id"] = selected_warehouse_id
    order = await db.orders.find_one(query, {"_id": 0})
    if not order:
        raise HTTPException(404, "Order not found.")
    if order.get("payment_method") != "bank_transfer":
        raise HTTPException(409, "Only bank transfer orders can be confirmed.")
    if order_payment_fields(order)["paymentStatus"] == "PAID":
        return {"ok": True, "already_paid": True}
    await _mark_order_bank_paid(order, order.get("payment_reference", ""), "supplier-confirm")
    return {"ok": True}


async def _supplier_orders_for_bulk(user: dict, order_ids: List[str]) -> List[dict]:
    require_supplier_permission(user, "orders")
    query = {"id": {"$in": list(set(order_ids))}, "supplier_id": supplier_owner_id(user)}
    selected_warehouse_id = await supplier_warehouse_id(user)
    if selected_warehouse_id:
        query["warehouse_id"] = selected_warehouse_id
    return await db.orders.find(query, {"_id": 0}).to_list(200)


@api.post("/supplier/orders/bulk-status")
async def bulk_update_order_status(body: BulkStatusIn, user: dict = Depends(require_role("supplier"))):
    requested = body.status.strip().upper()
    rules = {  # target lifecycle -> required current internal status
        "APPROVED": "Pending", "IN_TRANSIT": "Processing", "REJECTED": "Pending",
    }
    if requested not in rules:
        raise HTTPException(400, "Bulk status must be APPROVED, IN_TRANSIT or REJECTED.")
    if user.get("billing_frozen"):
        raise HTTPException(403, "Account frozen due to an overdue commission invoice.")
    orders = {order["id"]: order for order in await _supplier_orders_for_bulk(user, body.order_ids)}
    updated, skipped = [], []
    for order_id in dict.fromkeys(body.order_ids):
        order = orders.get(order_id)
        if not order:
            skipped.append({"id": order_id, "reason": "Order not found"})
        elif order.get("status") != rules[requested]:
            skipped.append({"id": order_id, "reason": f"Order is {lifecycle_status(order)}"})
        elif order.get("payment_method") in {"tbc", "bog"} and order.get("payment_status") != "Succeeded":
            skipped.append({"id": order_id, "reason": "Bank payment not confirmed"})
        else:
            await apply_order_status(
                order, STATUS_BY_LIFECYCLE[requested], False,
                (body.reason or "").strip() or None, requested == "REJECTED",
            )
            updated.append(order_id)
    return {"updated": updated, "skipped": skipped}


@api.post("/supplier/orders/bulk-assign-driver")
async def bulk_assign_driver(body: BulkAssignDriverIn, user: dict = Depends(require_role("supplier"))):
    require_supplier_permission(user, "routes")
    owner_id = supplier_owner_id(user)
    driver = await db.drivers.find_one({"id": body.driver_id, "supplier_id": owner_id}, {"_id": 0})
    if not driver:
        raise HTTPException(404, "Driver not found.")
    if driver.get("active", True) is False:
        raise HTTPException(409, "This driver is inactive and cannot be assigned.")
    orders = {order["id"]: order for order in await _supplier_orders_for_bulk(user, body.order_ids)}
    updated, skipped = [], []
    for order_id in dict.fromkeys(body.order_ids):
        order = orders.get(order_id)
        if not order:
            skipped.append({"id": order_id, "reason": "Order not found"})
        elif order.get("status") not in {"Processing", "In Transit"}:
            skipped.append({"id": order_id, "reason": "Approve the order before assigning a driver"})
        elif order.get("warehouse_id") != driver.get("warehouse_id") and order.get("warehouse_id") and driver.get("warehouse_id"):
            skipped.append({"id": order_id, "reason": "Driver belongs to a different warehouse"})
        else:
            await db.orders.update_one({"id": order_id}, {"$set": {
                "assigned_driver_id": driver["id"], "assigned_driver_name": driver["name"],
                "updated_at": now_iso(),
            }})
            updated.append(order_id)
    return {"updated": updated, "skipped": skipped, "driver": {"id": driver["id"], "name": driver["name"]}}


@api.post("/orders/{oid}/receive")
async def receive_order_stock(oid: str, user: dict = Depends(require_store_permission("canManageInventory"))):
    order = await db.orders.find_one({
        "id": oid, "retailer_id": store_owner_id(user), "external_order": {"$ne": True},
    }, {"_id": 0})
    if not order:
        raise HTTPException(404, "Order not found.")
    assigned_branch_id = user.get("assigned_branch_id") if user.get("store_access_role") != "global_admin" else None
    if assigned_branch_id and order.get("branch_id") != assigned_branch_id:
        raise HTTPException(404, "Order not found.")
    if order.get("status") != "Delivered":
        raise HTTPException(409, "Stock can only be received after the supplier marks the order delivered.")
    received_at = now_iso()
    result = await db.orders.update_one(
        {"id": oid, "retailer_id": store_owner_id(user), "received_at": {"$exists": False}},
        {"$set": {
            "received_at": received_at,
            "received_by": user["id"],
            "updated_at": received_at,
        }},
    )
    if result.modified_count == 0:
        raise HTTPException(409, "Stock for this order has already been received.")
    return {"order_id": oid, "received_at": received_at}


@api.post("/returns", status_code=201)
async def create_return_request(body: ReturnRequestIn, user: dict = Depends(require_role("retailer"))):
    order = await db.orders.find_one({
        "id": body.order_id, "retailer_id": store_owner_id(user), "external_order": {"$ne": True},
    }, {"_id": 0})
    if not order:
        raise HTTPException(404, "Order not found.")
    assigned_branch_id = user.get("assigned_branch_id") if user.get("store_access_role") != "global_admin" else None
    if assigned_branch_id and order.get("branch_id") != assigned_branch_id:
        raise HTTPException(404, "Order not found.")
    if order.get("status") != "Delivered":
        raise HTTPException(409, "Products can only be returned from delivered orders.")
    matching_items = [item for item in order.get("items", []) if item.get("product_id") == body.product_id]
    if len(matching_items) != 1:
        raise HTTPException(404, "Product line not found or duplicated on this order.")
    item = matching_items[0]
    previous_returns = await db.product_returns.find({
        "order_id": body.order_id, "product_id": body.product_id,
        "status": {"$in": ["PENDING", "APPROVING", "APPROVED"]},
    }, {"_id": 0, "quantity": 1}).to_list(1000)
    already_requested = sum(int(return_request.get("quantity", 0)) for return_request in previous_returns)
    returned_quantity = int(item.get("returned_quantity", 0) or 0)
    remaining = int(item.get("quantity", 0) or 0) - max(already_requested, returned_quantity)
    if body.quantity > remaining:
        raise HTTPException(409, {"message": "Return quantity exceeds the remaining order quantity.", "remaining": max(0, remaining)})

    request_id = str(uuid.uuid4())
    created_at = now_iso()
    record = {
        "id": request_id, "order_id": order["id"], "order_no": order.get("order_no", ""),
        "product_id": body.product_id, "product_name": item.get("name", ""),
        "quantity": body.quantity, "reason": body.reason, "comment": body.comment.strip(),
        "status": "PENDING", "retailer_id": order["retailer_id"],
        "retailer_name": order.get("retailer_name", ""),
        "supplier_id": order["supplier_id"], "supplier_name": order.get("supplier_name", ""),
        "warehouse_id": order.get("warehouse_id"), "branch_id": order.get("branch_id"),
        "created_by": user["id"], "created_at": created_at, "updated_at": created_at,
    }
    await db.product_returns.insert_one(record)
    await log_financial_event(
        "product_return_requested", user, "product_return", request_id,
        after={"order_id": order["id"], "product_id": body.product_id,
               "quantity": body.quantity, "reason": body.reason}, status="pending",
    )
    await notify(
        order["supplier_id"],
        f"მაღაზიამ {record['order_no']}-ზე დაბრუნების მოთხოვნა გამოგზავნა ({record['product_name']}, {body.quantity}).",
        "product_return",
    )
    return await db.product_returns.find_one({"id": request_id}, {"_id": 0})


@api.get("/returns/mine")
async def list_my_return_requests(
    status: Optional[str] = Query(None, pattern="^(PENDING|APPROVING|APPROVED|REJECTED)$"),
    user: dict = Depends(require_role("retailer")),
):
    query = {"retailer_id": store_owner_id(user)}
    assigned_branch_id = user.get("assigned_branch_id") if user.get("store_access_role") != "global_admin" else None
    if assigned_branch_id:
        query["branch_id"] = assigned_branch_id
    if status:
        query["status"] = status
    return await db.product_returns.find(query, {"_id": 0}).sort("created_at", -1).to_list(1000)


@api.get("/supplier/returns")
async def list_supplier_returns(
    status: Optional[str] = Query(None, pattern="^(PENDING|APPROVING|APPROVED|REJECTED)$"),
    warehouse_id: Optional[str] = None,
    user: dict = Depends(require_role("supplier")),
):
    require_supplier_permission(user, "orders")
    query = {"supplier_id": supplier_owner_id(user)}
    selected_warehouse_id = await supplier_warehouse_id(user, warehouse_id)
    if selected_warehouse_id:
        query["warehouse_id"] = selected_warehouse_id
    if status:
        query["status"] = status
    return await db.product_returns.find(query, {"_id": 0}).sort("created_at", -1).to_list(2000)


async def _apply_supplier_return_restock(return_request: dict) -> None:
    await InventorySyncAdapter(db).restock_distributor(return_request)


async def _apply_return_inventory(return_request: dict) -> None:
    return_id = return_request["id"]
    quantity = int(return_request["quantity"])
    order_id = return_request["order_id"]
    product_id = return_request["product_id"]

    await _apply_supplier_return_restock(return_request)

    order = await db.orders.find_one({"id": order_id}, {"_id": 0, "items": 1})
    item = next((line for line in (order or {}).get("items", []) if line.get("product_id") == product_id), None)
    if not item:
        raise HTTPException(409, "Store inventory could not be adjusted for this return.")
    if return_id not in item.get("return_ids", []):
        updated_items = [dict(line) for line in order["items"]]
        updated_item = next(line for line in updated_items if line.get("product_id") == product_id)
        updated_item["returned_quantity"] = int(updated_item.get("returned_quantity", 0) or 0) + quantity
        updated_item["return_ids"] = list(updated_item.get("return_ids", [])) + [return_id]
        order_result = await db.orders.update_one(
            {"id": order_id, "items": order["items"]},
            {"$set": {"items": updated_items, "updated_at": now_iso()}},
        )
        if not order_result.modified_count:
            order = await db.orders.find_one({"id": order_id}, {"_id": 0, "items": 1})
            item = next((line for line in (order or {}).get("items", []) if line.get("product_id") == product_id), None)
            if not item or return_id not in item.get("return_ids", []):
                raise HTTPException(409, "Store inventory could not be adjusted for this return.")

    adapter = InventorySyncAdapter(db)
    store_tracked = await adapter.reduce_store_on_hand(return_request)
    await adapter.record_movements(return_request, store_tracked)


@api.patch("/supplier/returns/{return_id}/decision")
async def decide_return_request(
    return_id: str,
    body: ReturnDecisionIn,
    user: dict = Depends(require_role("supplier")),
):
    require_supplier_permission(user, "orders")
    supplier_id = supplier_owner_id(user)
    warehouse_id = await supplier_warehouse_id(user)
    query = {"id": return_id, "supplier_id": supplier_id}
    if warehouse_id:
        query["warehouse_id"] = warehouse_id
    return_request = await db.product_returns.find_one(query, {"_id": 0})
    if not return_request:
        raise HTTPException(404, "Return request not found.")
    if body.decision == "REJECTED":
        if not body.comment.strip():
            raise HTTPException(422, "A rejection comment is required.")
        result = await db.product_returns.update_one(
            {**query, "status": "PENDING"},
            {"$set": {"status": "REJECTED", "decision_comment": body.comment.strip(),
                      "decided_by": user["id"], "decided_at": now_iso(), "updated_at": now_iso()}},
        )
        if result.modified_count != 1:
            raise HTTPException(409, "Return request is no longer pending.")
    else:
        if return_request.get("status") == "APPROVED":
            raise HTTPException(409, "Return request has already been approved.")
        if return_request.get("status") not in {"PENDING", "APPROVING"}:
            raise HTTPException(409, "Only pending return requests can be approved.")
        if return_request.get("status") == "PENDING":
            claim = await db.product_returns.update_one(
                {**query, "status": "PENDING"},
                {"$set": {"status": "APPROVING", "decision_comment": body.comment.strip(),
                          "decided_by": user["id"], "updated_at": now_iso()}},
            )
            if claim.modified_count != 1:
                raise HTTPException(409, "Return request changed. Refresh and retry.")
        try:
            await _apply_return_inventory(return_request)
        except HTTPException:
            raise
        except Exception as error:
            logger.exception("Return inventory application failed: %s", return_id)
            raise HTTPException(503, "Return inventory update failed; retry approval after the inventory service recovers.") from error
        result = await db.product_returns.update_one(
            {**query, "status": "APPROVING"},
            {"$set": {"status": "APPROVED", "decision_comment": body.comment.strip(),
                      "decided_by": user["id"], "decided_at": now_iso(), "updated_at": now_iso()}},
        )
        if result.modified_count != 1:
            raise HTTPException(409, "Return inventory was applied; request finalization needs retry.")

    updated = await db.product_returns.find_one(query, {"_id": 0})
    await log_financial_event(
        "product_return_" + body.decision.lower(), user, "product_return", return_id,
        before={"status": return_request.get("status")},
        after={"status": body.decision, "quantity": return_request["quantity"],
               "comment": body.comment.strip()},
        status="success" if body.decision == "APPROVED" else "pending",
    )
    await notify(
        return_request["retailer_id"],
        f"დაბრუნების მოთხოვნა {return_request.get('order_no', '')}: "
        f"{'დამტკიცდა' if body.decision == 'APPROVED' else 'უარყოფილია'}.",
        "product_return", order_id=return_request["order_id"],
    )
    return updated


# ---------- analytics ----------
@api.get("/analytics/supplier")
async def supplier_analytics(
    warehouse_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    granularity: str = Query("daily", pattern="^(daily|monthly)$"),
    user: dict = Depends(require_role("supplier")),
):
    require_supplier_permission(user, "orders")
    owner_id = supplier_owner_id(user)
    order_query = {"supplier_id": owner_id, "external_order": {"$ne": True}}
    external_query = {"supplier_id": owner_id, "external_order": True}
    selected_warehouse_id = await supplier_warehouse_id(user, warehouse_id)
    if selected_warehouse_id:
        order_query["warehouse_id"] = selected_warehouse_id
        external_query["warehouse_id"] = selected_warehouse_id
    now_local = datetime.now(moneylib.PLATFORM_TZ)
    today = now_local.date()
    selected_range = _analytics_date_range(start_date, end_date, max_days=366 if granularity == "daily" else 1825)
    if selected_range:
        series_start = selected_range[0] or (selected_range[1] - timedelta(days=6 if granularity == "daily" else 364))
        series_end = selected_range[1] or today
    elif granularity == "daily":
        series_start, series_end = today - timedelta(days=6), today
    else:
        series_end = today
        first_month = (today.year, today.month)
        for _ in range(11):
            year, month = first_month
            first_month = (year - 1, 12) if month == 1 else (year, month - 1)
        series_start = date(first_month[0], first_month[1], 1)
    if granularity == "daily" and (series_end - series_start).days + 1 > 366:
        raise HTTPException(422, "Daily analytics range cannot exceed 366 days.")
    if granularity == "monthly" and ((series_end.year - series_start.year) * 12 + series_end.month - series_start.month + 1) > 60:
        raise HTTPException(422, "Monthly analytics range cannot exceed 60 months.")
    query_range = (series_start, series_end)
    period_order_query = {**order_query, **_analytics_date_query("created_at", query_range)}
    period_external_query = {**external_query, **_analytics_date_query("created_at", query_range)}
    orders = await db.orders.find(
        period_order_query, {"_id": 0},
    ).to_list(50000)
    external_orders = await db.orders.find(period_external_query, {"_id": 0}).to_list(50000)
    if selected_range:
        summary_orders, summary_external_orders = orders, external_orders
        summary_order_query, summary_external_query = period_order_query, period_external_query
    else:
        summary_orders = await db.orders.find(order_query, {"_id": 0}).to_list(50000)
        summary_external_orders = await db.orders.find(external_query, {"_id": 0}).to_list(50000)
        summary_order_query, summary_external_query = order_query, external_query
    products = await db.products.find({"supplier_id": owner_id}, {"_id": 0}).to_list(500)
    inventory = getattr(db, "warehouse_inventory", None)
    if inventory is not None:
        stock_query = {"supplier_id": owner_id}
        if selected_warehouse_id:
            stock_query["warehouse_id"] = selected_warehouse_id
        product_stocks = await inventory.find(stock_query, {"_id": 0}).to_list(10000)
        stocks = {}
        for stock in product_stocks:
            stocks[stock["product_id"]] = stocks.get(stock["product_id"], 0) + int(stock.get("stock", 0))
        products = [product for product in products if product["id"] in stocks]
        for product in products:
            product["stock"] = stocks[product["id"]]
    today_key = series_end.isoformat() if granularity == "daily" else series_end.strftime("%Y-%m")
    bucket = moneylib.to_platform_day if granularity == "daily" else moneylib.to_platform_month

    def sales(order_list, period_key=None):
        return moneylib.total_sum(
            o.get("total") for o in order_list
            if o.get("status") != "Cancelled" and (period_key is None or bucket(o.get("created_at")) == period_key)
        )

    def commission(order_list):
        return moneylib.total_sum(moneylib.order_fee(o) for o in order_list if o.get("status") != "Cancelled")

    app_revenue, external_revenue = sales(summary_orders), sales(summary_external_orders)
    revenue = app_revenue + external_revenue
    daily = sales(orders, today_key) + sales(external_orders, today_key)
    total_inventory = sum(int(p.get("stock", 0) or 0) for p in products)
    active = len([o for o in summary_orders if o["status"] in ("Pending", "Processing", "In Transit")])
    low_stock = [p for p in products if p["stock"] < 50]
    # popular items
    counts = {}
    for o in summary_orders:
        for i in o["items"]:
            counts[i["name"]] = counts.get(i["name"], 0) + i["quantity"]
    popular = sorted([{"name": k, "qty": v} for k, v in counts.items()], key=lambda x: -x["qty"])[:5]
    # last 7 days series
    series = []
    if granularity == "daily":
        period_keys = [(series_start + timedelta(days=offset)).isoformat()
                       for offset in range((series_end - series_start).days + 1)]
    else:
        period_keys = []
        year, month = series_start.year, series_start.month
        while (year, month) <= (series_end.year, series_end.month):
            period_keys.append(f"{year:04d}-{month:02d}")
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    for period_key in period_keys:
        amt = sales(orders, period_key) + sales(external_orders, period_key)
        series.append({
            "day": period_key[5:] if granularity == "daily" else period_key,
            "period": period_key, "sales": moneylib.as_json(amt),
            "app_sales": moneylib.as_json(sales(orders, period_key)),
            "external_sales": moneylib.as_json(sales(external_orders, period_key)),
        })
    aggregate = getattr(db.orders, "aggregate", None)
    if aggregate:
        status_rows = await aggregate([
            {"$match": summary_order_query}, {"$group": {"_id": "$status", "count": {"$sum": 1}}},
        ]).to_list(None)
        status_counts = {row["_id"]: row["count"] for row in status_rows}
    else:
        status_counts = {}
        for order in summary_orders:
            status_counts[order.get("status", "unknown")] = status_counts.get(order.get("status", "unknown"), 0) + 1
    return {"revenue": moneylib.as_json(revenue), "daily": moneylib.as_json(daily), "active_orders": active,
            "total_orders": len(summary_orders), "product_count": len(products),
            "granularity": granularity, "date_range": {"start_date": series_start.isoformat(),
                                                         "end_date": series_end.isoformat()},
            "status_counts": status_counts,
            "total_inventory": total_inventory,
            "app_sales": {"revenue": moneylib.as_json(app_revenue), "daily": moneylib.as_json(sales(orders, today_key)),
                          "orders": len([o for o in summary_orders if o.get("status") != "Cancelled"]),
                          "commission": moneylib.as_json(commission(summary_orders))},
            "external_sales": {"revenue": moneylib.as_json(external_revenue),
                               "daily": moneylib.as_json(sales(external_orders, today_key)),
                               "orders": len([o for o in external_orders if o.get("status") != "Cancelled"]),
                               "commission": 0.0},
            "low_stock": low_stock, "popular": popular, "series": series}

@api.get("/analytics/admin")
async def admin_analytics(user: dict = Depends(require_role("admin"))):
    # Aggregate in MongoDB instead of pulling every order and user document into Python.
    # Same formula as /admin/analytics/overview: Decimal totals and moneylib.order_fee.
    async def order_stats():
        rows = await db.orders.find(
            {"external_order": {"$ne": True}},
            {"_id": 0, "status": 1, "total": 1, "commission_amount": 1, "service_fee": 1, "source": 1, "external_order": 1},
        ).to_list(None)
        stats = {"total": 0, "delivered": 0, "gmv": moneylib.ZERO, "fees": moneylib.ZERO}
        for order in rows:
            if order.get("source") == "external":
                continue
            stats["total"] += 1
            if order.get("status") == "Delivered":
                stats["delivered"] += 1
            if order.get("status") != "Cancelled":
                stats["gmv"] += moneylib.q(order.get("total"))
                stats["fees"] += moneylib.order_fee(order)
        return stats

    async def user_counts():
        rows = await db.users.aggregate([
            {"$match": {"role": {"$in": ["retailer", "supplier"]}}},
            {"$group": {
                "_id": "$role", "count": {"$sum": 1},
                "pending": {"$sum": {"$cond": [{"$eq": ["$status", "pending"]}, 1, 0]}},
            }},
        ]).to_list(10)
        return {r["_id"]: r for r in rows}

    stats, counts = await asyncio.gather(order_stats(), user_counts())
    total = stats["total"]
    fulfillment = (float((Decimal(stats["delivered"]) * 100 / total).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
                   if total else None)
    return {"gmv": moneylib.as_json(stats["gmv"]), "total_orders": total, "fulfillment_rate": fulfillment,
            "fee_revenue": moneylib.as_json(stats["fees"]),
            "retailers": counts.get("retailer", {}).get("count", 0),
            "suppliers": counts.get("supplier", {}).get("count", 0),
            "pending_suppliers": counts.get("supplier", {}).get("pending", 0)}

@api.get("/health/db")
async def health_db():
    try:
        await asyncio.wait_for(client.admin.command("ping"), timeout=5)
    except Exception:
        raise HTTPException(503, "Database unavailable")
    return {"database": "ok"}


@api.get("/admin/analytics/overview")
async def admin_analytics_overview(
    months: int = Query(12, ge=1, le=60),
    year: Optional[int] = Query(None, ge=2000, le=2100),
    granularity: str = Query("monthly", pattern="^(daily|monthly)$"),
    days: int = Query(30, ge=7, le=90),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user: dict = Depends(require_role("admin")),
):
    """GMV / platform fees, registrations and order status counts by day or month."""
    now = datetime.now(timezone.utc)
    now_local = now.astimezone(moneylib.PLATFORM_TZ)
    selected_range = _analytics_date_range(start_date, end_date, max_days=366 if granularity == "daily" else 1826)
    if selected_range:
        first_date, last_date = selected_range
        if granularity == "daily":
            last_day = last_date or now_local.date()
            first_day = first_date or (last_day - timedelta(days=days - 1))
            if first_day > last_day:
                raise HTTPException(400, "start_date must be on or before end_date.")
            if (last_day - first_day).days + 1 > 366:
                raise HTTPException(422, "Daily analytics range cannot exceed 366 days.")
            days_list = [first_day + timedelta(days=offset)
                         for offset in range((last_day - first_day).days + 1)]
        else:
            end_day = last_date or now_local.date()
            if first_date:
                first_month = date(first_date.year, first_date.month, 1)
            else:
                first_month = date(end_day.year, end_day.month, 1)
                for _ in range(months - 1):
                    year_value, month_value = first_month.year, first_month.month
                    first_month = date(year_value - 1, 12, 1) if month_value == 1 else date(year_value, month_value - 1, 1)
            last_month = date(end_day.year, end_day.month, 1)
            pairs = []
            cursor = first_month
            while cursor <= last_month:
                pairs.append((cursor.year, cursor.month))
                cursor = date(cursor.year + 1, 1, 1) if cursor.month == 12 else date(cursor.year, cursor.month + 1, 1)
            if len(pairs) > 60:
                raise HTTPException(422, "Monthly analytics range cannot exceed 60 months.")
    elif granularity == "daily":
        last_day = now_local.date()
        days_list = [last_day - timedelta(days=offset) for offset in range(days - 1, -1, -1)]
    else:
        if year:
            pairs = [(year, m) for m in range(1, 13)]
        else:
            pairs, y, m = [], now_local.year, now_local.month
            for _ in range(months):
                pairs.append((y, m))
                m -= 1
                if m == 0:
                    y, m = y - 1, 12
            pairs.reverse()

    if granularity == "daily":
        keys = [d.isoformat() for d in days_list]
        bucket = moneylib.to_platform_day
        start = moneylib.platform_day_start_utc(days_list[0]).isoformat()
        end = moneylib.platform_day_start_utc(days_list[-1] + timedelta(days=1)).isoformat()
    else:
        keys = [f"{y}-{m:02d}" for y, m in pairs]
        bucket = moneylib.to_platform_month
        start = _month_bounds(*pairs[0])[0].isoformat()
        end = _month_bounds(*pairs[-1])[1].isoformat()
    live = ("Pending", "Processing", "In Transit")
    since = (now - timedelta(days=30)).isoformat()
    order_fields = {"_id": 0, "status": 1, "total": 1, "commission_amount": 1, "service_fee": 1,
                    "created_at": 1, "source": 1, "external_order": 1}

    async def orders_by_period():
        rows = await db.orders.find(
            {"external_order": {"$ne": True}, "created_at": {"$gte": start, "$lt": end}}, order_fields,
        ).to_list(None)
        acc, skipped = {}, 0
        for order in rows:
            if order.get("source") == "external":
                continue
            key = bucket(order.get("created_at"))
            if key is None:
                skipped += 1
                continue
            a = acc.setdefault(key, {"gmv": moneylib.ZERO, "fees": moneylib.ZERO, "delivered": 0, "cancelled": 0,
                                     "in_progress": 0, "non_cancelled": 0})
            status = order.get("status")
            if status == "Cancelled":
                a["cancelled"] += 1
                continue
            a["gmv"] += moneylib.q(order.get("total"))
            a["fees"] += moneylib.order_fee(order)
            a["non_cancelled"] += 1
            if status == "Delivered":
                a["delivered"] += 1
            elif status in live:
                a["in_progress"] += 1
        return acc, skipped

    async def users_by_period():
        rows = await db.users.find(
            {"role": {"$in": ["retailer", "supplier"]}, "created_at": {"$gte": start, "$lt": end}},
            {"_id": 0, "role": 1, "created_at": 1},
        ).to_list(None)
        counts = {}
        for row in rows:
            key = bucket(row.get("created_at"))
            if key:
                counts[(key, row["role"])] = counts.get((key, row["role"]), 0) + 1
        return counts

    async def totals():
        t = await db.users.aggregate([
            {"$match": {"role": {"$in": ["retailer", "supplier"]}}},
            {"$group": {"_id": "$role", "n": {"$sum": 1}}},
        ]).to_list(5)
        recent = await db.orders.aggregate([
            {"$match": {"external_order": {"$ne": True}, "status": {"$ne": "Cancelled"}, "created_at": {"$gte": since}}},
            {"$group": {"_id": None, "r": {"$addToSet": "$retailer_id"}, "s": {"$addToSet": "$supplier_id"}}},
        ]).to_list(1)
        open_invoices = await db.invoices.find(
            {"status": {"$ne": "paid"}}, {"_id": 0, "amount": 1},
        ).to_list(50000)
        invoice_debt = moneylib.total_sum(invoice.get("amount") for invoice in open_invoices)
        return ({r["_id"]: r["n"] for r in t},
                recent[0] if recent else {"r": [], "s": []}, invoice_debt, len(open_invoices))

    (o_map, skipped_orders), u_map, (tot, recent, invoice_debt, open_invoice_count) = await asyncio.gather(
        orders_by_period(), users_by_period(), totals(),
    )
    series = []
    for k in keys:
        o = o_map.get(k, {})
        series.append({
            "month": k,
            "gmv": moneylib.as_json(o.get("gmv", moneylib.ZERO)),
            "revenue": moneylib.as_json(o.get("fees", moneylib.ZERO)),
            "new_distributors": u_map.get((k, "supplier"), 0), "new_stores": u_map.get((k, "retailer"), 0),
            "delivered": o.get("delivered", 0), "cancelled": o.get("cancelled", 0),
            "in_progress": o.get("in_progress", 0),
        })
    # Totals sum the exact per-period Decimals, never the rounded floats above.
    total_fees = sum((o_map[k]["fees"] for k in keys if k in o_map), moneylib.ZERO)
    total_gmv = sum((o_map[k]["gmv"] for k in keys if k in o_map), moneylib.ZERO)
    non_cancelled = sum(o_map[k]["non_cancelled"] for k in keys if k in o_map)
    users_total = sum(tot.values())
    active = len({x for x in recent["r"] + recent["s"] if x})
    active = min(active, users_total)

    def pct(part):
        if not users_total:
            return None
        return float((Decimal(part) * 100 / users_total).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))

    # Monthly view: average per month. Daily view: 30-day run rate.
    mrr_base = total_fees if granularity == "monthly" else total_fees * 30
    return {
        "timezone": "Asia/Tbilisi", "granularity": granularity,
        "series": series,
        "data_quality": {"skipped_orders": skipped_orders},
        "summary": {
            "mrr": moneylib.as_json(moneylib.divide(mrr_base, len(keys))),
            "aov": moneylib.as_json(moneylib.divide(total_gmv, non_cancelled)),
            "total_gmv": moneylib.as_json(total_gmv), "total_revenue": moneylib.as_json(total_fees),
            "system_debt": moneylib.as_json(invoice_debt), "open_invoices": open_invoice_count,
            "users_total": users_total, "users_active": active, "users_inactive": users_total - active,
            "active_pct": pct(active), "inactive_pct": pct(users_total - active),
        },
    }


# ---------- admin user mgmt ----------
@api.get("/admin/users")
async def admin_users(role: Optional[str] = None, user: dict = Depends(require_role("admin"))):
    q = {} if not role or role == "all" else {"role": role}
    users = await db.users.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return [public_user_document(user_doc) for user_doc in users]

@api.delete("/admin/users/{uid}")
async def delete_admin_user(uid: str, user: dict = Depends(require_role("admin"))):
    if uid == user["id"]:
        raise HTTPException(400, "საკუთარი ანგარიშის წაშლა შეუძლებელია.")
    target = await db.users.find_one({"id": uid}, {"_id": 0, "id": 1, "role": 1})
    if not target:
        raise HTTPException(404, "მომხმარებელი ვერ მოიძებნა.")
    if target.get("role") == "admin" and await db.users.count_documents({"role": "admin"}) <= 1:
        raise HTTPException(400, "ბოლო ადმინისტრატორის წაშლა შეუძლებელია.")
    result = await db.users.delete_one({"id": uid})
    if result.deleted_count == 0:
        raise HTTPException(404, "მომხმარებელი ვერ მოიძებნა.")
    return {"ok": True}

@api.put("/admin/users/{uid}/commission")
async def set_user_commission(uid: str, body: CommissionIn, user: dict = Depends(require_role("admin"))):
    target = await db.users.find_one({"id": uid}, {"_id": 0, "role": 1})
    if not target or target.get("role") not in ("retailer", "supplier"):
        raise HTTPException(404, "მომხმარებელი ვერ მოიძებნა.")
    if body.commissionPayer and body.commissionPayer not in ("supplier", "retailer", "split"):
        raise HTTPException(400, "საკომისიოს გადამხდელი არასწორია.")
    if not body.enabled:
        fields = {"customCommissionType": None, "customCommissionValue": None, "commissionPayer": None}
    else:
        if body.customCommissionType not in ("percent", "fixed") or body.customCommissionValue is None:
            raise HTTPException(400, "მიუთითეთ საკომისიოს ტიპი და ოდენობა.")
        if body.customCommissionType == "percent" and body.customCommissionValue > 100:
            raise HTTPException(400, "პროცენტი არ უნდა აღემატებოდეს 100-ს.")
        fields = {
            "customCommissionType": body.customCommissionType,
            "customCommissionValue": moneylib.as_json(moneylib.q(body.customCommissionValue)),
            "commissionPayer": body.commissionPayer or None,
        }
    await db.users.update_one({"id": uid}, {"$set": fields})
    return {"ok": True, **fields}


@api.put("/admin/users/{uid}/status")
async def set_user_status(uid: str, body: StatusUpdate, user: dict = Depends(require_role("admin"))):
    if body.status not in ("active", "pending", "suspended"):
        raise HTTPException(400, "Invalid status")
    res = await db.users.update_one({"id": uid}, {"$set": {"status": body.status}})
    if res.matched_count == 0:
        raise HTTPException(404, "User not found")
    status_ka = {"active": "აქტიურია", "pending": "მოლოდინშია", "suspended": "შეჩერებულია"}[body.status]
    await notify(uid, f"თქვენი ანგარიშის სტატუსი შეიცვალა: {status_ka}.", "account")
    return {"ok": True}


# ---------- messaging ----------
async def _save_registered_contact(owner_id: str, contact: dict) -> None:
    contact_id = contact.get("id")
    if not owner_id or not contact_id or owner_id == contact_id:
        return
    timestamp = now_iso()
    await db.saved_contacts.update_one(
        {"owner_id": owner_id, "id": contact_id},
        {"$set": {
            "contact_id": contact_id,
            "name": contact.get("business_name") or contact.get("name") or contact.get("email") or "",
            "phone": contact.get("phone", ""),
            "role": contact.get("role", "other"),
            "kind": "registered",
            "updated_at": timestamp,
        }, "$setOnInsert": {"created_at": timestamp}},
        upsert=True,
    )


async def _ensure_admin_contacts(owner_id: str) -> None:
    admins = await db.users.find(
        {"role": "admin", "id": {"$ne": owner_id}, "status": {"$ne": "suspended"}},
        {"_id": 0, "id": 1, "name": 1, "business_name": 1, "email": 1, "phone": 1, "role": 1},
    ).to_list(100)
    for admin in admins:
        await _save_registered_contact(owner_id, admin)


async def backfill_existing_admin_contacts() -> None:
    admins = await db.users.find(
        {"role": "admin", "status": {"$ne": "suspended"}},
        {"_id": 0, "id": 1, "name": 1, "business_name": 1, "email": 1, "phone": 1, "role": 1},
    ).to_list(100)
    if not admins:
        return
    users = db.users.find({}, {"_id": 0, "id": 1})
    async for user in users:
        for admin in admins:
            await _save_registered_contact(user["id"], admin)


@api.get("/contacts")
async def contacts(user: dict = Depends(get_current_user)):
    # Include both transactional contacts and contacts explicitly saved by this user.
    if user["role"] == "retailer":
        orders = await db.orders.find({"retailer_id": user["id"]}, {"_id": 0, "supplier_id": 1}).to_list(500)
        ids = {o["supplier_id"] for o in orders}
    elif user["role"] == "supplier":
        orders = await db.orders.find({"supplier_id": user["id"]}, {"_id": 0, "retailer_id": 1}).to_list(500)
        ids = {o["retailer_id"] for o in orders}
    else:
        ids = None
    if ids is None:
        registered = await db.users.find(
            {"id": {"$ne": user["id"]}, "status": {"$ne": "suspended"}},
            {"_id": 0, "password_hash": 0},
        ).to_list(100)
    else:
        ids.discard("")
        registered = await db.users.find(
            {"id": {"$in": list(ids), "$ne": user["id"]}},
            {"_id": 0, "password_hash": 0},
        ).to_list(200) if ids else []
    saved = await db.saved_contacts.find({"owner_id": user["id"]}, {"_id": 0}).sort("name", 1).to_list(500)
    contacts_by_id = {contact["id"]: contact for contact in registered}
    for contact in saved:
        if contact.get("kind") == "registered":
            registered_contact = await db.users.find_one(
                {"id": contact.get("contact_id"), "status": {"$ne": "suspended"}},
                {"_id": 0, "password_hash": 0},
            )
            if registered_contact:
                contacts_by_id[registered_contact["id"]] = registered_contact
                continue
        contacts_by_id[contact["id"]] = {
            "id": contact["id"],
            "business_name": contact["name"],
            "name": contact["name"],
            "phone": contact.get("phone", ""),
            "role": contact.get("role", "other"),
            "contact_kind": contact.get("kind", "manual"),
            "is_external_contact": contact.get("kind") != "registered",
        }
    return list(contacts_by_id.values())


@api.get("/contacts/search")
async def search_contacts(query: str = "", user: dict = Depends(get_current_user)):
    query = " ".join(query.split())
    if not query:
        return []
    pattern = re.escape(query)
    users = await db.users.find({
        "id": {"$ne": user["id"]},
        "role": {"$in": ["retailer", "supplier"]},
        "status": {"$ne": "suspended"},
        "$or": [
            {"business_name": {"$regex": pattern, "$options": "i"}},
            {"name": {"$regex": pattern, "$options": "i"}},
            {"phone": {"$regex": pattern, "$options": "i"}},
        ],
    }, {"_id": 0, "id": 1, "name": 1, "business_name": 1, "phone": 1, "role": 1}).to_list(50)
    results = [{
        "id": contact["id"],
        "name": contact.get("business_name") or contact.get("name") or "",
        "phone": contact.get("phone", ""),
        "role": contact.get("role", "other"),
        "kind": "registered",
        "is_registered": True,
    } for contact in users]
    if user.get("role") == "supplier":
        drivers = await db.drivers.find({
            "supplier_id": user["id"],
            "$or": [
                {"name": {"$regex": pattern, "$options": "i"}},
                {"phone": {"$regex": pattern, "$options": "i"}},
            ],
        }, {"_id": 0, "id": 1, "name": 1, "phone": 1}).to_list(50)
        results.extend({
            "id": driver["id"],
            "name": driver.get("name", ""),
            "phone": driver.get("phone", ""),
            "role": "driver",
            "kind": "driver",
            "is_registered": False,
        } for driver in drivers)
    return results


@api.post("/contacts")
async def add_contact(body: ContactIn, user: dict = Depends(get_current_user)):
    allowed_roles = {"retailer", "supplier", "driver", "store", "other"}
    if body.role not in allowed_roles:
        raise HTTPException(422, "Choose a valid contact role.")

    contact_id = body.contact_id
    kind = body.kind
    name = body.name
    phone = body.phone
    role = body.role
    if contact_id:
        registered = await db.users.find_one({
            "id": contact_id,
            "role": {"$in": ["retailer", "supplier"]},
            "status": {"$ne": "suspended"},
        }, {"_id": 0, "id": 1, "name": 1, "business_name": 1, "phone": 1, "role": 1})
        if registered and registered["id"] == user["id"]:
            registered = None
        if registered:
            kind = "registered"
            name = registered.get("business_name") or registered.get("name") or name
            phone = registered.get("phone") or phone
            role = registered.get("role", role)
        else:
            driver = await db.drivers.find_one({
                "id": contact_id,
                "supplier_id": user["id"],
            }, {"_id": 0, "id": 1, "name": 1, "phone": 1})
            if not driver:
                raise HTTPException(404, "Contact not found.")
            kind = "driver"
            name = driver.get("name") or name
            phone = driver.get("phone") or phone
            role = "driver"
    else:
        kind = "manual"
        contact_id = str(uuid.uuid4())

    saved_contact = {
        "id": contact_id,
        "contact_id": contact_id if kind != "manual" else "",
        "owner_id": user["id"],
        "name": name.strip(),
        "phone": phone.strip(),
        "role": role,
        "kind": kind,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    if not saved_contact["name"]:
        raise HTTPException(422, "Contact name is required.")
    await db.saved_contacts.update_one(
        {"owner_id": user["id"], "id": contact_id},
        {"$set": {key: value for key, value in saved_contact.items() if key != "created_at"},
         "$setOnInsert": {"created_at": saved_contact["created_at"]}},
        upsert=True,
    )
    return {
        "id": contact_id,
        "business_name": saved_contact["name"],
        "name": saved_contact["name"],
        "phone": saved_contact["phone"],
        "role": saved_contact["role"],
        "contact_kind": kind,
        "is_external_contact": kind != "registered",
    }

@api.get("/messages/{other_id}")
async def get_messages(other_id: str, user: dict = Depends(get_current_user)):
    msgs = await db.messages.find({
        "$or": [{"from_id": user["id"], "to_id": other_id}, {"from_id": other_id, "to_id": user["id"]}]
    }, {"_id": 0}).sort("created_at", 1).to_list(500)
    await db.messages.update_many({"from_id": other_id, "to_id": user["id"], "read": False}, {"$set": {"read": True}})
    return msgs

@api.post("/messages")
async def send_message(body: MessageIn, user: dict = Depends(get_current_user)):
    recipient = await db.users.find_one(
        {"id": body.to_id, "status": {"$ne": "suspended"}},
        {"_id": 0, "id": 1, "name": 1, "business_name": 1, "email": 1, "phone": 1, "role": 1},
    )
    if not recipient:
        raise HTTPException(404, "Recipient not found.")
    if recipient["id"] == user["id"]:
        raise HTTPException(400, "You cannot message yourself.")
    msg = {"id": str(uuid.uuid4()), "from_id": user["id"], "from_name": user["business_name"],
           "to_id": body.to_id, "text": body.text, "order_id": body.order_id or "",
           "read": False, "created_at": now_iso()}
    await db.messages.insert_one(dict(msg))
    await _save_registered_contact(user["id"], recipient)
    await _save_registered_contact(body.to_id, user)
    await notify(
        body.to_id, f"ახალი შეტყობინება მომხმარებლისგან „{user['business_name']}“.",
        "message", order_id=body.order_id or None,
    )
    return clean(msg)


# ---------- support: "Distro" assistant + central admin tickets ----------
_SUPPORT_USER_TYPE = {"retailer": "store", "supplier": "distributor", "admin": "admin"}
_SUPPORT_TYPE_KA = {"store": "მაღაზია", "distributor": "დისტრიბუტორი", "admin": "ადმინისტრატორი"}

_SUPPORT_BLOCKED = re.compile(
    r"(source\s*code|კოდი\s*მაჩვენ|კოდი\s*მომეცი|პროგრამული\s*კოდ|api[\s_-]*key|secret|jwt|token|ტოკენ|გასაღებ|"
    r"პაროლი\s*(მომეცი|მითხარი)|env\b|\.env|database\s*(url|uri)|mongo|connection\s*string|smtp_password|"
    r"ignore\s+(all\s+)?(previous|prior)|system\s*prompt)", re.I)

_SUPPORT_KB = {
    "retailer": [
        (r"ძებნ|პროდუქ|კატალოგ|search|catalog", "პროდუქტის საპოვნელად გახსენით „კატალოგი“, გამოიყენეთ საძიებო ველი და ქალაქის/კატეგორიის ფილტრები. პროდუქტის დასამატებლად დააჭირეთ კალათის ღილაკს."),
        (r"შეკვეთ|გაფორმ|checkout|order", "შეკვეთის გასაფორმებლად დაამატეთ პროდუქცია კალათაში, გადადით „კალათაში“, მიუთითეთ მისამართი და გადახდის მეთოდი და დააჭირეთ „შეკვეთის გაფორმებას“. ისტორია ჩანს „ჩემი შეკვეთები“-ში."),
        (r"რე-?ორდ|ხელახლა|reorder|re-order", "„ჩემი შეკვეთები“-ში შეკვეთასთან დააჭირეთ „ხელახლა გამოწერა“. პროდუქცია კალათაში გადავა მიმდინარე ფასებითა და მარაგით, სადაც რაოდენობების შეცვლა, წაშლა და ახლის დამატება შეგიძლიათ."),
        (r"ბარათ|card|გადახდ", "ბარათის მისაბმელად გახსენით „პროფილი“ და დააჭირეთ „ახალი ბარათის დამატება“. შეგიძლიათ რამდენიმე ბარათის მიბმა; შეკვეთისას ისინი გადახდის მეთოდებში გამოჩნდება. სხვა მეთოდებია: ნაღდი, კონსიგნაცია, საბანკო გადარიცხვა."),
        (r"ბუღალტ|ინვოის|invoice|მეილ|ელ.?ფოსტ|smtp", "ინვოისის გასაგზავნად „ჩემი შეკვეთები“-ში გახსენით შეკვეთა და დააჭირეთ „ინვოისის გაგზავნას“ (PDF მიმაგრებული გაიგზავნება). მიმღების მისამართი მიუთითეთ პროფილში, ბუღალტრის ელფოსტის ველში; გაგზავნას პლატფორმა მართავს."),
    ],
    "supplier": [
        (r"კატალოგ|პროდუქ|მარაგ|ინვენტ|stock|inventory", "პროდუქციისა და მარაგის სამართავად გახსენით „ინვენტარი“: შეგიძლიათ პროდუქტის დამატება/რედაქტირება, მარაგის განახლება და CSV/Excel იმპორტი."),
        (r"ფას|price|ფასდაკლ", "ფასებს ცვლით „ინვენტარში“ პროდუქტის რედაქტირებისას (საფეხურებრივი ფასებიც). ინდივიდუალური ფასის მოთხოვნები ჩანს „ფასების მოლაპარაკებებში“."),
        (r"შეკვეთ|order", "შემოსული შეკვეთები ჩანს „შეკვეთებში“: დაადასტურეთ, გადაიყვანეთ სტატუსები (დამუშავება, გზაში, მიწოდებული) და გაუგზავნეთ მაღაზიას."),
        (r"ინვოის|invoice|ბუღალტ|მეილ|ელ.?ფოსტ|smtp", "შეკვეთის ინვოისს PDF-ად გადმოწერთ ან ელფოსტით გააგზავნით შეკვეთის გვერდიდან. ბუღალტრის ელფოსტა მიუთითეთ „პროფილში“; გაგზავნას პლატფორმა მართავს, საბანკო ანგარიშებიც (რამდენიმე IBAN) იქვეა."),
    ],
}

_SUPPORT_FALLBACK = ("მე ვარ „დისტრო“ — დაგეხმარებით პლატფორმის გამოყენებაში. დამისვით კითხვა ფუნქციონალზე "
                     "(მაგ. შეკვეთა, ბარათი, ინვოისი, ფასები, მარაგი) ან დააჭირეთ „ადმინისტრატორთან დაკავშირებას“.")

_FINANCIAL_QUESTION = re.compile(
    r"(რამდენი|ჯამი|ჯამურად|თანხა|ხარჯ|შევიძინ|ვიყიდ|შეკვეთ|გაყიდ|ბრუნვ|შემოსავალ|"
    r"monthly|spent|spend|buy|bought|purchase|purchased|sales|revenue|turnover)",
    re.I,
)


async def _support_orders_in_period(user: dict, start: datetime, end: datetime) -> list:
    role = user.get("role")
    if role not in {"retailer", "supplier"}:
        return []
    owner_id = store_owner_id(user) if role == "retailer" else supplier_owner_id(user)
    owner_field = "retailer_id" if role == "retailer" else "supplier_id"
    return await db.orders.find(
        {
            owner_field: owner_id,
            "external_order": {"$ne": True},
            "created_at": {"$gte": start.isoformat(), "$lt": end.isoformat()},
            "status": {"$ne": "Cancelled"},
        },
        {"_id": 0, "id": 1, "total": 1, "amount_paid": 1, "payment_status": 1, "paid_at_checkout": 1,
         "status": 1, "created_at": 1, "items": 1},
    ).to_list(10000)


async def _support_monthly_financial_answer(text: str, user: dict) -> Optional[str]:
    if not _FINANCIAL_QUESTION.search(text) or not re.search(
        r"(ამ\s*თვეში|მიმდინარე\s*თვეში|თვიურ|monthly|this\s+month)", text, re.I,
    ):
        return None

    role = user.get("role")
    if role not in {"retailer", "supplier"}:
        return None

    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if now.month == 12:
        next_month = month_start.replace(year=now.year + 1, month=1)
    else:
        next_month = month_start.replace(month=now.month + 1)
    orders = await _support_orders_in_period(user, month_start, next_month)

    total = moneylib.total_sum(order.get("total") for order in orders)
    paid = moneylib.total_sum(
        moneylib.q(order_payment_totals(order)[0]) - moneylib.q(order_payment_totals(order)[1]) for order in orders
    )
    unpaid = max(moneylib.ZERO, total - paid)
    quantity = sum(
        int(item.get("quantity", 0) or 0)
        for order in orders for item in order.get("items", [])
        if isinstance(item, dict)
    )
    role_label = "შესყიდვებზე" if role == "retailer" else "გაყიდვებზე"
    return (
        f"ამ თვეში ({month_start:%d.%m.%Y}–{(next_month - timedelta(days=1)):%d.%m.%Y}) "
        f"{role_label} დაფიქსირებულია {len(orders)} შეკვეთა ({quantity} ერთეული), ჯამური ღირებულებით "
        f"₾{total:,.2f}. აღრიცხული გადახდა: ₾{paid:,.2f}; დარჩენილი/გადაუხდელი: ₾{unpaid:,.2f}. "
        "მონაცემი დათვლილია თქვენს ანგარიშთან დაკავშირებული, გაუქმებული არა-app შეკვეთებიდან. "
        "გადახდებისა და ფილიალების დეტალური შეჯერებისთვის გახსენით „ფინანსები“ ან „ანალიტიკა“."
    )


def _support_norm(value: str) -> str:
    return re.sub(r"[\W_]+", "", str(value or "").lower())


async def _support_all_orders(user: dict) -> list:
    now = datetime.now(timezone.utc)
    return await _support_orders_in_period(user, now - timedelta(days=730), now + timedelta(microseconds=1))


def _support_product_totals(orders: list) -> dict:
    totals: dict = {}
    for order in orders:
        for item in order.get("items", []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            quantity = int(item.get("quantity", 0) or 0)
            row = totals.setdefault(name, {"quantity": 0, "amount": moneylib.ZERO})
            row["quantity"] += quantity
            row["amount"] += moneylib.q(moneylib.dec(item.get("unit_price", 0) or 0) * quantity)
    return totals


async def _support_product_answer(text: str, user: dict) -> Optional[str]:
    role = user.get("role")
    if role not in {"retailer", "supplier"}:
        return None
    verb = "შევიძინე" if role == "retailer" else "გავყიდე"
    top_q = re.search(r"(ყველაზე\s*მეტ|most|top|ტოპ)", text, re.I) and re.search(
        r"(პროდუქც|პროდუქტ|ავიღ|შევიძინ|შევუკვეთ|ვიყიდ|გავყიდ|გაიყიდ|product|bought|sold|ordered)", text, re.I)
    tokens = [t for t in (_support_norm(w) for w in re.split(r"\s+", text)) if len(t) >= 4]
    if not top_q and not tokens:
        return None
    totals = _support_product_totals(await _support_all_orders(user))

    terms = {}
    if tokens and not top_q:
        names = {name: _support_norm(name) for name in totals}
        for token in tokens:
            stem = token[:-2] if len(token) >= 7 else token[:-1] if len(token) >= 5 else token
            matched = [n for n, norm in names.items() if stem in norm]
            if matched and stem not in terms:
                terms[stem] = matched
    if terms:
        rows = []
        for stem, matched in terms.items():
            qty = sum(totals[n]["quantity"] for n in matched)
            amount = sum(totals[n]["amount"] for n in matched)
            rows.append((matched[0] if len(matched) == 1 else stem, qty, amount))
        rows.sort(key=lambda r: (-r[1], r[0]))
        detail = "; ".join(f"{n}: {q} ერთეული, ₾{a:,.2f}" for n, q, a in rows)
        if len(rows) > 1 and rows[0][1] != rows[1][1]:
            verdict = f"მეტი {rows[0][1] - rows[1][1]} ერთეულით {rows[0][0]} გაქვთ."
        elif len(rows) > 1:
            verdict = "რაოდენობები ტოლია."
        else:
            verdict = ""
        return f"ბოლო 2 წლის შეკვეთებით: {detail}. {verdict}".strip()
    if top_q:
        if not totals:
            return "შეკვეთების ისტორიაში პროდუქციის მონაცემი ჯერ არ მოიძებნა."
        ranked = sorted(totals.items(), key=lambda p: (-p[1]["quantity"], p[0]))[:5]
        lines = "; ".join(f"{i}. {n} — {v['quantity']} ერთეული (₾{v['amount']:,.2f})"
                          for i, (n, v) in enumerate(ranked, 1))
        return f"ყველაზე მეტი რაოდენობით {verb}: {lines}."
    return None


async def _support_role_overview(text: str, user: dict) -> Optional[str]:
    role = user.get("role")
    if role == "supplier" and re.search(r"(მარაგ|ნაშთ|stock|inventor)", text, re.I):
        owner_id = supplier_owner_id(user)
        products = await db.products.find(
            {"supplier_id": owner_id}, {"_id": 0, "name": 1, "stock": 1},
        ).to_list(5000)
        if not products:
            return "თქვენს კატალოგში პროდუქცია ჯერ არ არის დამატებული."
        out = [p for p in products if int(p.get("stock", 0) or 0) <= 0]
        low = sorted((p for p in products if 0 < int(p.get("stock", 0) or 0) <= 10),
                     key=lambda p: int(p.get("stock", 0) or 0))
        parts = [f"კატალოგში {len(products)} პროდუქტია; მარაგი ამოწურულია {len(out)}-ზე"]
        if out:
            parts.append("ამოწურული: " + ", ".join(p.get("name", "") for p in out[:5]))
        if low:
            parts.append("მცირე მარაგი: " + ", ".join(f"{p.get('name', '')} ({p.get('stock')})" for p in low[:5]))
        return "; ".join(parts) + "."
    if role == "supplier" and re.search(r"(ინვოის|invoice)", text, re.I):
        invoices_collection = getattr(db, "invoices", None)
        if invoices_collection is None:
            return None
        invoices = await invoices_collection.find(
            {"supplier_id": supplier_owner_id(user)}, {"_id": 0, "amount": 1, "status": 1},
        ).to_list(2000)
        open_items = [i for i in invoices if str(i.get("status", "")).lower() != "paid"]
        total_open = moneylib.total_sum(i.get("amount", 0) or 0 for i in open_items)
        return f"გაქვთ {len(invoices)} ინვოისი, აქედან გადაუხდელი {len(open_items)} ჯამურად ₾{total_open:,.2f}."
    if re.search(r"(ბოლო\s*შეკვეთ|შეკვეთების\s*ისტორ|order\s*history|recent\s*orders)", text, re.I) \
            and role in {"retailer", "supplier"}:
        orders = sorted(await _support_all_orders(user), key=lambda o: o.get("created_at", ""), reverse=True)[:5]
        if not orders:
            return "შეკვეთების ისტორია ჯერ ცარიელია."
        lines = "; ".join(
            f"{str(o.get('created_at', ''))[:10]} — ₾{moneylib.q(o.get('total', 0) or 0):,.2f} ({o.get('status', '')})"
            for o in orders)
        return f"ბოლო შეკვეთები: {lines}."
    return None


_ACCOUNTING_QUESTION = re.compile(
    r"(მარჟ|თვითღირებულ|მოგებ|margin|profit|დავალიან|გადასახდელ|მისაღებ|ვალი|payable|receivable|debt|"
    r"ამონაგ|ბრუნვ|საბრუნავ|cash\s*flow|ხარჯ.*(ოპტიმ|შემცირ)|expenses)",
    re.I,
)


def _support_can_view_financials(user: dict) -> bool:
    if user.get("role") != "retailer":
        return True
    return bool(effective_store_permissions(user).get("canViewFinancials"))


async def _support_accounting_answer(text: str, user: dict) -> Optional[str]:
    role = user.get("role")
    if role not in {"retailer", "supplier"} or not _ACCOUNTING_QUESTION.search(text):
        return None
    now = datetime.now(timezone.utc)
    if re.search(r"(წელ|year)", text, re.I):
        start, label = now - timedelta(days=365), "ბოლო 365 დღე"
    else:
        start, label = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0), "მიმდინარე თვე"
    orders = await _support_orders_in_period(user, start, now + timedelta(microseconds=1))
    period_total = moneylib.total_sum(o.get("total") for o in orders)
    all_orders = await _support_all_orders(user)
    counterpart_field = "supplier_id" if role == "retailer" else "retailer_id"
    open_by_party: dict = {}
    for order in all_orders:
        balance = moneylib.q(order_payment_totals(order)[1])
        if balance > 0:
            party = str(order.get(counterpart_field) or "")
            open_by_party[party] = open_by_party.get(party, moneylib.ZERO) + balance
    open_total = moneylib.total_sum(open_by_party.values())
    names = {}
    if open_by_party:
        found = await db.users.find(
            {"id": {"$in": list(open_by_party)}}, {"_id": 0, "id": 1, "business_name": 1, "name": 1},
        ).to_list(len(open_by_party))
        names = {u["id"]: u.get("business_name") or u.get("name") or "" for u in found}
    top = sorted(open_by_party.items(), key=lambda p: -p[1])[:5]
    party_text = "; ".join(f"{names.get(pid) or 'უცნობი კონტრაგენტი'}: ₾{amount:,.2f}" for pid, amount in top)

    if role == "retailer":
        lines = [f"{label}: შესყიდვები ₾{period_total:,.2f} ({len(orders)} შეკვეთა)."]
        pos_sales = getattr(db, "pos_sales", None)
        if pos_sales is not None:
            sales = await pos_sales.find({"retailer_id": store_owner_id(user)}, {"_id": 0}).to_list(50000)
            sales = [s for s in sales if str(s.get("sold_at", ""))[:10] >= start.date().isoformat()]
            revenue = cost = moneylib.ZERO
            for sale in sales:
                for line in sale.get("items", []):
                    qty = moneylib.dec(line.get("quantity", 0) or 0)
                    revenue += moneylib.q(qty * moneylib.dec(line.get("retail_price", 0) or 0))
                    cost += moneylib.q(qty * moneylib.dec(line.get("unit_cost", 0) or 0))
            if revenue > 0:
                margin = (revenue - cost) / revenue * 100
                lines.append(f"გაყიდვების ამონაგები ₾{revenue:,.2f}, თვითღირებულება ₾{cost:,.2f}, "
                             f"საერთო მოგება ₾{revenue - cost:,.2f} (მარჟა {margin:.1f}%).")
            else:
                lines.append("მარჟის გასათვლელად POS გაყიდვები და თვითღირებულება ამ პერიოდში არ არის აღრიცხული.")
        lines.append(f"გადასახდელი დავალიანება (Accounts Payable): ₾{open_total:,.2f}"
                     + (f" — დისტრიბუტორების მიხედვით: {party_text}." if party_text else "."))
        lines.append("რჩევა: დაფარეთ უძველესი დავალიანებები პირველ რიგში, შეკვეთები გააერთიანეთ ტრანსპორტირების "
                     "ხარჯის შესამცირებლად და ნელმოძრავ პროდუქციაზე მარაგი არ დააგროვოთ.")
    else:
        lines = [f"{label}: გაყიდვები ₾{period_total:,.2f} ({len(orders)} შეკვეთა).",
                 f"მისაღები თანხა (Accounts Receivable): ₾{open_total:,.2f}"
                 + (f" — მაღაზიების მიხედვით: {party_text}." if party_text else "."),
                 "პროდუქტის თვითღირებულება დისტრიბუტორის ანგარიშზე არ აღირიცხება, ამიტომ მარჟას ზუსტად ვერ გამოვთვლი; "
                 "თუ შესყიდვის ფასს მეტყვით, გამოთვლაში დაგეხმარებით.",
                 "რჩევა: მაღალი ვადაგადაცილებული ვალის მქონე მაღაზიებზე შეზღუდეთ კრედიტი და ხშირად გაყიდვად "
                 "პროდუქტზე მარაგი ნულამდე არ დაუშვათ."]
    return " ".join(lines)


async def _support_category_answer(text: str, user: dict) -> Optional[str]:
    if user.get("role") not in {"retailer", "supplier"} or not re.search(
        r"(კატეგორ|ყველაზე\s*(მეტად|კარგად)\s*იყიდ|ტოპ.*(პროდუქ|გაყიდ)|top[- ]?sell|best[- ]?sell)",
        text, re.I,
    ):
        return None
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=90)
    orders = await _support_orders_in_period(user, start, now + timedelta(microseconds=1))
    product_ids = {
        str(item.get("product_id"))
        for order in orders for item in order.get("items", [])
        if isinstance(item, dict) and item.get("product_id")
    }
    products_collection = getattr(db, "products", None)
    if not product_ids or products_collection is None:
        return "ბოლო 90 დღისთვის საკმარისი გაყიდვების მონაცემი არ მოიძებნა. სცადეთ კითხვა მოგვიანებით ან გახსენით კატალოგი/ანალიტიკა."
    products = await products_collection.find(
        {"id": {"$in": list(product_ids)}}, {"_id": 0, "id": 1, "category": 1},
    ).to_list(len(product_ids))
    categories = {product["id"]: str(product.get("category") or "სხვა") for product in products}
    totals = {}
    for order in orders:
        for item in order.get("items", []):
            if not isinstance(item, dict):
                continue
            category = categories.get(str(item.get("product_id")), "სხვა")
            result = totals.setdefault(category, {"quantity": 0, "amount": moneylib.ZERO})
            quantity = int(item.get("quantity", 0) or 0)
            result["quantity"] += quantity
            result["amount"] += moneylib.q(moneylib.dec(item.get("unit_price", 0) or 0) * quantity)
    if not totals:
        return "ბოლო 90 დღისთვის კატეგორიების მონაცემი არ მოიძებნა."
    ranked = sorted(totals.items(), key=lambda pair: (-pair[1]["amount"], pair[0]))[:3]
    detail = "; ".join(
        f"{name}: {value['quantity']} ერთეული, ₾{value['amount']:,.2f}"
        for name, value in ranked
    )
    return (
        f"ბოლო 90 დღის შეკვეთებში ყველაზე მაღალი ჯამური ღირებულების კატეგორიებია: {detail}. "
        "ეს მაჩვენებელი შეკვეთების ღირებულებას ეფუძნება და არა საბოლოო მოგებას; მარაგისა და მარჟის სრულად შესაფასებლად "
        "შეადარეთ შეძენის ფასი, გაყიდვის ფასი და მიმდინარე ნაშთი."
    )


DISTRO_SYSTEM_PROMPT = """You are "Distro", an AI support assistant, accountant assistant and B2B business partner for the
Distro Logistics platform (retail stores and distributors in Georgia). Answer in natural, professional Georgian.

DATA: use only the authenticated user's own data (orders, items, invoices, balances, stock) and never invent figures.
Report amounts in GEL (₾). Answer product questions (e.g. "Coca-Cola or Fanta?", "what did I order most?") from order data.
ACCOUNTING: period expenses and revenue, margin and cost of goods, accounts payable (stores) / receivable (distributors),
cash-flow and cost-optimisation advice. Respect staff permissions for financial data.
SUPPORT: for lag/freezing give concrete steps (F5, clear cache, check connection, restart browser). Explain step by step:
adding employees (Employees page -> Add New), linking cards (Profile -> Cards -> + New card), invoice recipient email setup.
ADVISOR: stores - assortment planning, restocking popular items, purchase analysis; distributors - stock control,
pricing strategy, processing incoming orders.
SECURITY: never reveal or discuss source code, API keys, database structure, architecture or .env files, nor other users'
data. Never take actions or transactions on your own; only respond to the user's questions. If unsolved, direct the user to
"Contact Administrator"."""

# (pattern, answer variants, roles or None, suggest_admin). Order matters: first match wins.
_SUPPORT_TOPICS = [
    (r"მიჭედ|ჭედავს|იჭედება|ჭიანურ|ნელა|არ იტვირთ|გაიჭ|გაიყინ|არ იხსნ|არ მუშაობ|ერორ|შეცდომა|freez|lag|slow|not loading|crash|error",
     ["თუ პროგრამა იჭედება ან არ იტვირთება, სცადეთ თანმიმდევრულად:\n1) განაახლეთ გვერდი (F5 ან Ctrl+R; სრული განახლებისთვის Ctrl+F5).\n2) გაასუფთავეთ ბრაუზერის ქეში (Ctrl+Shift+Delete → „Cached images and files“).\n3) შეამოწმეთ ინტერნეტ-კავშირი.\n4) დახურეთ და თავიდან გახსენით ბრაუზერი ან აპლიკაცია; სცადეთ სხვა ბრაუზერიც.\nთუ პრობლემა მაინც რჩება, მომწერეთ რა გვერდზე ხდება და რა შეტყობინება ჩანს, ან გაუგზავნეთ ადმინისტრატორს."],
     None, True),
    (r"ბარათ.*(მიბმ|მიაბ|მივაბ|დამატ|დაყენ|როგორ|შევიყვან)|(მიბმ|მიაბ|მივაბ|დამატ).*ბარათ|card.*(add|link|attach)",
     ["ბარათის მისაბმელად:\n1) მარცხენა მენიუდან გახსენით „პროფილი“.\n2) ჩაყევით ბლოკამდე „ბარათი“ და დააჭირეთ „+ ახალი ბარათის დამატება“.\n3) შეიყვანეთ ბარათის ნომერი, ვადა (MM/YY), CVC და სახელი ბარათზე.\n4) დააჭირეთ „შენახვას“ — ბარათი გამოჩნდება სიაში ნიღბული ნომრით (••••1234).\nშეგიძლიათ რამდენიმე ბარათის მიბმა, თითოეულის წაშლა კი სიიდან. შეკვეთისას ისინი ავტომატურად ჩანს გადახდის მეთოდებში. ახალი ბარათი შეკვეთის დროს არ ემატება, მხოლოდ პროფილიდან."],
     None, False),
    (r"ბარათ.*(წაშ|მოშორ|ამოშ)|წაშ.*ბარათ",
     ["ბარათის წასაშლელად გახსენით „პროფილი“ → „ბარათი“ და დააჭირეთ ურნის ღილაკს იმ ბარათის გვერდით, რომლის წაშლაც გსურთ."],
     None, False),
    (r"ბუღალტ|smtp|app\s*password|აპლიკაციის პაროლ|გამგზავნ.*ელ|ინვოისი.*(არ იგზავნ|ვერ გავაგზავნ)",
         ["ინვოისის გასაგზავნად მიუთითეთ მიმღები/ბუღალტრის ელფოსტა „პროფილში“, შემდეგ „ჩემი შეკვეთები“-ში დააჭირეთ „ინვოისის გაგზავნას“ — PDF მიმაგრებული გაიგზავნება. გამგზავნ ელფოსტასა და მიწოდებას პლატფორმა მართავს.",
            "თუ ინვოისი არ იგზავნება, შეამოწმეთ მიმღების ელფოსტა პროფილში და Render-ის backend logs-ში Resend API-ის შეცდომა. სხვა მისამართზე გასაგზავნად გამოიყენეთ „სხვა ელ.ფოსტაზე“; ის დაიმახსოვრება."],
     None, False),
    (r"რე-?ორდ|ხელახლა გამოწ|reorder|re-order|გავიმეორო შეკვეთ",
     ["„ჩემი შეკვეთები“-ში დააჭირეთ შეკვეთასთან „ხელახლა გამოწერას“. პროდუქცია კალათაში გადავა მიმდინარე ფასებითა და მარაგით; მარაგგამოლეული პოზიციები გამოტოვებულია. კალათაში შეგიძლიათ რაოდენობების შეცვლა, ზედმეტის წაშლა და კატალოგიდან ახლის დამატება."],
     ["retailer"], False),
    (r"გადახდ|ნაღდი|კონსიგნაც|გადარიცხვ|payment",
     ["შეკვეთისას ხელმისაწვდომია: მიბმული ბარათი, ნაღდი/გადახდა ადგილზე, კონსიგნაცია და საბანკო გადარიცხვა/ინვოისი. ბარათის გამოსაყენებლად ჯერ მიაბით ის პროფილში."],
     ["retailer"], False),
    (r"ზრდ|გაზრდ|გაყიდვ|გაუმჯობეს|სამომავლო|გეგმ|ასორტიმენტ|მოგებ|ბიზნეს|რჩევა|რეკომენდაც|growth|sales|strategy|advice",
     ["მაღაზიისთვის პრაქტიკული B2B რჩევები:\n• ABC-ანალიზი: აღრიცხეთ 20% პროდუქტი, რომელიც 80% ბრუნვას იძლევა და ეს პოზიციები არასოდეს გაგიმთავრდეთ (დაადგინეთ მინიმალური მარაგი).\n• შეუკვეთეთ რეგულარულად ფიქსირებული გრაფიკით („ხელახლა გამოწერა“ ამას აჩქარებს) და ისარგებლეთ რაოდენობრივი ფასდაკლებით.\n• შეადარეთ რამდენიმე დისტრიბუტორის ფასი და მოითხოვეთ ინდივიდუალური ფასი მაღალ ბრუნვაზე.\n• ასორტიმენტი ფაზობრივად გააფართოვეთ: დაამატეთ 3–5 ახალი პოზიცია, 1 თვე გააკონტროლეთ გაყიდვები და დატოვეთ მხოლოდ მოძრავი.\n• ადევნეთ თვალი მარჟას და ძვირადმყოფ/ვადადამთავრებად პროდუქციას.",
      "ბიზნესის გასაზრდელად ჯერ დაადგინეთ, რა გაქვთ ბრუნვაში: რომელი პროდუქტი იყიდება სწრაფად, რომელი დგას თაროზე. სწრაფ პროდუქტზე გაზარდეთ შეკვეთის ზომა (უკეთესი ფასი), ნელზე შეამცირეთ. დისტრიბუტორთან შეათანხმეთ მიწოდების ფიქსირებული დღეები და გადახდის პირობები (კონსიგნაცია/ვადიანი გადახდა). რეგულარულად გადახედეთ ფინანსებისა და ანალიტიკის გვერდებს."],
     ["retailer"], False),
    (r"ზრდ|გაზრდ|გაყიდვ|გაუმჯობეს|სამომავლო|გეგმ|ასორტიმენტ|მოგებ|ბიზნეს|რჩევა|რეკომენდაც|growth|sales|strategy|advice",
     ["დისტრიბუტორისთვის პრაქტიკული B2B რჩევები:\n• მარაგების კონტროლი: პოპულარულ პროდუქტზე დააყენეთ მინიმალური ნაშთი და ივსებოდეს ახალი პარტიით მანამ, სანამ ამოიწურება.\n• საფეხურებრივი ფასები: დაამატეთ რაოდენობრივი ფასდაკლება — ეს ზრდის შეკვეთის საშუალო ოდენობას.\n• კომუნიკაცია: დროულად დაადასტურეთ შეკვეთები და შეატყობინეთ მაღაზიას მარაგის ცვლილებაზე; სტაბილური მიწოდება ლოიალობას ზრდის.\n• გააფართოვეთ მომსახურე ქალაქები და ახალი მაღაზიები მოიზიდეთ „ჩემი მაღაზიები“-თვის.\n• მარშრუტების ოპტიმიზაციით შეამცირეთ ტრანსპორტირების ხარჯი.",
      "გაყიდვების გასაუმჯობესებლად გააანალიზეთ რომელი მაღაზია და რომელი პროდუქტი იძლევა ყველაზე მეტ ბრუნვას, და ამ პოზიციებზე უზრუნველყავით მუდმივი მარაგი. შესთავაზეთ მაღაზიებს ტოპ-პროდუქტებზე შეთავაზებები, გამოაქვეყნეთ ახალი ასორტიმენტი კატალოგში და აკონტროლეთ დაგვიანებული გადახდები ინვოისებით."],
     ["supplier"], False),
    (r"ძებნ|პროდუქტ.*ვიპოვ|ვერ ვპოულობ|კატალოგ|search|catalog",
     ["პროდუქტის საპოვნელად „კატალოგში“ ჩაწერეთ დასახელება საძიებო ველში და გამოიყენეთ ქალაქისა და კატეგორიის ფილტრები. თუ პროდუქტი ვერ იპოვეთ, შეამოწმეთ, გაქვთ თუ არა აქტიური კავშირი შესაბამის დისტრიბუტორთან და მოიცავს თუ არა ის თქვენს ქალაქს."],
     ["retailer"], False),
    (r"პროდუქტ.*(დამატ|შეცვლ|რედაქტ)|მარაგ|ინვენტ|stock|inventory|იმპორტ|csv|excel",
     ["„ინვენტარში“ შეგიძლიათ პროდუქტის დამატება/რედაქტირება, მარაგის განახლება და CSV/Excel იმპორტი. ფასდაკლებისგან გამორიცხული პროდუქტი ინვოისზე აღინიშნება „* ფასდაკლება არ ეხება“."],
     ["supplier"], False),
    (r"თანამშრომელ|თანამშრომლ.*დამატ|მომხმარებელ.*დამატ|employee|staff",
     ["თანამშრომლის დასამატებლად გახსენით მარცხენა მენიუში „თანამშრომლები“ (Employees), შეავსეთ თანამშრომლის სახელი და ელფოსტა, მიუთითეთ ფილიალი და წვდომის როლი/უფლებები და დააჭირეთ თანამშრომლის შექმნის ღილაკს. ეს მოქმედება ხელმისაწვდომია მაღაზიის მფლობელისთვის."],
     ["retailer"], False),
    (r"მარაგის\s*ბრუნ|stock\s*turnover|ბრუნვადობ",
     ["მარაგის ბრუნვის შესაფასებლად გამოიყენეთ ფორმულა: პერიოდის გაყიდული ერთეულების თვითღირებულება ÷ იმავე პერიოდის საშუალო მარაგის თვითღირებულება. მაღალი ბრუნვა սովորաբար ეფექტიან მარაგზე მიუთითებს, თუმცა ზედმეტად მაღალი მაჩვენებელი ამოწურვის რისკსაც ზრდის. აკონტროლეთ მინიმალური ნაშთი, მომწოდებლის მიწოდების ვადა და სეზონურობა; არ შეადაროთ სხვადასხვა ხანგრძლივობის პერიოდები."],
     None, False),
    (r"ფას|price|ფასდაკლ|მოლაპარაკ",
     ["ფასებს ცვლით „ინვენტარში“ პროდუქტის რედაქტირებისას (მათ შორის საფეხურებრივ ფასებს). მაღაზიების მოთხოვნილი ინდივიდუალური ფასები ჩანს „ფასების მოლაპარაკებებში“, სადაც მათ დაადასტურებთ ან უარყოფთ."],
     ["supplier"], False),
    (r"შემოსული|შეკვეთ.*(დამუშავ|სტატუს|დაადასტ)|order",
     ["შემოსული შეკვეთები ჩანს „შეკვეთებში“: დაადასტურეთ და სტატუსი თანმიმდევრულად გადაიყვანეთ (დამუშავება → გზაში → მიწოდებული). ინვოისის PDF-ს გადმოწერთ ან ელფოსტით გააგზავნით იმავე გვერდიდან."],
     ["supplier"], False),
    (r"შეკვეთ|გაფორმ|კალათ|checkout",
     ["შეკვეთის გასაფორმებლად დაამატეთ პროდუქცია კალათაში, გახსენით „კალათა“, შეამოწმეთ რაოდენობები (მინიმალური რაოდენობა უნდა დაიცვათ), მიუთითეთ მისამართი და გადახდის მეთოდი და დააჭირეთ „შეკვეთის გაფორმებას“. ისტორიას ნახავთ „ჩემი შეკვეთები“-ში."],
     ["retailer"], False),
    (r"ინვოის|invoice",
     ["ინვოისი ჩანს შეკვეთაზე: შეგიძლიათ PDF-ად გადმოწერა ან ელფოსტით გაგზავნა. PDF-ში არის შეკვეთის ნომერი, მხარეთა რეკვიზიტები, პროდუქტების ცხრილი, დღგ და მოქმედების ვადა (3 სამუშაო დღე)."],
     None, False),
    (r"გამარჯობა|სალამი|hello|hi\b|კარგად ხარ|მადლობა|გმადლობ",
     ["გამარჯობა! რით დაგეხმაროთ — პლატფორმის გამოყენებაში, ტექნიკურ ხარვეზში თუ ბიზნეს-რჩევაში?",
      "სიამოვნებით! მკითხეთ ნებისმიერ თემაზე: შეკვეთები, ბარათი, ინვოისი, ან ბიზნესის გაუმჯობესება."],
     None, False),
]


class SupportAskIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


class SupportTicketIn(BaseModel):
    message: str = Field(min_length=3, max_length=2000)


class SupportReplyIn(BaseModel):
    reply: str = Field(min_length=1, max_length=2000)


class BroadcastNotificationIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    audience: str = Field(pattern="^(all|stores|distributors)$")

    @field_validator("text")
    @classmethod
    def normalize_broadcast_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message text cannot be blank.")
        return value


async def _distro_llm_reply(text: str, user: dict, facts: Optional[str], hint: Optional[str]) -> Optional[str]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    role_ka = {"retailer": "მაღაზია", "supplier": "დისტრიბუტორი"}.get(user.get("role"), "მომხმარებელი")
    context = f"User type: {role_ka}."
    if facts:
        context += f"\nVERIFIED DATA from the user's own account (use exactly these figures):\n{facts}"
    if hint:
        context += f"\nPlatform guidance:\n{hint}"
    history_ok = [
        {"role": "system", "content": DISTRO_SYSTEM_PROMPT + "\n\n" + context},
        {"role": "user", "content": text},
    ]
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"), "messages": history_ok,
                      "temperature": 0.4, "max_tokens": 600},
            )
        if resp.status_code != 200:
            logger.warning("Distro LLM call failed: HTTP %s", resp.status_code)
            return None
        reply = (resp.json()["choices"][0]["message"]["content"] or "").strip()
    except Exception as exc:
        logger.warning("Distro LLM call error: %s", type(exc).__name__)
        return None
    if _SUPPORT_BLOCKED.search(reply) or api_key in reply:
        return None
    return reply or None


@api.post("/support/assistant")
async def support_assistant(body: SupportAskIn, user: dict = Depends(get_current_user)):
    text = body.message.strip()
    result = await _support_rule_reply(text, user)
    if result.get("locked"):
        return {"reply": result["reply"], "suggest_admin": result["suggest_admin"]}
    kind = result.get("kind")
    llm = await _distro_llm_reply(
        text, user,
        result["reply"] if kind == "data" else None,
        result["reply"] if kind == "topic" else None,
    )
    if llm:
        return {"reply": llm, "suggest_admin": result["suggest_admin"] and kind == "fallback"}
    return {"reply": result["reply"], "suggest_admin": result["suggest_admin"]}


async def _support_rule_reply(text: str, user: dict) -> dict:
    if _SUPPORT_BLOCKED.search(text):
        return {"reply": "ვერ გავცემ კოდს, გასაღებებს ან შიდა ტექნიკურ ინფორმაციას. დაგეხმარებით პლატფორმის გამოყენებაში; საჭიროების შემთხვევაში დაგაკავშირებთ ადმინისტრატორს.",
                "suggest_admin": True, "locked": True}
    data_builders = (_support_role_overview, _support_product_answer)
    if _ACCOUNTING_QUESTION.search(text) or (_FINANCIAL_QUESTION.search(text) and re.search(r"(თვე|month)", text, re.I)):
        if not _support_can_view_financials(user):
            return {"reply": "ფინანსურ მონაცემებზე თქვენი ანგარიშისთვის წვდომა არ არის ჩართული. მიმართეთ მაღაზიის მფლობელს.",
                    "suggest_admin": False, "locked": True}
    financial_answer = await _support_monthly_financial_answer(text, user)
    if financial_answer:
        return {"reply": financial_answer, "suggest_admin": False, "kind": "data"}
    accounting_answer = await _support_accounting_answer(text, user)
    if accounting_answer:
        return {"reply": accounting_answer, "suggest_admin": False, "kind": "data"}
    for builder in data_builders:
        data_answer = await builder(text, user)
        if data_answer:
            return {"reply": data_answer, "suggest_admin": False, "kind": "data"}
    category_answer = await _support_category_answer(text, user)
    if category_answer:
        return {"reply": category_answer, "suggest_admin": False, "kind": "data"}
    role = user.get("role")
    for pattern, variants, roles, escalate in _SUPPORT_TOPICS:
        if (roles is None or role in roles) and re.search(pattern, text, re.I):
            return {"reply": random.choice(variants), "suggest_admin": escalate, "kind": "topic"}
    for pattern, answer in _SUPPORT_KB.get(role, []):
        if re.search(pattern, text, re.I):
            return {"reply": answer, "suggest_admin": False, "kind": "topic"}
    return {"reply": _SUPPORT_FALLBACK, "suggest_admin": True, "kind": "fallback"}


@api.post("/support/tickets")
async def create_support_ticket(body: SupportTicketIn, user: dict = Depends(get_current_user)):
    user_type = _SUPPORT_USER_TYPE.get(user.get("role"), "other")
    ticket = {
        "id": str(uuid.uuid4()), "user_id": user["id"], "user_type": user_type,
        "user_name": user.get("business_name") or user.get("name") or "",
        "user_email": user.get("email", ""), "message": body.message.strip(),
        "status": "open", "replies": [], "created_at": now_iso(),
    }
    await db.support_tickets.insert_one(dict(ticket))
    type_ka = _SUPPORT_TYPE_KA.get(user_type, user_type)
    admins = await db.users.find(
        {"role": "admin", "status": {"$ne": "suspended"}},
        {"_id": 0, "id": 1, "name": 1, "business_name": 1, "email": 1, "phone": 1, "role": 1},
    ).to_list(100)
    for a in admins:
        await notify(a["id"], f"მხარდაჭერა [{type_ka}] {ticket['user_name']}: {ticket['message'][:120]}", "support")
    admin = admins[0] if admins else None
    if admin:
        await _save_registered_contact(user["id"], admin)
        await _save_registered_contact(admin["id"], user)
        await db.messages.insert_one({
            "id": str(uuid.uuid4()),
            "from_id": user["id"],
            "from_name": ticket["user_name"],
            "to_id": admin["id"],
            "text": ticket["message"],
            "order_id": "",
            "read": False,
            "created_at": ticket["created_at"],
        })
    return {**ticket, "admin_id": admin["id"] if admin else None}


@api.get("/support/tickets")
async def my_support_tickets(user: dict = Depends(get_current_user)):
    return await db.support_tickets.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(200)


@api.get("/admin/support/tickets")
async def admin_support_tickets(status: Optional[str] = None, user_type: Optional[str] = None,
                                user: dict = Depends(require_role("admin"))):
    q = {}
    if status:
        q["status"] = status
    if user_type in ("store", "distributor"):
        q["user_type"] = user_type
    return await db.support_tickets.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)


@api.post("/admin/support/tickets/{tid}/reply")
async def admin_support_reply(tid: str, body: SupportReplyIn, user: dict = Depends(require_role("admin"))):
    ticket = await db.support_tickets.find_one({"id": tid}, {"_id": 0})
    if not ticket:
        raise HTTPException(404, "Ticket not found.")
    reply = {"by": user.get("name") or "Admin", "text": body.reply.strip(), "created_at": now_iso()}
    await db.support_tickets.update_one({"id": tid}, {"$push": {"replies": reply}, "$set": {"status": "answered"}})
    await notify(ticket["user_id"], f"ადმინისტრატორის პასუხი: {reply['text'][:150]}", "support")
    return {"ok": True}


@api.post("/admin/support/tickets/{tid}/close")
async def admin_support_close(tid: str, user: dict = Depends(require_role("admin"))):
    res = await db.support_tickets.update_one({"id": tid}, {"$set": {"status": "closed"}})
    if not res.matched_count:
        raise HTTPException(404, "Ticket not found.")
    return {"ok": True}


def _broadcast_audience_query(audience: str) -> dict:
    roles = {"all": ["retailer", "supplier"], "stores": ["retailer"],
             "distributors": ["supplier"]}[audience]
    return {"role": {"$in": roles}, "status": {"$ne": "suspended"}}


async def _deliver_broadcast(broadcast_id: str) -> None:
    campaign = await db.broadcast_campaigns.find_one({"id": broadcast_id}, {"_id": 0})
    if not campaign:
        return
    claim = await db.broadcast_campaigns.update_one(
        {"id": broadcast_id, "status": "queued"},
        {"$set": {"status": "sending", "started_at": now_iso(), "updated_at": now_iso()}},
    )
    if not claim.modified_count:
        return

    sent_count = 0
    failed_count = 0
    processed_count = 0
    delivery_limit = asyncio.Semaphore(25)
    query = _broadcast_audience_query(campaign["audience"])
    try:
        recipients = db.users.find(query, {"_id": 0, "id": 1})
        batch = []

        async def send_batch(users):
            nonlocal sent_count, failed_count, processed_count
            async def send_one(recipient):
                async with delivery_limit:
                    notification_id = str(uuid.uuid5(
                        uuid.NAMESPACE_URL, f"distro-broadcast:{broadcast_id}:{recipient['id']}",
                    ))
                    await notify(
                        recipient["id"], campaign["text"], "broadcast", notification_id=notification_id,
                        broadcast_id=broadcast_id,
                    )

            results = await asyncio.gather(*(send_one(recipient) for recipient in users), return_exceptions=True)
            sent_count += sum(not isinstance(result, BaseException) for result in results)
            failed_count += sum(isinstance(result, BaseException) for result in results)
            for result in results:
                if isinstance(result, BaseException):
                    logger.error("Broadcast recipient delivery failed: %s", type(result).__name__)
            processed_count += len(users)
            await db.broadcast_campaigns.update_one({"id": broadcast_id}, {"$set": {
                "recipient_count": processed_count, "sent_count": sent_count,
                "failed_count": failed_count, "updated_at": now_iso(),
            }})

        async for recipient in recipients:
            batch.append(recipient)
            if len(batch) >= 200:
                await send_batch(batch)
                batch = []
        if batch:
            await send_batch(batch)

        status = "completed" if failed_count == 0 else "partial"
        completed_at = now_iso()
        await db.broadcast_campaigns.update_one({"id": broadcast_id}, {"$set": {
            "status": status, "recipient_count": processed_count, "sent_count": sent_count,
            "failed_count": failed_count, "completed_at": completed_at, "updated_at": completed_at,
        }})
        await log_financial_event(
            "admin_broadcast_completed", campaign.get("actor", {}), "broadcast", broadcast_id,
            after={"text": campaign["text"], "audience": campaign["audience"],
                   "recipient_count": processed_count, "sent_count": sent_count,
                   "failed_count": failed_count},
            status="success" if failed_count == 0 else "error",
        )
    except Exception:
        logger.exception("Broadcast delivery failed: %s", broadcast_id)
        completed_at = now_iso()
        await db.broadcast_campaigns.update_one({"id": broadcast_id}, {"$set": {
            "status": "failed", "recipient_count": processed_count, "sent_count": sent_count,
            "failed_count": max(failed_count, campaign.get("recipient_count", 0) - sent_count),
            "completed_at": completed_at, "updated_at": completed_at,
        }})
        await log_financial_event(
            "admin_broadcast_failed", campaign.get("actor", {}), "broadcast", broadcast_id,
            after={"text": campaign["text"], "audience": campaign["audience"],
                   "recipient_count": processed_count, "sent_count": sent_count}, status="error",
        )


def _spawn_broadcast_task(broadcast_id: str) -> None:
    tasks = getattr(app.state, "broadcast_tasks", None)
    if tasks is None:
        tasks = set()
        app.state.broadcast_tasks = tasks
    task = asyncio.create_task(_deliver_broadcast(broadcast_id))
    tasks.add(task)
    task.add_done_callback(tasks.discard)


async def _recover_broadcasts() -> None:
    stale_before = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    await db.broadcast_campaigns.update_many(
        {"status": "sending", "updated_at": {"$lt": stale_before}},
        {"$set": {"status": "queued", "updated_at": now_iso()}},
    )
    queued = db.broadcast_campaigns.find({"status": "queued"}, {"_id": 0, "id": 1})
    async for campaign in queued:
        _spawn_broadcast_task(campaign["id"])


@api.post("/admin/broadcast-notification")
async def create_admin_broadcast(
    body: BroadcastNotificationIn,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_role("admin")),
):
    audience_query = _broadcast_audience_query(body.audience)
    recipient_count = await db.users.count_documents(audience_query)
    if recipient_count == 0:
        raise HTTPException(409, "No active recipients match this audience.")
    created_at = now_iso()
    broadcast_id = str(uuid.uuid4())
    campaign = {
        "id": broadcast_id, "text": body.text, "audience": body.audience,
        "recipient_count": recipient_count, "sent_count": 0, "failed_count": 0,
        "status": "queued", "actor": {"id": user["id"], "name": user.get("name") or user.get("business_name", "")},
        "created_at": created_at, "updated_at": created_at,
    }
    await db.broadcast_campaigns.insert_one(campaign)
    try:
        await log_financial_event(
            "admin_broadcast_queued", user, "broadcast", broadcast_id,
            after={"text": body.text, "audience": body.audience, "recipient_count": recipient_count},
            status="pending",
        )
    except Exception:
        await db.broadcast_campaigns.update_one({"id": broadcast_id}, {"$set": {"status": "failed"}})
        raise
    background_tasks.add_task(_deliver_broadcast, broadcast_id)
    return {"id": broadcast_id, "status": "queued", "recipient_count": recipient_count}


@api.get("/admin/broadcast-notification/history")
async def admin_broadcast_history(
    limit: int = Query(50, ge=1, le=100),
    user: dict = Depends(require_role("admin")),
):
    return await db.broadcast_campaigns.find({}, {"_id": 0, "actor.id": 0}).sort(
        "created_at", -1,
    ).limit(limit).to_list(limit)


# ---------- notifications ----------
@api.get("/notifications")
async def get_notifications(
    response: Response, limit: Optional[int] = None, offset: int = 0, unread_only: bool = False,
    user: dict = Depends(get_current_user),
):
    q = {"user_id": user["id"]}
    if unread_only:
        q["read"] = False
    size, skip = _page(limit, offset, 100)
    response.headers["X-Total-Count"] = str(await db.notifications.count_documents(q))
    return await db.notifications.find(q, {"_id": 0}).sort("created_at", -1).skip(skip).limit(size).to_list(size)

class PushKeysIn(BaseModel):
    p256dh: str = Field(min_length=1, max_length=256)
    auth: str = Field(min_length=1, max_length=128)


class PushSubscriptionIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=2048)
    keys: PushKeysIn


class PushUnsubscribeIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=2048)


@api.get("/push/public-key")
async def push_public_key(user: dict = Depends(get_current_user)):
    _, public_key = await web_push.get_vapid(db)
    return {"public_key": public_key}


@api.post("/push/subscribe")
async def push_subscribe(body: PushSubscriptionIn, user: dict = Depends(get_current_user)):
    # An endpoint identifies one browser profile; re-binding it moves pushes to whoever is signed in now.
    try:
        await db.push_subscriptions.update_one(
            {"endpoint": body.endpoint},
            {"$set": {"user_id": user["id"], "keys": body.keys.model_dump(), "updated_at": now_iso()},
             "$setOnInsert": {"created_at": now_iso()}},
            upsert=True,
        )
    except Exception as error:
        details = traceback.format_exc()
        for secret in (body.endpoint, body.keys.p256dh, body.keys.auth):
            details = details.replace(secret, "[REDACTED]")
        logger.error(
            "Push subscription persistence failed user=%s error=%s traceback:\n%s",
            user["id"], type(error).__name__, details,
        )
        raise HTTPException(500, "Could not save push subscription.") from error
    return {"ok": True}


@api.post("/push/unsubscribe")
async def push_unsubscribe(body: PushUnsubscribeIn, user: dict = Depends(get_current_user)):
    await db.push_subscriptions.delete_many({"endpoint": body.endpoint, "user_id": user["id"]})
    return {"ok": True}


@api.post("/notifications/read")
async def read_notifications(user: dict = Depends(get_current_user)):
    await db.notifications.update_many({"user_id": user["id"]}, {"$set": {"read": True}})
    return {"ok": True}

@api.post("/notifications/{notification_id}/read")
async def read_notification(notification_id: str, user: dict = Depends(get_current_user)):
    result = await db.notifications.update_one(
        {"id": notification_id, "user_id": user["id"]}, {"$set": {"read": True}}
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Notification not found")
    return {"ok": True}


# ---------- profile ----------
@api.put("/profile")
async def update_profile(body: ProfileIn, user: dict = Depends(get_current_user)):
    upd = {k: v for k, v in body.model_dump().items() if v is not None}
    upd.pop("establishment_type", None)
    upd.pop("establishment_type_other", None)
    if upd.get("city") is not None:
        upd["city"] = _canon_city(upd["city"])
    if "accountant_email" in upd:
        upd["accountant_email"] = upd["accountant_email"].strip().lower()
        if upd["accountant_email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", upd["accountant_email"]):
            raise HTTPException(422, "ბუღალტრის ელ.ფოსტა არასწორია")
    if "business_sectors" in upd:
        if user.get("role") != "supplier":
            upd.pop("business_sectors")
        else:
            upd["business_sectors"] = list(dict.fromkeys(str(s).strip() for s in upd["business_sectors"] if str(s).strip()))
            upd["servedSectors"] = upd["business_sectors"]
    if "identification_number" in upd:
        upd["identification_number"] = upd["identification_number"].strip()
        if not upd["identification_number"].isdigit() or len(upd["identification_number"]) not in (9, 11):
            raise HTTPException(422, "საიდენტიფიკაციო ან პირადი ნომერი უნდა შედგებოდეს ზუსტად 9 ან 11 ციფრისგან!")
    if "cities" in upd:
        upd["cities"] = _normalize_service_cities(upd["cities"], upd.get("city", user.get("city")))
    if "category_ids" in upd:
        if user.get("role") != "supplier":
            upd.pop("category_ids")
        else:
            upd["category_ids"], names = await _resolve_supplier_categories(upd["category_ids"])
            upd["category"] = ", ".join(names)
    if user.get("role") != "retailer":
        for k in ("card_name", "card_number", "card_expiry"):
            upd.pop(k, None)
    elif "card_number" in upd:
        num = upd.pop("card_number")
        if num:
            upd["card_last4"] = mask_card(num)
    if user.get("role") == "supplier":
        if "bank_name" in upd:
            upd["bank_name"] = _validate_bank_name(upd["bank_name"])
        if "iban" in upd:
            upd["iban"] = _validate_iban(upd["iban"])
        if "bank_accounts" in upd:
            accounts, seen = [], set()
            for raw in upd["bank_accounts"][:10]:
                iban = _validate_iban(raw.get("iban"))
                if not iban or iban in seen:
                    continue
                seen.add(iban)
                previous = next((a for a in user.get("bank_accounts") or [] if a.get("iban") == iban), None)
                accounts.append({
                    "id": (previous or {}).get("id") or str(uuid.uuid4()),
                    "bank_name": _validate_bank_name(raw.get("bank_name")),
                    "iban": iban,
                    "bank_code": (raw.get("bank_code") or iban[4:6]).strip().upper()[:11],
                })
            upd["bank_accounts"] = accounts
            if accounts:
                upd["bank_name"], upd["iban"] = accounts[0]["bank_name"], accounts[0]["iban"]
    else:
        upd.pop("bank_name", None)
        upd.pop("iban", None)
        upd.pop("bank_accounts", None)
    if user.get("role") == "supplier" and any(k in upd for k in ("bank_name", "iban", "bank_accounts")):
        before = {k: user.get(k) for k in ("bank_name", "iban", "bank_accounts")}
        after = {k: upd.get(k, user.get(k)) for k in before}
        if before != after:
            # Orders keep their own bank_account_snapshot; only the profile changes.
            await db.bank_account_history.insert_one({
                "id": str(uuid.uuid4()), "supplier_id": user["id"], "replaced": safeguards.redact(before),
                "replaced_by": safeguards.redact(after), "changed_at": now_iso(),
            })
            await log_financial_event("bank_details_changed", user, "supplier_bank", user["id"], before, after)
    await db.users.update_one({"id": user["id"]}, {"$set": _encrypt_sensitive_fields(upd)})
    if user.get("role") == "supplier" and upd.get("business_name"):
        await db.products.update_many({"supplier_id": user["id"]}, {"$set": {"supplier_name": upd["business_name"]}})
    updated_user = await db.users.find_one({"id": user["id"]}, {"_id": 0, "password_hash": 0})
    return public_user_document(updated_user)


# ---------- business logo ----------
@api.post("/profile/logo")
async def upload_logo(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    data = await file.read(2 * 1024 * 1024 + 1)
    try:
        png = process_upload(data)
        await asyncio.to_thread(save_logo, user["id"], png)
    except LogoError as e:
        raise HTTPException(400, str(e))
    version = int(time.time())
    await db.users.update_one({"id": user["id"]}, {"$set": {"logo_url": f"/logos/{user['id']}?v={version}"}})
    return public_user_document(await db.users.find_one({"id": user["id"]}, {"_id": 0}))


@api.delete("/profile/logo")
async def remove_logo(user: dict = Depends(get_current_user)):
    await asyncio.to_thread(delete_logo, user["id"])
    await db.users.update_one({"id": user["id"]}, {"$unset": {"logo_url": ""}})
    return public_user_document(await db.users.find_one({"id": user["id"]}, {"_id": 0}))


@api.get("/logos/{user_id}")
@api.get("/profile/logo/{user_id}")
async def get_logo(user_id: str):
    # Public on purpose: <img> tags cannot send the Bearer header, and logos are not sensitive.
    owner = await db.users.find_one({"id": user_id}, {"_id": 0, "business_name": 1, "name": 1})
    name = (owner or {}).get("business_name") or (owner or {}).get("name") or ""
    png = await asyncio.to_thread(logo_bytes, user_id, name)
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff"})


# ---------- platform settings (service fee) ----------
@api.get("/settings")
async def read_settings(user: dict = Depends(get_current_user)):
    return public_settings(await get_settings())


@api.get("/admin/settings")
async def read_admin_settings(user: dict = Depends(require_role("admin"))):
    return public_settings(await get_settings(), include_sensitive=True)

@api.put("/admin/settings")
async def write_settings(body: SettingsIn, user: dict = Depends(require_role("admin"))):
    if body.fee_type not in ("percent", "fixed"):
        raise HTTPException(400, "Invalid fee type")
    if body.fee_payer not in ("supplier", "retailer", "split"):
        raise HTTPException(400, "Invalid fee payer")
    if body.payment_provider is not None and body.payment_provider not in ("tbc", "bog", "stripe"):
        raise HTTPException(400, "Invalid payment provider")
    upd = {"fee_type": body.fee_type, "fee_value": body.fee_value, "fee_payer": body.fee_payer}
    for k in ("issuer_name", "issuer_tax_id", "issuer_iban",
              "billing_overdue_limit", "billing_overdue_days", "billing_reminder_days",
              "payment_provider", "payment_split_enabled"):
        v = getattr(body, k)
        if v is not None:
            upd[k] = _encrypt_sensitive_fields({"issuer_iban": v})["issuer_iban"] if k == "issuer_iban" else v
    if body.payment_client_id is not None:
        upd["payment_client_id"] = body.payment_client_id.strip()
    if body.payment_secret and body.payment_secret.strip():
        upd["payment_secret_enc"] = encrypt_secret(body.payment_secret.strip())
    await db.settings.update_one({"id": "platform"}, {"$set": upd}, upsert=True)
    return public_settings(await get_settings(), include_sensitive=True)


# ---------- categories ----------
DEFAULT_CATEGORY_NAMES = ["Beverages", "Groceries", "Snacks & Sweets", "Dry Goods", "Household Chemicals", "Packaging", "Hygiene", "Pet Supplies"]
_ALL_STD = set(DEFAULT_CATEGORY_NAMES)
# Which standard categories each establishment type buys. Unlisted types see everything.
ESTABLISHMENT_CATEGORIES = {
    "grocery": _ALL_STD - {"Pet Supplies"},
    "zoo": {"Pet Supplies", "Household Chemicals"},
    "pet_shop": {"Pet Supplies", "Household Chemicals"},
    "household": {"Household Chemicals", "Hygiene", "Packaging"},
    "restaurant_cafe_bar": {"Beverages", "Groceries", "Dry Goods", "Household Chemicals", "Hygiene", "Packaging"},
    "hotel_hostel": {"Household Chemicals", "Hygiene", "Packaging", "Beverages", "Dry Goods"},
    "laundry": {"Household Chemicals", "Hygiene", "Packaging"},
    "office_company": {"Household Chemicals", "Hygiene", "Packaging", "Beverages", "Dry Goods"},
    "carwash": {"Household Chemicals", "Packaging", "Hygiene"},
    "pharmacy": {"Hygiene", "Packaging", "Household Chemicals"},
    "horeca": _ALL_STD - {"Pet Supplies"},
}


def _category_allowed(name: str, allowed: Optional[set]) -> bool:
    # Custom categories outside the standard list are never restricted.
    return allowed is None or name in allowed or name not in _ALL_STD


async def _allowed_categories_for_user(user: Optional[dict]) -> Optional[set]:
    if not user or user.get("role") != "retailer":
        return None
    est = user.get("entityType") or user.get("entity_type") or user.get("businessType") or user.get("business_type") or user.get("establishment_type")
    if not est and store_owner_id(user) != user["id"]:
        owner = await db.users.find_one(
            {"id": store_owner_id(user)},
            {"_id": 0, "entityType": 1, "entity_type": 1, "businessType": 1, "business_type": 1, "establishment_type": 1},
        )
        est = (owner or {}).get("entityType") or (owner or {}).get("entity_type") or (owner or {}).get("businessType") or (owner or {}).get("business_type") or (owner or {}).get("establishment_type")
    sector = _normalize_business_sector(est)
    return ESTABLISHMENT_CATEGORIES.get(sector)


def _normalize_business_sector(value: Optional[str]) -> str:
    sector = str(value or "").strip().lower()
    aliases = {
        "სასურსათო მაღაზია": "grocery",
        "ზოო მაღაზია": "pet_shop",
        "zoo": "pet_shop",
        "საყოფაცხოვრებო საქონლის მაღაზია": "household",
        "რესტორანი / კაფე / ბარი": "restaurant_cafe_bar",
        "სასტუმრო / ჰოსტელი": "hotel_hostel",
        "სამრეცხაო": "laundry",
        "ოფისი / კომპანია": "office_company",
    }
    return aliases.get(sector, re.sub(r"[\s/-]+", "_", sector))


def _entity_group_for_type(value: Optional[str]) -> str:
    return "RETAIL" if _normalize_business_sector(value) in {"grocery", "pet_shop", "household"} else "SERVICE"


async def _entity_type_for_user(user: Optional[dict]) -> Optional[str]:
    if not user or user.get("role") != "retailer":
        return None
    entity_type = user.get("entityType") or user.get("entity_type") or user.get("businessType") or user.get("business_type") or user.get("establishment_type")
    if not entity_type and store_owner_id(user) != user["id"]:
        owner = await db.users.find_one(
            {"id": store_owner_id(user)},
            {"_id": 0, "entityType": 1, "entity_type": 1, "businessType": 1, "business_type": 1, "establishment_type": 1},
        )
        entity_type = (owner or {}).get("entityType") or (owner or {}).get("entity_type") or (owner or {}).get("businessType") or (owner or {}).get("business_type") or (owner or {}).get("establishment_type")
    return _normalize_business_sector(entity_type) or None


def _supplier_serves_entity(supplier: dict, entity_type: str) -> bool:
    sectors = supplier.get("servedSectors") or supplier.get("business_sectors") or []
    return any(_normalize_business_sector(sector) == entity_type for sector in sectors)


# Georgian labels map onto the canonical English names so the same category is never listed twice.
CATEGORY_ALIASES = {
    "პროდუქტები ცხოველებისთვის": "pet supplies", "ცხოველთა საკვები": "pet supplies", "ცხოველთა პროდუქცია": "pet supplies",
    "სასმელები": "beverages", "სურსათი": "groceries", "საკვები პროდუქტები": "groceries",
    "სნექები და ტკბილეული": "snacks & sweets", "სნეკები და ტკბილეული": "snacks & sweets",
    "მშრალი პროდუქტები": "dry goods", "მშრალი პროდუქტი": "dry goods",
    "საყოფაცხოვრებო ქიმია": "household chemicals", "შეფუთვა": "packaging", "ჰიგიენა": "hygiene",
}


async def _retailer_city(user: Optional[dict]) -> Optional[str]:
    if not user or user.get("role") != "retailer":
        return None
    city = _canon_city(user.get("city"))
    if not city and store_owner_id(user) != user["id"]:
        owner = await db.users.find_one({"id": store_owner_id(user)}, {"_id": 0, "city": 1})
        city = _canon_city((owner or {}).get("city"))
    return city or None


async def _serving_supplier_ids(entity_type: str, city: Optional[str] = None) -> List[str]:
    suppliers = await db.users.find(
        {"role": "supplier"}, {"_id": 0, "id": 1, "city": 1, "cities": 1, "business_sectors": 1, "servedSectors": 1},
    ).to_list(5000)
    return [s["id"] for s in suppliers
            if _supplier_serves_entity(s, entity_type) and _supplier_serves_city(s, city)]


@api.get("/categories")
async def list_categories(user: Optional[dict] = Depends(get_current_user)):
    allowed = await _allowed_categories_for_user(user)
    cats = await db.categories.find({}, {"_id": 0}).sort("name", 1).to_list(200)
    names = list(dict.fromkeys(c["name"] for c in cats if _category_allowed(c["name"], allowed)))
    entity_type = await _entity_type_for_user(user)
    if entity_type:
        serving_ids = await _serving_supplier_ids(entity_type, await _retailer_city(user))
        present = set(await db.products.distinct("category", {"supplier_id": {"$in": serving_ids}})) if serving_ids else set()
        names = [n for n in names if n in present]
    return names


@api.get("/categories/options")
async def list_category_options():
    cats = await db.categories.find({}, {"_id": 0, "id": 1, "name": 1}).sort("name", 1).to_list(200)
    seen, out = set(), []
    for c in cats:
        if not c.get("id") or not c.get("name"):
            continue
        key = CATEGORY_ALIASES.get(c["name"].strip().casefold(), c["name"].strip().casefold())
        if key in seen:
            continue
        seen.add(key)
        out.append({"id": c["id"], "name": c["name"]})
    return out


async def _resolve_supplier_categories(category_ids: List[str]) -> tuple:
    """Validate the selected Category ids; returns (unique ids, their names)."""
    ids = list(dict.fromkeys(str(i).strip() for i in (category_ids or []) if str(i).strip()))
    if not ids:
        return [], []
    found = await db.categories.find({"id": {"$in": ids}}, {"_id": 0, "id": 1, "name": 1}).to_list(len(ids))
    by_id = {c["id"]: c["name"] for c in found}
    unknown = [i for i in ids if i not in by_id]
    if unknown:
        raise HTTPException(400, "არჩეული კატეგორია ვერ მოიძებნა.")
    return ids, [by_id[i] for i in ids]


async def _declared_category_names(supplier_ids: List[str]) -> dict:
    """supplier_id -> set of declared category names (suppliers with no selection are omitted)."""
    suppliers = await db.users.find(
        {"id": {"$in": supplier_ids}}, {"_id": 0, "id": 1, "category_ids": 1},
    ).to_list(len(supplier_ids) or 1)
    all_ids = {cid for s in suppliers for cid in s.get("category_ids") or []}
    if not all_ids:
        return {}
    cats = await db.categories.find({"id": {"$in": list(all_ids)}}, {"_id": 0, "id": 1, "name": 1}).to_list(len(all_ids))
    names = {c["id"]: c["name"] for c in cats}
    return {
        s["id"]: {names[cid] for cid in s.get("category_ids") or [] if cid in names}
        for s in suppliers if any(cid in names for cid in s.get("category_ids") or [])
    }

@api.post("/categories")
async def add_category(body: CategoryIn, user: dict = Depends(get_current_user)):
    if user["role"] not in ("admin", "supplier"):
        raise HTTPException(403, "Not allowed")
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "Name required")
    business_id = supplier_owner_id(user) if user.get("role") == "supplier" else None
    resolved = await _resolve_business_category_name(name, business_id=business_id)
    return await list_categories(user)


CATEGORY_MAP = {
    "სასმელები": ["სასმელები", "სასმელი", "წვენი", "წვენები", "წყალი", "წყლები", "კოკაკოლა", "კოკა-კოლა", "კოლა", "ფანტა", "სპრაით", "ლიმონადი", "ლუდი", "ღვინო", "juice", "water", "cola", "fanta", "sprite", "lemonade", "beer", "wine"],
    "ჰიგიენა": ["ჰიგიენა", "სალფეტკი", "სალფეტები", "საპონი", "საპნები", "შამპუნი", "შამპუნები", "ტუალეტი", "ტუალეტის", "ქაღალდი", "ტამპონი", "დეზოდორანტი", "soap", "shampoo", "napkin", "tissue", "toilet", "diaper", "toothpaste", "wipe"],
    "ნახევარფაბრიკატები": ["ნახევარფაბრიკატები", "ნახევარფაბრიკატი", "ხინკალი", "ხინკლები", "პელმენი", "პელმენები", "ვარენიკი", "ვარნიკი", "მანტი", "ნაგეტები", "ნაგეტი", "dumpling", "dumplings", "pelmeni", "khinkali", "nugget", "frozen"],
    "საყოფაცხოვრებო ქიმია": ["საყოფაცხოვრებო ქიმია", "სარეცხი", "ფხვნილი", "გამწმენდი", "ქლორი", "ბრილიანტი", "detergent", "bleach", "cleaner"],
    "სნექები და ტკბილეული": ["სნექები", "სნექი", "ტკბილეული", "ჩიფსი", "შოკოლადი", "კანფეტი", "ვაფლი", "ნამცხვარი", "snack", "chips", "chocolate", "candy", "cookie", "wafer"],
    "მშრალი პროდუქტები": ["მშრალი პროდუქტები", "ბრინჯი", "მაკარონი", "ფქვილი", "შაქარი", "მარილი", "ბურღულეული", "ზეთი", "რძე", "flour", "rice", "pasta", "sugar", "salt", "oil", "milk"],
    "სურსათი": ["სურსათი", "პური", "ყავა", "ხორცი", "თევზი", "კვერცხი", "კარაქი", "მაიონეზი", "კეტჩუპი", "ძეხვი", "იოგურტი", "ხაჭო", "bread", "cheese", "meat", "egg", "butter", "sausage"],
}


def _normalize_category_name(value: str) -> str:
    return " ".join(re.sub(r"[^\w\u10d0-\u10fa\u10fd\u10fc\u10fe\u10ff\u10f0-\u10f5\u10f6\u10f7\u10f8\u10f9A-Za-z0-9]+", " ", str(value or "")).split()).casefold()


CATEGORY_GROUP_LOOKUP = {}
for canonical, variants in CATEGORY_MAP.items():
    for variant in variants:
        CATEGORY_GROUP_LOOKUP[_normalize_category_name(variant)] = canonical
CATEGORY_GROUP_LOOKUP.update({
    "beverages": "სასმელები",
    "hygiene": "ჰიგიენა",
    "semi finished goods": "ნახევარფაბრიკატები",
    "semi_finished_goods": "ნახევარფაბრიკატები",
    "groceries": "სურსათი",
    "dry goods": "მშრალი პროდუქტები",
    "household chemicals": "საყოფაცხოვრებო ქიმია",
    "packaging": "შეფუთვა",
    "snacks sweets": "სნექები და ტკბილეული",
    "snacks & sweets": "სნექები და ტკბილეული",
    "pet supplies": "ცხოველთა საკვები",
})


def _category_group_name(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    clean = str(value).strip()
    if not clean:
        return None
    key = _normalize_category_name(clean)
    if not key or key in {"other", "სხვა", "others", "other products"}:
        return None
    if key in CATEGORY_GROUP_LOOKUP:
        return CATEGORY_GROUP_LOOKUP[key]
    return None


async def _resolve_business_category(
    raw_name: Optional[str], business_id: Optional[str] = None,
) -> tuple[str, Optional[str]]:
    raw_name = (raw_name or "").strip() or "Other"
    canonical = (_category_group_name(raw_name) or classify_product_category(raw_name) or raw_name).strip()
    if not canonical or canonical in {"Other", "სხვა"}:
        canonical = canonical or "Other"
    category_collection = getattr(db, "categories", None)
    if business_id and category_collection is not None:
        variants = [str(v).strip() for v in CATEGORY_MAP.get(canonical, [canonical]) if str(v).strip()]
        variant_keys = {_normalize_category_name(v) for v in variants + [canonical] if v}
        existing = await category_collection.find({"business_id": business_id}, {"_id": 0, "id": 1, "name": 1}).to_list(500)
        match = next((
            c for c in existing
            if c.get("id") and _normalize_category_name(c.get("name", "")) in variant_keys
        ), None)
        if match:
            return str(match["name"]), match.get("id")
        doc = {"id": str(uuid.uuid4()), "name": canonical, "business_id": business_id}
        await category_collection.insert_one(doc)
        return canonical, doc["id"]
    return await ensure_category_name(canonical), None


async def _resolve_business_category_name(raw_name: Optional[str], business_id: Optional[str] = None) -> str:
    name, _ = await _resolve_business_category(raw_name, business_id)
    return name


# Product-name keyword rules run before CATEGORY_MAP synonym matching.
_SMART_CATEGORY_RULES = [
    ("ნახევარფაბრიკატები", ["ხინკალ", "პელმენ", "ვარენიკ", "ნაგეთს", "ნაგეტ", "მანტი", "დაქუცმაცებულ", "ნახევარფაბრ",
                            "dumpling", "pelmen", "khinkali", "nugget", "frozen"]),
    ("ჰიგიენა", ["სალფეტ", "საპონ", "შამპუნ", "კბილის", "პასტა კბილ", "ქაღალდ", "ტუალეტ", "პამპერს", "საფენ", "დეზოდორ",
                 "ხელსახოც", "ტამპონ", "საპარ", "soap", "shampoo", "napkin", "tissue", "toilet", "diaper", "toothpaste"]),
    ("საყოფაცხოვრებო ქიმია", ["სარეცხ", "ფხვნილ", "გამწმენდ", "ქლორ", "ჭურჭლის", "დეტერჯენტ", "ლაქის", "detergent", "bleach", "cleaner"]),
    ("სასმელები", ["კოკაკოლა", "კოკა-კოლა", "კოლა", "ფანტა", "სპრაით", "წვენ", "წყალი", "ლუდ", "ღვინ", "ლიმონად", "ენერგეტ",
                   "ბორჯომ", "ნაბეღლავ", "ჩაი", "ყავა", "სასმელ", "cola", "fanta", "sprite", "juice", "water", "beer", "wine",
                   "lemonade", "energy"]),
    ("ცხოველთა საკვები", ["ძაღლის", "კატის", "ცხოველ", "dog food", "cat food", "pet"]),
    ("სნექები და ტკბილეული", ["ჩიფს", "შოკოლად", "ნამცხვარ", "ორცხობილ", "კანფეტ", "ტკბილეულ", "ფისტაშ", "სნექ", "სნეკ", "ვაფლ",
                              "ტაფი", "ჟელე", "ნაყინ", "chips", "chocolate", "candy", "cookie", "snack", "wafer"]),
    ("შეფუთვა", ["პარკ", "ცელოფან", "ჭიქა", "კოლოფ", "ფოლგ", "ერთჯერად", "bag", "foil", "package"]),
    ("მშრალი პროდუქტები", ["ბრინჯ", "მაკარონ", "ფქვილ", "შაქარ", "მარილ", "ბურღულ", "ლობიო", "ცომ", "ზეთ", "რძე", "flour",
                           "sugar", "rice", "pasta", "salt", "oil"]),
    ("სურსათი", ["პური", "ყველ", "ხორც", "თევზ", "კვერცხ", "კარაქ", "მაიონეზ", "კეტჩუპ", "ძეხვ", "იოგურტ", "ხაჭო",
                 "bread", "cheese", "meat", "egg", "butter", "sausage"]),
]


def classify_product_category(name: str) -> Optional[str]:
    text = (name or "").casefold()
    if not text.strip():
        return None
    for category, stems in _SMART_CATEGORY_RULES:
        if any(stem in text for stem in stems):
            return category
    normalized_text = _normalize_category_name(text)
    for category, variants in CATEGORY_MAP.items():
        if any(
            _normalize_category_name(variant) in normalized_text
            for variant in variants
            if _normalize_category_name(variant)
        ):
            return category
    return None


async def ensure_category_name(name: str) -> str:
    """Return the stored name of the category, creating it if it does not exist yet."""
    name = name.strip()
    if getattr(db, "categories", None) is None:
        return name
    canonical = CATEGORY_ALIASES.get(name.casefold())
    candidates = [name]
    if canonical:
        english = next((n for n in DEFAULT_CATEGORY_NAMES if n.casefold() == canonical), None)
        candidates = [english, name] if english else [name]
    for candidate in candidates:
        found = await db.categories.find_one(
            {"name": {"$regex": f"^{re.escape(candidate)}$", "$options": "i"}}, {"_id": 0, "name": 1},
        )
        if found:
            return found["name"]
    await db.categories.insert_one({"id": str(uuid.uuid4()), "name": candidates[0]})
    return candidates[0]


async def smart_category_for(name: str, current: Optional[str], business_id: Optional[str] = None) -> str:
    """Prefer explicit category, otherwise resolve from the product name within the business scope."""
    category, _ = await smart_category_details_for(name, current, business_id)
    return category


async def resolve_product_category(
    name: str, business_id: Optional[str], current: Optional[str] = None,
) -> tuple[str, str]:
    """Shared resolver for manual create/edit and imports; always returns (category, category_id)."""
    category, category_id = await smart_category_details_for(name, current, business_id=business_id)
    if not category_id:
        raise HTTPException(500, "პროდუქტის კატეგორიის შენახვა ვერ მოხერხდა.")
    return category, category_id


async def smart_category_details_for(
    name: str, current: Optional[str], business_id: Optional[str] = None,
) -> tuple[str, Optional[str]]:
    """Resolve the category label and, when business-scoped, its stored category id."""
    explicit = (current or "").strip()
    if explicit and explicit.casefold() not in ("other", "სხვა"):
        category_collection = getattr(db, "categories", None)
        if business_id and category_collection is not None:
            canonical = _category_group_name(explicit) or explicit
            variants = [str(value).strip() for value in CATEGORY_MAP.get(canonical, [canonical]) if str(value).strip()]
            variant_keys = {_normalize_category_name(value) for value in variants + [explicit] if value}
            existing = await category_collection.find(
                {"business_id": business_id}, {"_id": 0, "id": 1, "name": 1},
            ).to_list(500)
            match = next((
                item for item in existing
                if item.get("id") and _normalize_category_name(item.get("name", "")) in variant_keys
            ), None)
            if match:
                return str(match["name"]), match.get("id")
            category_id = str(uuid.uuid4())
            await category_collection.insert_one({
                "id": category_id, "name": canonical, "business_id": business_id,
            })
            return canonical, category_id
        return _category_group_name(explicit) or explicit, None
    detected = classify_product_category(name) or _category_group_name(name) or explicit or "Other"
    if business_id:
        return await _resolve_business_category(detected, business_id=business_id)
    return await ensure_category_name(detected), None

# ---------- commission billing & financials ----------
ISSUER_DEFAULTS = {"issuer_name": "Distro Logistics LLC", "issuer_tax_id": "400123456",
                   "issuer_iban": "GE00DL0000000000001234"}


def _month_bounds(year, month):
    # Month edges are midnight in platform time, expressed in UTC to match stored ISO timestamps.
    start = datetime(year, month, 1, tzinfo=moneylib.PLATFORM_TZ).astimezone(timezone.utc)
    nxt = (datetime(year + 1, 1, 1, tzinfo=moneylib.PLATFORM_TZ) if month == 12
           else datetime(year, month + 1, 1, tzinfo=moneylib.PLATFORM_TZ)).astimezone(timezone.utc)
    georgian_months = (
        "იანვარი", "თებერვალი", "მარტი", "აპრილი", "მაისი", "ივნისი",
        "ივლისი", "აგვისტო", "სექტემბერი", "ოქტომბერი", "ნოემბერი", "დეკემბერი",
    )
    return start, nxt, f"{georgian_months[month - 1]} {year}", f"{year:04d}-{month:02d}"


def _prev_month(dt):
    return (dt.year - 1, 12) if dt.month == 1 else (dt.year, dt.month - 1)


def _fmt(dt):
    georgian_months = (
        "იანვარი", "თებერვალი", "მარტი", "აპრილი", "მაისი", "ივნისი",
        "ივლისი", "აგვისტო", "სექტემბერი", "ოქტომბერი", "ნოემბერი", "დეკემბერი",
    )
    return f"{dt.day} {georgian_months[dt.month - 1]} {dt.year}"


def order_commission(o):
    return moneylib.as_json(moneylib.order_fee(o))


def effective_status(inv):
    if inv.get("status") == "paid":
        return "paid"
    try:
        due = datetime.fromisoformat(inv["due_date"])
    except Exception:
        return inv.get("status", "pending")
    return "overdue" if datetime.now(timezone.utc) > due else "pending"


def billing_should_freeze(invs: list, settings: dict) -> bool:
    """Block rule: with no thresholds set, any overdue invoice blocks; otherwise
    block when overdue balance exceeds the limit or the oldest overdue invoice
    is older than the allowed number of days."""
    now = datetime.now(timezone.utc)
    overdue = [i for i in invs if effective_status(i) == "overdue"]
    if not overdue:
        return False
    limit = moneylib.amount_or_zero(settings.get("billing_overdue_limit"))
    grace_days = int(settings.get("billing_overdue_days") or 0)
    if limit <= 0 and grace_days <= 0:
        return True
    if limit > 0 and moneylib.total_sum(i["amount"] for i in overdue) > limit:
        return True
    if grace_days > 0:
        for inv in overdue:
            try:
                days = (now - datetime.fromisoformat(inv["due_date"])).days
            except (KeyError, ValueError, TypeError):
                continue
            if days >= grace_days:
                return True
    return False


async def recompute_freeze(supplier_id):
    invs = await db.invoices.find({"supplier_id": supplier_id}, {"_id": 0}).to_list(500)
    frozen = billing_should_freeze(invs, await get_settings())
    await db.users.update_one({"id": supplier_id}, {"$set": {"billing_frozen": frozen}})
    return frozen


def invoice_payment_link(invoice_id: str) -> str:
    base = (os.environ.get("INVOICE_PAYMENT_LINK_BASE", "").strip()
            or f"{os.environ.get('APP_BASE_URL', '').strip().rstrip('/')}/pay")
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}invoice_id={invoice_id}"


async def do_generate_invoices(period=None):
    settings = await get_settings()
    issuer = {k: settings.get(k, ISSUER_DEFAULTS[k]) for k in ISSUER_DEFAULTS}
    now = datetime.now(timezone.utc)
    if period:
        y, m = int(period[:4]), int(period[5:7])
    else:
        y, m = _prev_month(now.astimezone(moneylib.PLATFORM_TZ))
    start, nxt, label, period_str = _month_bounds(y, m)
    issue_dt = now
    due_dt = issue_dt + timedelta(days=5)
    created = []
    email_jobs = []
    suppliers = await db.users.find({"role": "supplier"}, {"_id": 0, "password_hash": 0}).to_list(1000)
    already_invoiced = {
        i["supplier_id"] async for i in db.invoices.find({"period": period_str}, {"_id": 0, "supplier_id": 1})
    }
    for sup in suppliers:
        if sup["id"] in already_invoiced:
            continue
        orders = await db.orders.find({"supplier_id": sup["id"], "status": "Delivered",
            "external_order": {"$ne": True},
            "delivered_at": {"$gte": start.isoformat(), "$lt": nxt.isoformat()}}, {"_id": 0}).to_list(5000)
        orders = [o for o in orders if not o.get("invoice_id") and not o.get("paid_at_checkout")]
        if not orders:
            continue
        line_items, amount, sales = [], moneylib.ZERO, moneylib.ZERO
        for o in orders:
            c = moneylib.order_fee(o)
            order_total = moneylib.q(o.get("total"))
            amount += c
            sales += order_total
            line_items.append({"order_no": o["order_no"], "date": (o.get("delivered_at") or "")[:10],
                               "order_total": moneylib.as_json(order_total), "commission": moneylib.as_json(c)})
        iid = str(uuid.uuid4())
        inv = {"id": iid, "invoice_no": f"INV-{period_str.replace('-', '')}-{iid[:4].upper()}",
               "supplier_id": sup["id"], "supplier_name": sup.get("business_name", ""),
               "supplier_tax_id": sup.get("identification_number", ""), "supplier_email": sup.get("email", ""),
               "period": period_str, "period_label": label,
               "line_items": line_items, "order_count": len(orders),
               "total_sales": moneylib.as_json(sales), "amount": moneylib.as_json(amount), "currency": "GEL",
               "status": "pending", "issue_date": issue_dt.isoformat(), "issue_label": _fmt(issue_dt),
               "payment_link": invoice_payment_link(iid), "payment_reference": iid,
               "payment_reference_normalized": iid.casefold(),
               "due_date": due_dt.isoformat(), "due_label": _fmt(due_dt), "paid_at": None,
               **issuer, "created_at": now_iso()}
        await db.invoices.insert_one(_encrypt_sensitive_fields(inv))
        await db.orders.update_many({"id": {"$in": [o["id"] for o in orders]}}, {"$set": {"invoice_id": iid}})
        await notify(
            sup["id"],
            f"გამოიწერა საკომისიოს ახალი ინვოისი №{inv['invoice_no']} ({label}) — "
            f"₾{inv['amount']:.2f}; გადახდის ვადა: {inv['due_label']}.",
            "billing", invoice_id=iid,
        )
        if sup.get("email"):
            email_jobs.append(try_send_email(to=sup["email"], subject=f"Your Distro Logistics commission invoice {inv['invoice_no']}",
                                             html=invoice_email_html(inv)))
        created.append(inv["invoice_no"])
    await _gather_limited(email_jobs)
    return created


async def _gather_limited(coroutines, limit: int = 10):
    """Run coroutines concurrently with a cap; one failure never blocks the rest."""
    semaphore = asyncio.Semaphore(limit)

    async def run(coro):
        async with semaphore:
            try:
                return await coro
            except Exception:
                logger.exception("Background job failed")
    return await asyncio.gather(*(run(c) for c in coroutines))


async def do_billing_check():
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    settings = await get_settings()
    lead_days = int(settings.get("billing_reminder_days") or 2)
    invs = await db.invoices.find({"status": {"$ne": "paid"}}, {"_id": 0}).to_list(2000)
    reminded = []
    for inv in invs:
        sup = None
        status = effective_status(inv)
        if status == "overdue":
            if inv.get("reminded_on") == today:
                continue
            sup = await db.users.find_one({"id": inv["supplier_id"]}, {"_id": 0})
            if sup and sup.get("email"):
                email_invoice = _decrypt_sensitive_fields(inv)
                await try_send_email(to=sup["email"], subject=f"Overdue: commission invoice {inv['invoice_no']}",
                                     html=reminder_email_html(email_invoice))
            await db.invoices.update_one({"id": inv["id"]}, {"$set": {"reminded_on": today}})
            await notify(
                inv["supplier_id"],
                f"ინვოისი №{inv['invoice_no']} ვადაგადაცილებულია. გადახდამდე ახალი შეკვეთების მიღება შეიძლება შეჩერდეს.",
                "billing", invoice_id=inv["id"],
            )
            reminded.append(inv["invoice_no"])
        elif status == "pending" and not inv.get("due_soon_reminded"):
            try:
                due = datetime.fromisoformat(inv["due_date"])
            except (KeyError, ValueError, TypeError):
                continue
            if due - now > timedelta(days=lead_days):
                continue
            sup = await db.users.find_one({"id": inv["supplier_id"]}, {"_id": 0})
            if sup and sup.get("email"):
                email_invoice = _decrypt_sensitive_fields(inv)
                await try_send_email(to=sup["email"], subject=f"Payment due soon: invoice {inv['invoice_no']}",
                                     html=invoice_email_html(email_invoice))
            await db.invoices.update_one({"id": inv["id"]}, {"$set": {"due_soon_reminded": True}})
            await notify(
                inv["supplier_id"],
                f"ინვოისის №{inv['invoice_no']} გადახდის ვადა უახლოვდება: {inv['due_label']} (₾{inv['amount']:.2f}).",
                "billing", invoice_id=inv["id"],
            )
            reminded.append(inv["invoice_no"])
    all_sups = await db.users.find({"role": "supplier"}, {"_id": 0, "id": 1}).to_list(1000)
    for sup in all_sups:
        await recompute_freeze(sup["id"])
    return reminded


async def billing_scheduler_loop():
    """Daily in-process scheduler: invoices on the 1st of the month, reminders and blocking every day."""
    while True:
        try:
            now = datetime.now(timezone.utc)
            if now.day == 1:
                await do_generate_invoices()
            await do_billing_check()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Scheduled billing run failed")
        await asyncio.sleep(6 * 3600)


@api.get("/invoices")
async def list_invoices(
    response: Response, status: Optional[str] = None, supplier_id: Optional[str] = None,
    limit: Optional[int] = None, offset: int = 0, user: dict = Depends(get_current_user),
):
    if user["role"] == "supplier":
        if user.get("supplier_access_role") == "branch_manager":
            raise HTTPException(403, "Platform commission invoices are available to distributor owners only.")
        q = {"supplier_id": supplier_owner_id(user)}
    elif user["role"] == "admin":
        q = {"supplier_id": supplier_id} if supplier_id else {}
    else:
        raise HTTPException(403, "Not allowed")
    now_iso_value = datetime.now(timezone.utc).isoformat()
    if status == "paid":
        q["status"] = "paid"
    elif status == "unpaid":
        q["status"] = {"$ne": "paid"}
    elif status == "overdue":
        q.update({"status": {"$ne": "paid"}, "due_date": {"$lt": now_iso_value}})
    elif status == "pending":
        q.update({"status": {"$ne": "paid"}, "due_date": {"$gte": now_iso_value}})
    size, skip = _page(limit, offset, 2000)
    response.headers["X-Total-Count"] = str(await db.invoices.count_documents(q))
    invs = await db.invoices.find(q, {"_id": 0}).sort("created_at", -1).skip(skip).limit(size).to_list(size)
    for i in invs:
        i.update(_decrypt_sensitive_fields(i))
        i["effective_status"] = effective_status(i)
        i.setdefault("payment_link", invoice_payment_link(i["id"]))
    return invs


async def settle_invoice_payment(
    inv: dict, amount: Optional[float], reference: str,
    transaction_id: Optional[str] = None, currency: Optional[str] = None,
) -> dict:
    """Mark an invoice paid (idempotent); returns the stored invoice."""
    if inv.get("status") == "paid":
        return inv
    fields = {
        "status": "paid", "paid_at": now_iso(), "paid_via": "bank_webhook",
        "payment_reference": reference or inv.get("payment_reference", ""),
        "paid_amount": amount if amount is not None else inv.get("amount"),
    }
    if transaction_id:
        fields["bank_transaction_id"] = transaction_id
    if currency:
        fields["paid_currency"] = currency
    result = await db.invoices.update_one(
        {"id": inv["id"], "status": {"$ne": "paid"}},
        {"$set": fields},
    )
    if result.modified_count:
        await recompute_freeze(inv["supplier_id"])
        await notify(
            inv["supplier_id"], f"ინვოისი №{inv['invoice_no']} წარმატებით გადახდილია. გმადლობთ!",
            "billing", invoice_id=inv["id"],
            notification_id=f"invoice-bank-{transaction_id}" if transaction_id else None,
        )
    return await db.invoices.find_one({"id": inv["id"]}, {"_id": 0})


def enforce_webhook_ip(request: Request) -> None:
    client_info = getattr(request, "client", None)
    host = client_info.host if client_info else None
    allowlist = os.environ.get("WEBHOOK_ALLOWED_IPS", "").strip()
    if os.environ.get("APP_ENV", "").strip().lower() == "production" and not allowlist:
        raise HTTPException(503, "Webhook IP allowlist is not configured.")
    if not safeguards.ip_allowed(host, allowlist):
        logger.warning("Webhook rejected: source address not in WEBHOOK_ALLOWED_IPS")
        raise HTTPException(403, "Source address is not allowed.")


async def deduplicated_webhook(source: str, event_id, raw_body: bytes, handler):
    """Run handler once per provider event; returns None for a replay. The claim is released on failure so the provider can retry."""
    events = getattr(db, "webhook_events", None)
    key = safeguards.webhook_event_key(source, event_id, raw_body)
    if not await safeguards.claim_webhook_event(events, key):
        return None
    try:
        return await handler()
    except BaseException:
        await safeguards.release_webhook_event(events, key)
        raise


@api.post("/invoices/webhook")
async def invoice_payment_webhook(request: Request):
    enforce_webhook_ip(request)
    secret = os.environ.get("INVOICE_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(503, "Invoice webhook is not configured.")
    raw_body = await request.body()
    signature = request.headers.get("X-Signature", "").strip().removeprefix("sha256=")
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(signature, expected):
        raise HTTPException(401, "Invalid webhook signature.")
    try:
        payload = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(400, "Invalid webhook payload.")
    if not isinstance(payload, dict):
        raise HTTPException(400, "Invalid webhook payload.")
    invoice_id = payload.get("invoice_id")
    if not isinstance(invoice_id, str) or not invoice_id:
        raise HTTPException(400, "invoice_id is required.")
    inv = await db.invoices.find_one({"id": invoice_id}, {"_id": 0})
    if not inv:
        raise HTTPException(404, "Invoice not found.")
    if str(payload.get("status", "")).strip().lower() not in {"success", "succeeded", "paid", "completed"}:
        return {"ok": True, "invoice_id": invoice_id, "status": inv.get("status"), "updated": False}
    if payload.get("amount") is None:
        raise HTTPException(400, "A payment amount is required.")
    try:
        amount = moneylib.q(payload["amount"])
        invoice_amount = moneylib.q(inv.get("amount"))
    except moneylib.MoneyError:
        raise HTTPException(400, "Invalid amount.")
    currency = str(payload.get("currency") or "").strip().upper()
    invoice_currency = str(inv.get("currency") or "GEL").strip().upper()
    if currency != invoice_currency:
        raise HTTPException(409, "Payment currency does not match invoice currency.")
    if amount != invoice_amount:
        raise HTTPException(409, "Paid amount does not exactly match the invoice amount.")
    amount = moneylib.as_json(amount)

    async def settle():
        updated = await settle_invoice_payment(
            inv, amount, str(payload.get("reference") or payload.get("transaction_id") or ""),
            transaction_id=str(payload.get("transaction_id") or "") or None, currency=currency,
        )
        return {"ok": True, "invoice_id": invoice_id, "status": updated["status"],
                "updated": inv.get("status") != "paid"}

    event_id = payload.get("event_id") or payload.get("transaction_id")
    result = await deduplicated_webhook(f"invoice:{invoice_id}", event_id, raw_body, settle)
    if result is None:  # replay of an event that was already processed
        return {"ok": True, "invoice_id": invoice_id, "status": inv.get("status"), "updated": False, "duplicate": True}
    return result


@api.post("/v1/invoices/bank-webhook")
async def bank_invoice_payment_webhook(request: Request):
    enforce_webhook_ip(request)
    secret = os.environ.get("BANK_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise HTTPException(503, "Bank invoice webhook is not configured.")
    raw_body = await request.body()
    signature = request.headers.get("X-Signature", "").strip().removeprefix("sha256=")
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(signature, expected):
        raise HTTPException(401, "Invalid webhook signature.")
    try:
        payload = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(400, "Invalid bank callback payload.")
    if not isinstance(payload, dict):
        raise HTTPException(400, "Invalid bank callback payload.")

    raw_transaction_id = payload.get("transaction_id") or payload.get("transactionId") or payload.get("id")
    if raw_transaction_id is None or isinstance(raw_transaction_id, bool):
        raise HTTPException(400, "transaction_id is required.")
    transaction_id = str(raw_transaction_id).strip()
    if not transaction_id or len(transaction_id) > 200:
        raise HTTPException(400, "Invalid transaction_id.")

    raw_reference = payload.get("reference") or payload.get("invoice_reference") or payload.get("description")
    if not isinstance(raw_reference, str) or not raw_reference.strip():
        raise HTTPException(400, "Invoice reference is required.")
    reference = raw_reference.strip()
    normalized_reference = reference.casefold()
    invoice = await db.invoices.find_one({"payment_reference_normalized": normalized_reference}, {"_id": 0})
    if not invoice:
        raise HTTPException(404, "Invoice not found for payment reference.")

    currency = str(payload.get("currency") or "").strip().upper()
    invoice_currency = str(invoice.get("currency") or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency) or currency != invoice_currency:
        raise HTTPException(409, "Payment currency does not match invoice currency.")
    try:
        amount = moneylib.q(payload.get("amount"))
        invoice_amount = moneylib.q(invoice.get("amount"))
    except moneylib.MoneyError:
        raise HTTPException(400, "A valid payment amount is required.")
    if amount <= 0 or amount != invoice_amount:
        raise HTTPException(409, "Payment amount does not exactly match invoice amount.")

    provider_status = str(payload.get("status") or "").strip().casefold()
    if provider_status not in {"success", "succeeded", "paid", "completed"}:
        return {"ok": True, "invoice_id": invoice["id"], "status": invoice.get("status"), "updated": False}

    fingerprint_data = {
        "transaction_id": transaction_id, "reference": normalized_reference,
        "amount": str(amount), "currency": currency,
    }
    payload_hash = hashlib.sha256(json.dumps(fingerprint_data, sort_keys=True).encode("utf-8")).hexdigest()
    transactions = db.invoice_bank_transactions
    now = datetime.now(timezone.utc)
    lease_until = now + timedelta(seconds=60)
    record = {
        "transaction_id": transaction_id, "payload_hash": payload_hash,
        "invoice_id": invoice["id"], "reference": reference,
        "amount": moneylib.as_json(amount), "currency": currency,
        "state": "processing", "lease_until": lease_until,
        "created_at": now, "updated_at": now,
    }
    try:
        await transactions.insert_one(record)
    except DuplicateKeyError:
        previous = await transactions.find_one({"transaction_id": transaction_id}, {"_id": 0})
        if not previous or previous.get("payload_hash") != payload_hash:
            raise HTTPException(409, "transaction_id was already used with different payment data.")
        if previous.get("state") == "applied":
            return {"ok": True, "invoice_id": invoice["id"], "status": "paid",
                    "updated": False, "duplicate": True, "transaction_id": transaction_id}
        if previous.get("state") == "rejected":
            raise HTTPException(409, "This transaction was already rejected.")
        if previous.get("lease_until") and previous["lease_until"] > now:
            return {"ok": True, "invoice_id": invoice["id"], "status": "processing",
                    "updated": False, "duplicate": True, "transaction_id": transaction_id}
        claim = await transactions.update_one(
            {"transaction_id": transaction_id, "payload_hash": payload_hash,
             "state": previous.get("state"), "lease_until": previous.get("lease_until")},
            {"$set": {"state": "processing", "lease_until": lease_until, "updated_at": now}},
        )
        if not claim.modified_count:
            return {"ok": True, "invoice_id": invoice["id"], "status": "processing",
                    "updated": False, "duplicate": True, "transaction_id": transaction_id}

    try:
        if invoice.get("status") == "paid":
            if invoice.get("bank_transaction_id") != transaction_id:
                await transactions.update_one({"transaction_id": transaction_id}, {"$set": {
                    "state": "rejected", "updated_at": datetime.now(timezone.utc),
                }})
                raise HTTPException(409, "Invoice has already been settled by another payment.")
        else:
            await settle_invoice_payment(
                invoice, moneylib.as_json(amount), invoice.get("payment_reference") or reference,
                transaction_id=transaction_id, currency=currency,
            )

        settled = await db.invoices.find_one({"id": invoice["id"]}, {"_id": 0})
        if settled.get("bank_transaction_id") != transaction_id:
            await transactions.update_one({"transaction_id": transaction_id}, {"$set": {
                "state": "rejected", "updated_at": datetime.now(timezone.utc),
            }})
            raise HTTPException(409, "Invoice has already been settled by another payment.")
        await transactions.update_one({"transaction_id": transaction_id}, {"$set": {
            "state": "applied", "applied_at": datetime.now(timezone.utc),
            "lease_until": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc),
        }})
        await log_financial_event(
            "invoice_bank_payment_applied", {"id": "system", "name": "Bank webhook"},
            "invoice", invoice["id"], before={"status": invoice.get("status")},
            after={"status": "paid", "transaction_id": transaction_id,
                   "reference": reference, "amount": moneylib.as_json(amount), "currency": currency},
            status="success",
        )
        return {"ok": True, "invoice_id": invoice["id"], "status": "paid",
                "updated": invoice.get("status") != "paid", "transaction_id": transaction_id}
    except HTTPException as error:
        if error.status_code >= 500:
            await transactions.update_one({"transaction_id": transaction_id, "state": "processing"}, {"$set": {
                "state": "retryable", "lease_until": datetime.now(timezone.utc),
                "last_error": error.detail, "updated_at": datetime.now(timezone.utc),
            }})
        raise
    except Exception as error:
        await transactions.update_one({"transaction_id": transaction_id, "state": "processing"}, {"$set": {
            "state": "retryable", "lease_until": datetime.now(timezone.utc),
            "last_error": type(error).__name__, "updated_at": datetime.now(timezone.utc),
        }})
        logger.exception("Bank invoice payment processing failed")
        raise HTTPException(503, "Payment processing failed; the bank may retry.") from error


@app.post("/api/v1/payments/bank-webhook")
async def bank_payment_webhook(request: Request):
    enforce_webhook_ip(request)
    configured_secret = os.environ.get("BANK_WEBHOOK_SECRET", "").strip()
    if not configured_secret:
        raise HTTPException(503, "Bank webhook is not configured.")
    raw_body = await request.body()
    signature = request.headers.get("X-Signature", "").strip().removeprefix("sha256=")
    expected_signature = hmac.new(configured_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    signature_ok = bool(signature) and hmac.compare_digest(signature, expected_signature)
    if not signature_ok:
        raise HTTPException(401, "Invalid webhook signature.")
    try:
        payload = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(400, "Invalid webhook payload.")
    if not isinstance(payload, dict):
        raise HTTPException(400, "Invalid webhook payload.")
    raw_reference = str(payload.get("description") or payload.get("reference") or payload.get("transaction_text") or "").strip()
    match = PAYMENT_REFERENCE_RE.search(raw_reference)
    if not match:
        raise HTTPException(400, "Payment reference not found.")
    reference = match.group(0).upper()
    try:
        amount = moneylib.q(payload.get("amount"))
    except moneylib.MoneyError:
        raise HTTPException(400, "Invalid amount.")
    order = await db.orders.find_one({"payment_reference": reference}, {"_id": 0})
    if not order:
        raise HTTPException(404, "Order not found for payment reference.")
    if amount != moneylib.q(order.get("total")):
        raise HTTPException(409, "Transferred amount does not match order total.")
    if order_payment_fields(order)["paymentStatus"] == "PAID":
        return {"ok": True, "updated": False, "order_id": order["id"]}

    async def settle():
        await _mark_order_bank_paid(order, reference, "bank-webhook")
        return {"ok": True, "updated": True, "order_id": order["id"]}

    event_id = payload.get("transaction_id") or payload.get("id") or payload.get("event_id")
    result = await deduplicated_webhook(f"bank:{reference}", event_id, raw_body, settle)
    return result or {"ok": True, "updated": False, "order_id": order["id"], "duplicate": True}


@api.get("/invoices/{iid}/pdf")
async def invoice_pdf(iid: str, user: dict = Depends(get_current_user)):
    inv = await db.invoices.find_one({"id": iid}, {"_id": 0})
    if not inv:
        raise HTTPException(404, "Invoice not found")
    if user["role"] == "retailer":
        raise HTTPException(403, "Not allowed")
    if user["role"] == "supplier" and (
        user.get("supplier_access_role") == "branch_manager"
        or inv["supplier_id"] != supplier_owner_id(user)
    ):
        raise HTTPException(404, "Invoice not found")
    pdf = build_invoice_pdf(_decrypt_sensitive_fields(inv))
    return StreamingResponse(io.BytesIO(pdf), media_type="application/pdf",
                             headers={"Content-Disposition": f'inline; filename="{inv["invoice_no"]}.pdf"'})


@api.put("/admin/invoices/{iid}/paid")
async def mark_invoice_paid(iid: str, user: dict = Depends(require_role("admin"))):
    inv = await db.invoices.find_one({"id": iid}, {"_id": 0})
    if not inv:
        raise HTTPException(404, "Invoice not found")
    if inv.get("status") == "paid":
        raise HTTPException(409, "Invoice is already marked as paid.")
    await log_financial_event("invoice_marked_paid", user, "invoice", iid,
                              before={"status": inv.get("status")}, after={"status": "paid"})
    await db.invoices.update_one({"id": iid}, {"$set": {"status": "paid", "paid_at": now_iso()}})
    await recompute_freeze(inv["supplier_id"])
    await notify(
        inv["supplier_id"], f"ინვოისი №{inv['invoice_no']} გადახდილად მოინიშნა. გმადლობთ!",
        "billing", invoice_id=iid,
    )
    updated = await db.invoices.find_one({"id": iid}, {"_id": 0})
    updated["effective_status"] = effective_status(updated)
    return updated


@api.post("/admin/invoices/{iid}/remind")
async def remind_invoice(iid: str, user: dict = Depends(require_role("admin"))):
    inv = await db.invoices.find_one({"id": iid}, {"_id": 0})
    if not inv:
        raise HTTPException(404, "Invoice not found")
    sup = await db.users.find_one({"id": inv["supplier_id"]}, {"_id": 0})
    sent = False
    if sup and sup.get("email"):
        sent = await try_send_email(to=sup["email"], subject=f"Reminder: commission invoice {inv['invoice_no']}",
                                    html=reminder_email_html(inv))
    await notify(
        inv["supplier_id"], f"ინვოისის №{inv['invoice_no']} გადახდის შეხსენება გამოგეგზავნათ.",
        "billing", invoice_id=iid,
    )
    return {"sent": sent, "email": sup.get("email") if sup else ""}


@api.post("/admin/invoices/generate")
async def admin_generate_invoices(
    background: BackgroundTasks, run_in_background: bool = False,
    user: dict = Depends(require_role("admin")),
):
    if run_in_background:
        background.add_task(do_generate_invoices)
        return {"accepted": True, "created": [], "count": 0}
    created = await do_generate_invoices()
    return {"created": created, "count": len(created)}


@api.get("/admin/financials")
async def admin_financials(user: dict = Depends(require_role("admin"))):
    now = datetime.now(timezone.utc)
    platform_now = now.astimezone(moneylib.PLATFORM_TZ)
    cs, cn, clabel, _ = _month_bounds(platform_now.year, platform_now.month)
    window = {"$gte": cs.isoformat(), "$lt": cn.isoformat()}
    commission_fields = {"_id": 0, "supplier_id": 1, "total": 1, "commission_amount": 1, "service_fee": 1,
                         "invoice_id": 1, "paid_at_checkout": 1}
    # Three batched queries instead of two queries per supplier.
    suppliers, invs_all, cur_all, chk_all = await asyncio.gather(
        db.users.find({"role": "supplier"}, {"_id": 0, "password_hash": 0}).to_list(1000),
        db.invoices.find({}, {"_id": 0, "line_items": 0}).sort("created_at", -1).to_list(3000),
        db.orders.find({"status": "Delivered", "external_order": {"$ne": True}, "delivered_at": window},
                       commission_fields).to_list(20000),
        db.orders.find({"external_order": {"$ne": True}, "paid_at_checkout": True, "created_at": window},
                       commission_fields).to_list(20000),
    )
    invs_by_supplier, cur_by_supplier, chk_by_supplier = {}, {}, {}
    for inv in invs_all:
        invs_by_supplier.setdefault(inv["supplier_id"], []).append(inv)
    for order in cur_all:
        if not order.get("invoice_id") and not order.get("paid_at_checkout"):
            cur_by_supplier.setdefault(order.get("supplier_id"), []).append(order)
    for order in chk_all:
        chk_by_supplier.setdefault(order.get("supplier_id"), []).append(order)
    rows = []
    tot_outstanding = tot_accrued = tot_collected = moneylib.ZERO
    for sup in suppliers:
        s_invs = invs_by_supplier.get(sup["id"], [])
        for i in s_invs:
            i["effective_status"] = effective_status(i)
        cur = cur_by_supplier.get(sup["id"], [])
        accrued = moneylib.total_sum(moneylib.order_fee(o) for o in cur)
        month_sales = moneylib.total_sum(o.get("total") for o in cur)
        checkout_collected = moneylib.total_sum(moneylib.order_fee(o) for o in chk_by_supplier.get(sup["id"], []))
        outstanding = moneylib.total_sum(i["amount"] for i in s_invs if i["effective_status"] != "paid")
        collected = moneylib.total_sum(i["amount"] for i in s_invs if i["effective_status"] == "paid") + checkout_collected
        tot_outstanding += outstanding
        tot_accrued += accrued
        tot_collected += collected
        rows.append({"supplier_id": sup["id"], "supplier_name": sup.get("business_name", ""),
                     "email": sup.get("email", ""), "tax_id": sup.get("identification_number", ""),
                     "frozen": bool(sup.get("billing_frozen")), "month_sales": moneylib.as_json(month_sales),
                     "accrued_commission": moneylib.as_json(accrued),
                     "checkout_collected": moneylib.as_json(checkout_collected),
                     "outstanding": moneylib.as_json(outstanding), "collected": moneylib.as_json(collected),
                     "invoices": s_invs})
    return {"period_label": clabel, "timezone": "Asia/Tbilisi", "suppliers": rows,
            "totals": {"outstanding": moneylib.as_json(tot_outstanding), "accrued": moneylib.as_json(tot_accrued),
                       "collected": moneylib.as_json(tot_collected)}}


@api.get("/admin/financials/audit-log")
async def admin_financial_audit_log(
    status: str = Query("all", pattern="^(all|success|pending|error)$"),
    page: int = Query(1, ge=1, le=1000),
    page_size: int = Query(25, ge=1, le=100),
    user: dict = Depends(require_role("admin")),
):
    legacy_error_actions = ["branch_delete_blocked", "warehouse_delete_blocked"]
    legacy_pending_actions = ["bank_payment_pending"]
    if status == "success":
        query = {"$or": [
            {"status": "success"},
            {"status": {"$exists": False}, "action": {"$nin": legacy_error_actions + legacy_pending_actions}},
        ]}
    elif status == "pending":
        query = {"$or": [
            {"status": "pending"},
            {"status": {"$exists": False}, "action": {"$in": legacy_pending_actions}},
        ]}
    elif status == "error":
        query = {"$or": [
            {"status": "error"},
            {"status": {"$exists": False}, "action": {"$in": legacy_error_actions}},
        ]}
    else:
        query = {}
    audit_query = {"$and": [{"entity": {"$ne": "bank_payment"}}, query]} if query else {
        "entity": {"$ne": "bank_payment"}
    }
    payment_statuses = {
        "success": ["Succeeded", "success", "settled"],
        "pending": ["Pending", "Processing", "pending"],
        "error": ["Failed", "Expired", "Returned", "PartialReturned", "error", "failed"],
    }
    payment_query = {"status": {"$in": payment_statuses[status]}} if status in payment_statuses else {}

    audit_projection = {
        "_id": 0, "id": 1, "action": 1, "entity": 1, "entity_id": 1,
        "actor_id": 1, "actor_name": 1, "at": 1, "status": 1,
        "amount": 1, "currency": 1, "gateway": 1,
    }
    payment_projection = {
        "_id": 0, "id": 1, "retailer_id": 1, "amount": 1, "currency": 1,
        "gateway": 1, "status": 1, "created_at": 1, "updated_at": 1,
    }
    total = await financial_audit_logs.count_documents(audit_query) + await db.bank_payments.count_documents(payment_query)
    candidate_count = page * page_size
    audit_events, payment_rows = await asyncio.gather(
        financial_audit_logs.find(audit_query, audit_projection).sort("at", -1).limit(candidate_count).to_list(candidate_count),
        db.bank_payments.find(payment_query, payment_projection).sort("updated_at", -1).limit(candidate_count).to_list(candidate_count),
    )
    for event in audit_events:
        if not event.get("status"):
            action = event.get("action", "").lower()
            event["status"] = (
                "error" if action in legacy_error_actions
                else "pending" if action in legacy_pending_actions
                else "success"
            )
    events = audit_events + [{
        "id": f"gateway:{payment.get('id', '')}", "action": "bank_payment_checkout",
        "entity": "bank_payment", "entity_id": payment.get("id"),
        "actor_id": payment.get("retailer_id"), "at": payment.get("updated_at") or payment.get("created_at"),
        "status": "success" if payment.get("status") in ("Succeeded", "success", "settled")
        else "pending" if payment.get("status") in ("Pending", "Processing", "pending") else "error",
        "amount": payment.get("amount"), "currency": payment.get("currency", "GEL"),
        "gateway": payment.get("gateway"),
    } for payment in payment_rows]
    events.sort(key=lambda event: event.get("at") or "", reverse=True)
    events = events[(page - 1) * page_size:page * page_size]
    return {"events": events, "total": total, "page": page, "page_size": page_size}


INVOICE_STATUS_KA = {"paid": "გადახდილი", "pending": "მოლოდინში", "overdue": "ვადაგადაცილებული"}


def _embed_logos(logo_rows):
    """Place each owner's logo (or a generated placeholder) in column A of its row."""
    from openpyxl.drawing.image import Image as XlImage
    cache = {}
    for sheet, row_no, owner_id, owner_name in logo_rows:
        if (owner_id, owner_name) not in cache:
            cache[(owner_id, owner_name)] = logo_bytes(owner_id, owner_name, size=48)
        img = XlImage(io.BytesIO(cache[(owner_id, owner_name)]))
        img.width = img.height = 32
        sheet.add_image(img, f"A{row_no}")
        sheet.row_dimensions[row_no].height = 28


@api.get("/export-financials")
@api.get("/admin/financials/export.xlsx")
async def export_financials_xlsx(status: Optional[str] = None, user: dict = Depends(require_role("admin"))):
    from openpyxl import Workbook
    from openpyxl.styles import Font
    if status and status not in ("all", "paid", "pending", "overdue", "unpaid"):
        raise HTTPException(400, "Invalid status filter")
    overview = await admin_financials(user)
    order_fields = {"_id": 0, "retailer_id": 1, "retailer_name": 1, "supplier_id": 1, "supplier_name": 1,
                    "total": 1, "amount_paid": 1, "paid_at_checkout": 1, "payment_status": 1,
                    "external_order": 1}
    delivered, store_names = await asyncio.gather(
        db.orders.find({"status": "Delivered", "external_order": {"$ne": True}}, order_fields).to_list(50000),
        db.users.find({"role": "retailer"}, {"_id": 0, "id": 1, "business_name": 1, "name": 1}).to_list(20000),
    )
    names = {u["id"]: u.get("business_name") or u.get("name", "") for u in store_names}

    logo_rows = []  # (sheet, row number, owner id, owner name) -> logo embedded after data is written
    wb = Workbook()
    summary = wb.active
    summary.title = "შეჯამება"
    summary.append(["ლოგო", "დისტრიბუტორი", "სას. კოდი", "ელ. ფოსტა", "თვის ბრუნვა (ლარი)", "დარიცხული საკომისიო (ლარი)",
                    "მიღებული შეკვეთისას (ლარი)", "გადასახდელი (ლარი)", "სულ გადახდილი (ლარი)", "დაბლოკილია"])
    for row in overview["suppliers"]:
        summary.append([
            "", row["supplier_name"], row["tax_id"], row["email"], row["month_sales"], row["accrued_commission"],
            row["checkout_collected"], row["outstanding"], row["collected"], "დიახ" if row["frozen"] else "არა",
        ])
        logo_rows.append((summary, summary.max_row, row["supplier_id"], row["supplier_name"]))
    totals = overview["totals"]
    summary.append([])
    summary.append(["", "სულ", "", "", "", totals["accrued"], "", totals["outstanding"], totals["collected"], ""])

    invoices = wb.create_sheet("ინვოისები")
    invoices.append(["ლოგო", "ინვოისის №", "დისტრიბუტორი", "სას. კოდი", "ელ. ფოსტა", "პერიოდი", "გამოწერის თარიღი",
                     "გადახდის ვადა", "თანხა (ლარი)", "სტატუსი", "გადახდის თარიღი", "შეკვეთები"])
    for row in overview["suppliers"]:
        for inv in row["invoices"]:
            eff = inv["effective_status"]
            if status == "unpaid" and eff == "paid":
                continue
            if status in ("paid", "pending", "overdue") and eff != status:
                continue
            invoices.append([
                "", inv.get("invoice_no", ""), inv.get("supplier_name", ""), inv.get("supplier_tax_id", ""),
                inv.get("supplier_email", ""), inv.get("period_label", ""), inv.get("issue_label", ""),
                inv.get("due_label", ""), moneylib.as_json(inv["amount"]), INVOICE_STATUS_KA.get(eff, eff),
                (inv.get("paid_at") or "")[:10], inv.get("order_count", 0),
            ])
            logo_rows.append((invoices, invoices.max_row, row["supplier_id"], inv.get("supplier_name", "")))

    balances = wb.create_sheet("ბალანსები")
    balances.append(["ლოგო", "მაღაზია", "დისტრიბუტორი", "ჩაბარებული შეკვეთები", "ბრუნვა (ლარი)", "გადახდილი (ლარი)",
                     "დავალიანება (ლარი)"])
    grouped = {}
    for order in delivered:
        key = (order.get("retailer_id"), order.get("supplier_id"))
        total, balance = order_payment_totals(order)
        entry = grouped.setdefault(key, {"store": names.get(order.get("retailer_id")) or order.get("retailer_name", ""),
                                         "store_id": order.get("retailer_id"),
                                         "supplier": order.get("supplier_name", ""), "orders": 0,
                                         "turnover": moneylib.ZERO, "balance": moneylib.ZERO})
        entry["orders"] += 1
        entry["turnover"] += moneylib.q(total)
        entry["balance"] += moneylib.q(balance)
    for entry in sorted(grouped.values(), key=lambda e: e["balance"], reverse=True):
        balances.append(["", entry["store"], entry["supplier"], entry["orders"], moneylib.as_json(entry["turnover"]),
                         moneylib.as_json(entry["turnover"] - entry["balance"]), moneylib.as_json(entry["balance"])])
        logo_rows.append((balances, balances.max_row, entry["store_id"] or "", entry["store"]))

    await asyncio.to_thread(_embed_logos, logo_rows)

    widths = {"შეჯამება": (10, 28, 16, 28, 20, 26, 26, 20, 22, 14),
              "ინვოისები": (10, 22, 28, 16, 28, 16, 18, 16, 14, 14, 18, 12),
              "ბალანსები": (10, 28, 28, 22, 16, 18, 20)}
    for sheet in wb.worksheets:
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        sheet.freeze_panes = "A2"
        for index, width in enumerate(widths[sheet.title]):
            sheet.column_dimensions[chr(65 + index)].width = width
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return StreamingResponse(
        buffer, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="financial-report-{status or "all"}.xlsx"'},
    )


FINANCE_STATUS_KA = {
    "paid": "გადახდილი", "unpaid": "გადაუხდელი",
    "partially_paid": "ნაწილობრივ გადახდილი", "overdue": "ვადაგადაცილებული",
}


@api.get("/finance/export.xlsx")
async def export_party_finance_xlsx(
    date_from: Optional[str] = None, date_to: Optional[str] = None,
    payment_status: Optional[str] = None, user: dict = Depends(get_current_user),
):
    """Accountant export of confirmed orders/invoices for the caller's own side, filtered by period."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    for value in (date_from, date_to):
        if value:
            try:
                date.fromisoformat(value)
            except ValueError:
                raise HTTPException(400, "თარიღის ფორმატი არასწორია (YYYY-MM-DD).")
    if payment_status and payment_status != "all" and payment_status not in FINANCE_STATUS_KA:
        raise HTTPException(400, "გადახდის სტატუსი არასწორია.")
    query = {"external_order": {"$ne": True}, "status": {"$in": ["Processing", "In Transit", "Delivered"]}}
    if user["role"] == "supplier":
        require_supplier_permission(user, "finance")
        query["supplier_id"] = supplier_owner_id(user)
        selected_warehouse_id = await supplier_warehouse_id(user)
        if selected_warehouse_id:
            query["warehouse_id"] = selected_warehouse_id
        sales_side = True
    elif user["role"] == "retailer":
        if not effective_store_permissions(user)["canViewFinancials"]:
            raise HTTPException(403, "Permission required: canViewFinancials")
        query["retailer_id"] = store_owner_id(user)
        assigned_branch_id = user.get("assigned_branch_id") if user.get("store_access_role") != "global_admin" else None
        if assigned_branch_id:
            query["branch_id"] = assigned_branch_id
        sales_side = False
    else:
        raise HTTPException(403, "Not allowed")

    orders = await db.orders.find(query, {"_id": 0}).sort("created_at", 1).to_list(20000)
    orders = [
        order for order in orders
        if (not date_from or (moneylib.to_platform_day(order.get("created_at")) or "") >= date_from)
        and (not date_to or (moneylib.to_platform_day(order.get("created_at")) or "9999") <= date_to)
    ]
    supplier_ids = list({order["supplier_id"] for order in orders if order.get("supplier_id")})
    retailer_ids = list({order["retailer_id"] for order in orders if order.get("retailer_id")})
    suppliers = {
        u["id"]: u for u in await db.users.find(
            {"id": {"$in": supplier_ids}}, {"_id": 0, "id": 1, "vat_registered": 1},
        ).to_list(len(supplier_ids) or 1)
    } if supplier_ids else {}
    terms_by_pair = {
        (t["supplier_id"], t["retailer_id"]): t for t in await db.credit_terms.find(
            {"supplier_id": {"$in": supplier_ids}, "retailer_id": {"$in": retailer_ids}}, {"_id": 0},
        ).to_list(5000)
    } if orders else {}

    wb = Workbook()
    sheet = wb.active
    sheet.title = "ინვოისები"
    sheet.append(["ინვოისის №", "თარიღი", "შეკვეთის სტატუსი", "მაღაზია" if sales_side else "დისტრიბუტორი",
                  "ს.კ.", "თანხა დღგ-ს გარეშე (₾)", "დღგ (₾)", "ჯამი (₾)", "გადახდილი (₾)",
                  "ნაშთი (₾)", "გადახდის სტატუსი", "გადახდის ვადა"])
    items_sheet = wb.create_sheet("პროდუქცია")
    items_sheet.append(["ინვოისის №", "პროდუქტი", "რაოდენობა", "ერთეულის ფასი (₾)", "ჯამი (₾)"])
    totals = {"subtotal": moneylib.ZERO, "vat": moneylib.ZERO, "total": moneylib.ZERO,
              "paid": moneylib.ZERO, "balance": moneylib.ZERO}
    for order in orders:
        view = finance_order_view(order, terms_by_pair.get((order.get("supplier_id"), order.get("retailer_id"))))
        if payment_status and payment_status != "all" and view["payment_status"] != payment_status:
            continue
        vat_registered = bool(suppliers.get(order.get("supplier_id"), {}).get("vat_registered"))
        total = moneylib.q(view["total"])
        vat = (total * 18 / 118).quantize(moneylib.CENT, rounding=ROUND_HALF_UP) if vat_registered else moneylib.ZERO
        subtotal = total - vat
        paid, balance = moneylib.q(view["amount_paid"]), moneylib.q(view["balance_due"])
        counterparty = order.get("retailer_name") if sales_side else order.get("supplier_name")
        tax_id = order.get("retailer_tax_id") if sales_side else order.get("supplier_tax_id")
        sheet.append([
            order.get("order_no", ""), str(order.get("created_at") or "")[:10],
            {"Processing": "დამტკიცებულია", "In Transit": "გზაშია", "Delivered": "მიწოდებულია"}.get(order["status"], order["status"]),
            counterparty or "", tax_id or "", moneylib.as_json(subtotal), moneylib.as_json(vat),
            moneylib.as_json(total), moneylib.as_json(paid), moneylib.as_json(balance),
            FINANCE_STATUS_KA[view["payment_status"]],
            str(view.get("payment_due_date") or "")[:10],
        ])
        for item in order.get("items", []):
            quantity, price = item.get("quantity", 0), moneylib.amount_or_zero(item.get("unit_price"))
            items_sheet.append([order.get("order_no", ""), item.get("name") or item.get("product_name", ""),
                                quantity, moneylib.as_json(price), moneylib.as_json(moneylib.q(price * Decimal(str(quantity or 0))))])
        for key, amount in zip(totals, (subtotal, vat, total, paid, balance)):
            totals[key] += amount
    sheet.append([])
    sheet.append(["სულ", "", "", "", "", *(moneylib.as_json(totals[k]) for k in ("subtotal", "vat", "total", "paid")),
                  moneylib.as_json(totals["balance"]), "", ""])
    for ws, widths in ((sheet, (18, 12, 18, 28, 14, 20, 12, 14, 14, 14, 20, 14)), (items_sheet, (18, 36, 12, 18, 14))):
        for cell in ws[1]:
            cell.font = Font(bold=True)
        ws.freeze_panes = "A2"
        for index, width in enumerate(widths):
            ws.column_dimensions[chr(65 + index)].width = width
    for cell in sheet[sheet.max_row]:
        cell.font = Font(bold=True)
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    name = f"finance-{date_from or 'start'}_{date_to or 'today'}.xlsx"
    return StreamingResponse(
        buffer, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


def _check_cron_auth(authorization):
    expected = os.environ.get("WEBHOOK_CRON_SECRET", "")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Unauthorized")
    token = authorization.split(" ", 1)[1]
    if not expected or not secrets.compare_digest(token, expected):
        raise HTTPException(401, "Unauthorized")


@api.post("/cron/generate-invoices")
async def cron_generate_invoices(background: BackgroundTasks, authorization: Optional[str] = Header(None)):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    _check_cron_auth(authorization)
    background.add_task(do_generate_invoices)
    return {"accepted": True}


@api.post("/cron/billing-check")
async def cron_billing_check(background: BackgroundTasks, authorization: Optional[str] = Header(None)):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    _check_cron_auth(authorization)
    background.add_task(do_billing_check)
    return {"accepted": True}


# ---------- payment cards & checkout split (sandbox gateway) ----------
class CardIn(BaseModel):
    number: str
    exp: str
    cvc: str
    name: Optional[str] = ""


MAX_PAYMENT_CARDS = 10


def _user_cards(u: dict) -> list:
    """Saved cards; a legacy single card on the user document is exposed as one entry."""
    cards = u.get("payment_cards")
    if isinstance(cards, list):
        return [{key: value for key, value in card.items() if key != "token"} for card in cards]
    if u.get("card_verified") and u.get("card_last4"):
        return [{"id": "legacy", "brand": u.get("card_brand", "card"), "last4": u.get("card_last4", ""),
                 "exp": u.get("card_expiry", ""), "name": u.get("card_name", ""),
                 "sim_status": u.get("card_sim_status", "ok")}]
    return []


def _card_view(c: dict) -> dict:
    return {"id": c["id"], "brand": c.get("brand", "card"), "last4": c.get("last4", ""),
            "exp": c.get("exp", ""), "name": c.get("name", ""), "verified": True}


def _card_public(u: dict):
    cards = _user_cards(u)
    return _card_view(cards[0]) if cards else None


async def _save_cards(user_id: str, cards: list) -> None:
    cards = [{key: value for key, value in card.items() if key != "token"} for card in cards]
    first = cards[0] if cards else None
    await db.users.update_one({"id": user_id}, {"$set": _encrypt_sensitive_fields({
        "payment_cards": cards,
        "card_verified": bool(first),
        "card_token": "",
        "card_brand": first.get("brand", "") if first else "",
        "card_last4": first.get("last4", "") if first else "",
        "card_expiry": first.get("exp", "") if first else "",
        "card_name": first.get("name", "") if first else "",
        "card_sim_status": first.get("sim_status", "") if first else "",
    })})


@api.post("/payments/cards")
async def add_card(body: CardIn, user: dict = Depends(get_current_user)):
    cards = list(_user_cards(user))
    if len(cards) >= MAX_PAYMENT_CARDS:
        raise HTTPException(400, f"You can save up to {MAX_PAYMENT_CARDS} cards.")
    try:
        info = validate_card(body.number, body.exp, body.cvc)
    except CardError as e:
        raise HTTPException(400, str(e))
    if any(c.get("last4") == info["last4"] and c.get("exp") == info["exp"] and c.get("brand") == info["brand"] for c in cards):
        raise HTTPException(409, "This card is already saved.")
    try:
        simulate_hold(info["sim_status"], 1.0)  # 1 GEL validation hold, released immediately
    except CardError as e:
        raise HTTPException(402, f"Card validation failed: {e}")
    card = {"id": gen_token()[:16], "brand": info["brand"], "last4": info["last4"], "exp": info["exp"],
            "name": body.name or user.get("card_name", ""),
            "sim_status": info["sim_status"], "created_at": now_iso()}
    cards.append(card)
    await _save_cards(user["id"], cards)
    return {"card": _card_view(card), "cards": [_card_view(c) for c in cards]}


@api.get("/payments/cards")
async def get_card(user: dict = Depends(get_current_user)):
    cards = _user_cards(user)
    return {"card": _card_view(cards[0]) if cards else None, "cards": [_card_view(c) for c in cards]}


@api.delete("/payments/cards/{card_id}")
async def delete_card_by_id(card_id: str, user: dict = Depends(get_current_user)):
    cards = _user_cards(user)
    remaining = [c for c in cards if c["id"] != card_id]
    if len(remaining) == len(cards):
        raise HTTPException(404, "Card not found.")
    await _save_cards(user["id"], remaining)
    return {"ok": True, "cards": [_card_view(c) for c in remaining]}


@api.delete("/payments/cards")
async def delete_card(user: dict = Depends(get_current_user)):
    await _save_cards(user["id"], [])
    return {"ok": True}


@api.get("/payments/payouts")
async def list_payouts(user: dict = Depends(get_current_user)):
    if user["role"] == "supplier":
        q = {"supplier_id": user["id"]}
    elif user["role"] == "admin":
        q = {}
    else:
        raise HTTPException(403, "Not allowed")
    return await db.payouts.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)


async def do_auto_debit():
    now = datetime.now(timezone.utc)
    invs = await db.invoices.find({"status": {"$ne": "paid"}}, {"_id": 0}).to_list(2000)
    charged = []
    for inv in invs:
        try:
            due = datetime.fromisoformat(inv["due_date"])
        except Exception:
            continue
        if now < due:
            continue  # not yet due
        sup = await db.users.find_one({"id": inv["supplier_id"]}, {"_id": 0})
        if not sup or not sup.get("card_verified"):
            continue
        try:
            ref = simulate_charge(sup.get("card_sim_status", "ok"), inv["amount"])
        except CardError:
            await notify(
                inv["supplier_id"],
                f"ინვოისის №{inv['invoice_no']} ავტომატური ჩამოჭრა ვერ შესრულდა. "
                "განაახლეთ ბარათის მონაცემები ან გადაიხადეთ ხელით.",
                "billing", invoice_id=inv["id"],
            )
            continue
        await db.invoices.update_one({"id": inv["id"]}, {"$set": {"status": "paid", "paid_at": now_iso(),
                                                                  "payment_ref": ref, "auto_debited": True}})
        await recompute_freeze(inv["supplier_id"])
        await notify(
            inv["supplier_id"],
            f"ინვოისის №{inv['invoice_no']} თანხა (₾{inv['amount']:.2f}) შენახული ბარათიდან ავტომატურად ჩამოიჭრა.",
            "billing", invoice_id=inv["id"],
        )
        charged.append(inv["invoice_no"])
    return charged


@api.post("/cron/auto-debit")
async def cron_auto_debit(background: BackgroundTasks, authorization: Optional[str] = Header(None)):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    _check_cron_auth(authorization)
    background.add_task(do_auto_debit)
    return {"accepted": True}


@api.post("/admin/auto-debit/run")
async def admin_run_auto_debit(user: dict = Depends(require_role("admin"))):
    charged = await do_auto_debit()
    return {"charged": charged, "count": len(charged)}


app.add_middleware(CORSMiddleware, allow_credentials=False,
                   allow_origins=safeguards.parse_cors_origins(os.environ),
                   allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Total-Count"])
app.add_middleware(GZipMiddleware, minimum_size=1024)


@app.middleware("http")
async def force_utf8_charset(request: Request, call_next):
    response = await call_next(request)
    ctype = response.headers.get("content-type", "")
    base = ctype.split(";")[0].strip().lower()
    if "charset" not in ctype.lower() and (base.startswith("text/") or base in ("application/json", "application/javascript")):
        response.headers["content-type"] = f"{base}; charset=utf-8"
    return response


@app.exception_handler(moneylib.MoneyError)
async def money_error_handler(request: Request, exc: moneylib.MoneyError):
    # A corrupt stored amount must fail the report loudly instead of being summed as 0.
    logging.getLogger("server").error("Invalid financial amount on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Financial data integrity error: a stored amount is missing or invalid."},
        headers={"Access-Control-Allow-Origin": "*"},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Raised errors are handled outside CORSMiddleware, so add the headers here
    # to keep the browser from masking the real 500 as a CORS failure.
    logging.getLogger("server").exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
        headers={"Access-Control-Allow-Origin": "*"},
    )


PERFORMANCE_INDEXES = [
    ("orders", [("supplier_id", 1), ("created_at", -1)]),
    ("orders", [("supplier_id", 1), ("status", 1), ("delivered_at", 1)]),
    ("orders", [("retailer_id", 1), ("branch_id", 1), ("created_at", -1)]),
    ("orders", [("id", 1)]),
    ("orders", [("invoice_id", 1)]),
    ("orders", [("warehouse_id", 1), ("status", 1)]),
    ("invoices", [("id", 1)]),
    ("invoices", [("supplier_id", 1), ("created_at", -1)]),
    ("invoices", [("status", 1), ("due_date", 1)]),
    ("invoices", [("supplier_id", 1), ("period", 1)]),
    ("notifications", [("user_id", 1), ("created_at", -1)]),
    ("notifications", [("user_id", 1), ("read", 1)]),
    ("broadcast_campaigns", [("created_at", -1)]),
    ("broadcast_campaigns", [("status", 1), ("updated_at", 1)]),
    ("push_subscriptions", [("user_id", 1)]),
    ("push_subscriptions", [("endpoint", 1)]),
    ("users", [("id", 1)]),
    ("users", [("role", 1)]),
    ("products", [("id", 1)]),
    ("messages", [("order_id", 1), ("created_at", 1)]),
    ("drivers", [("supplier_id", 1), ("warehouse_id", 1)]),
    ("supplier_warehouses", [("supplier_id", 1), ("active", 1)]),
    ("store_expenses", [("retailer_id", 1), ("expense_date", -1)]),
]


async def ensure_performance_indexes():
    """Idempotent; a failing index (for example on legacy data) must never block startup."""
    for collection, keys in PERFORMANCE_INDEXES:
        try:
            await db[collection].create_index(keys, background=True)
        except Exception:
            logger.exception("Could not create index %s on %s", keys, collection)


async def ensure_startup_indexes():
    """Non-critical indexes, created concurrently after the server is already serving requests."""
    async def safe(coro, label):
        try:
            await coro
        except Exception:
            logger.exception("Startup index step failed: %s", label)

    async def reset_indexes():
        info = await db.password_resets.index_information()
        if "token_hash_1" in info:
            await db.password_resets.drop_index("token_hash_1")
        await db.password_resets.create_index("email")
        await db.password_resets.create_index("expires_at", expireAfterSeconds=0)

    steps = [
        ("email_otps.email", db.email_otps.create_index("email", unique=True)),
        ("bank_payments.id", db.bank_payments.create_index("id", unique=True)),
        ("bank_payments.pay_id", db.bank_payments.create_index("pay_id", unique=True)),
        ("product_returns.id", db.product_returns.create_index("id", unique=True)),
        ("product_returns.supplier_status", db.product_returns.create_index([("supplier_id", 1), ("status", 1), ("created_at", -1)])),
        ("product_returns.store_history", db.product_returns.create_index([("retailer_id", 1), ("created_at", -1)])),
        ("product_returns.order_line", db.product_returns.create_index([("order_id", 1), ("product_id", 1), ("status", 1)])),
        ("inventory_movements.id", db.inventory_movements.create_index("id", unique=True)),
        ("webhook_events.ttl", db.webhook_events.create_index("received_at", expireAfterSeconds=30 * 86400)),
        ("idempotency_keys.ttl", db.idempotency_keys.create_index("created_at", expireAfterSeconds=86400)),
        ("password_resets", reset_indexes()),
        ("store_distributor_connections", db.store_distributor_connections.create_index(
            [("store_id", 1), ("distributor_id", 1)], unique=True)),
        ("custom_prices", db.custom_prices.create_index(
            [("distributor_id", 1), ("store_id", 1), ("product_id", 1)], unique=True)),
        ("product_offers.current", db.product_offers.create_index(
            [("distributor_id", 1), ("store_id", 1), ("product_id", 1)], unique=True)),
        ("product_offer_history.timeline", db.product_offer_history.create_index(
            [("distributor_id", 1), ("store_id", 1), ("at", -1)])),
        ("products.supplier_id", db.products.create_index("supplier_id")),
        ("products.category", db.products.create_index([("category", 1), ("supplier_id", 1)])),
        ("market_price_benchmarks.fingerprint", db.market_price_benchmarks.create_index("fingerprint", unique=True)),
        ("market_price_benchmarks.product_observed", db.market_price_benchmarks.create_index(
            [("product_id", 1), ("status", 1), ("observed_at", -1)])),
        ("users.role_cities", db.users.create_index([("role", 1), ("cities", 1)])),
        ("orders.retailer_id", db.orders.create_index("retailer_id")),
        ("orders.supplier_id", db.orders.create_index("supplier_id")),
        ("drivers", db.drivers.create_index([("supplier_id", 1), ("name", 1)])),
        ("saved_contacts", db.saved_contacts.create_index([("owner_id", 1), ("id", 1)], unique=True)),
        ("delivery_routes.updated", db.delivery_routes.create_index([("supplier_id", 1), ("updated_at", -1)])),
        ("delivery_routes.share", db.delivery_routes.create_index("share_token_hash", sparse=True)),
    ]
    await asyncio.gather(*(safe(coro, label) for label, coro in steps))
    await ensure_performance_indexes()


async def remove_plaintext_card_tokens():
    await db.users.update_many({"card_token": {"$exists": True}}, {"$unset": {"card_token": ""}})
    users = db.users.find(
        {"payment_cards.token": {"$exists": True}}, {"_id": 1, "payment_cards": 1},
    )
    async for user in users:
        cards = [{key: value for key, value in card.items() if key != "token"}
                 for card in user.get("payment_cards", []) if isinstance(card, dict)]
        await db.users.update_one({"_id": user["_id"]}, {"$set": {"payment_cards": cards}})


async def migrate_sensitive_fields():
    encryption_enabled = bool(os.environ.get("FIELD_ENCRYPTION_KEY", "").strip())

    async def migrate(collection_name, query, projection, field_names):
        if not encryption_enabled:
            return
        collection = db[collection_name]
        operations = []

        async def flush():
            if operations:
                await asyncio.gather(*(collection.update_one(selector, update)
                                       for selector, update in operations))

        async for document in collection.find(query, projection):
            encrypted = _encrypt_sensitive_fields(document)
            updates = {field: encrypted[field] for field in field_names
                       if field in encrypted and encrypted.get(field) != document.get(field)}
            if updates:
                operations.append(({"_id": document["_id"]}, {"$set": updates}))
            if len(operations) >= 100:
                await flush()
                operations = []
        await flush()

    await migrate(
        "users", {"$or": [{"iban": {"$exists": True}}, {"bank_accounts": {"$exists": True}},
                           {"card_last4": {"$exists": True}}, {"card_expiry": {"$exists": True}},
                           {"payment_cards": {"$exists": True}}]},
        {"_id": 1, "iban": 1, "bank_accounts": 1, "card_last4": 1, "card_expiry": 1,
         "payment_cards": 1},
        ("iban", "bank_accounts", "card_last4", "card_expiry", "payment_cards"),
    )
    await migrate(
        "orders", {"$or": [{"bank_account_snapshot": {"$exists": True}},
                            {"platform_split.platform_iban": {"$exists": True}}]},
        {"_id": 1, "bank_account_snapshot": 1, "platform_split": 1},
        ("bank_account_snapshot", "platform_split"),
    )
    await migrate(
        "settings", {"issuer_iban": {"$exists": True}},
        {"_id": 1, "issuer_iban": 1}, ("issuer_iban",),
    )
    await migrate(
        "invoices", {"issuer_iban": {"$exists": True}},
        {"_id": 1, "issuer_iban": 1}, ("issuer_iban",),
    )
    invoices = db.invoices.find(
        {"payment_reference": {"$type": "string"}, "payment_reference_normalized": {"$exists": False}},
        {"_id": 1, "payment_reference": 1},
    )
    async for invoice in invoices:
        await db.invoices.update_one(
            {"_id": invoice["_id"]},
            {"$set": {"payment_reference_normalized": invoice["payment_reference"].strip().casefold()}},
        )


async def run_background_startup():
    """Idempotent migrations and backfills; none of them gate request handling."""
    async def step(fn, label):
        try:
            await fn()
        except Exception:
            logger.exception("Background startup step failed: %s", label)

    async def verified_backfill():
        # existing/seeded accounts are treated as already verified
        await db.users.update_many({"email_verified": {"$exists": False}}, {"$set": {"email_verified": True}})

    async def seed_categories():
        existing = {c["name"] async for c in db.categories.find({}, {"_id": 0, "name": 1})}
        missing = [n for n in DEFAULT_CATEGORY_NAMES if n not in existing]
        if missing:
            await db.categories.insert_many([{"id": str(uuid.uuid4()), "name": c} for c in missing])

    async def backfill_product_categories():
        # One-time/idempotent: attach category + category_id to products missing either.
        missing = {"$or": [
            {"category_id": {"$exists": False}}, {"category_id": None}, {"category_id": ""},
            {"category": {"$exists": False}}, {"category": None}, {"category": ""},
        ]}
        products = await db.products.find(missing, {"_id": 0, "id": 1, "name": 1, "category": 1, "supplier_id": 1}).to_list(50000)
        cache = {}
        fixed = 0
        for product in products:
            if not product.get("supplier_id"):
                continue
            key = (product["supplier_id"], product.get("name", ""), product.get("category") or "")
            if key not in cache:
                cache[key] = await smart_category_details_for(
                    product.get("name", ""), product.get("category"), business_id=product["supplier_id"],
                )
            category, category_id = cache[key]
            if category_id:
                await db.products.update_one(
                    {"id": product["id"]}, {"$set": {"category": category, "category_id": category_id}},
                )
                fixed += 1
        if fixed:
            logger.info("Backfilled categories for %d products", fixed)

    await asyncio.gather(
        step(backfill_product_categories, "product category backfill"),
        step(backfill_existing_admin_contacts, "existing admin contacts"),
        step(ensure_startup_indexes, "indexes"),
        step(lambda: migrate_store_finance(db), "store finance"),
        step(lambda: migrate_store_branches(db), "store branches"),
        step(lambda: migrate_supplier_warehouses(db), "supplier warehouses"),
        step(remove_plaintext_card_tokens, "plaintext card token cleanup"),
        step(verified_backfill, "email_verified"),
        step(seed_categories, "categories"),
        step(get_settings, "settings"),
        step(_recover_broadcasts, "broadcast recovery"),
    )


async def wait_for_database():
    attempts = int(os.environ.get("MONGO_STARTUP_RETRIES", "5"))
    for attempt in range(1, attempts + 1):
        try:
            await client.admin.command("ping")
            if audit_client is not None:
                await audit_client.admin.command("ping")
            return
        except Exception as exc:
            # Never log mongo_url: it contains the credentials.
            logger.error(
                "MongoDB unreachable (attempt %s/%s): %s. If this persists, check the Atlas Network Access "
                "allowlist includes this server's public IP and that MONGO_URL is correct.",
                attempt, attempts, type(exc).__name__,
            )
            if attempt == attempts:
                raise
            await asyncio.sleep(min(2 ** attempt, 15))


@app.on_event("startup")
async def startup():
    # Only what must exist before the first request is awaited here; every round trip to a hosted
    # database costs hundreds of ms, so the rest runs in the background.
    safeguards.validate_production_environment(os.environ)
    await wait_for_database()
    await migrate_sensitive_fields()
    await remove_plaintext_card_tokens()
    await db.invoices.create_index("payment_reference_normalized", unique=True, sparse=True)
    await db.invoice_bank_transactions.create_index("transaction_id", unique=True)
    await db.users.create_index("email", unique=True)
    try:
        await purge_demo_accounts(db)
    except Exception:
        logger.exception("Could not purge demo accounts")
    try:
        admin_result = await ensure_admin_account(db, hash_password, verify_password)
        if admin_result in ("created", "updated"):
            logger.info("Primary admin account %s", admin_result)
    except Exception:
        logger.exception("Could not ensure the primary admin account")
    app.state.index_task = asyncio.create_task(run_background_startup())
    if os.environ.get("BILLING_SCHEDULER", "1") != "0":
        app.state.billing_task = asyncio.create_task(billing_scheduler_loop())


@app.on_event("shutdown")
async def shutdown():
    task = getattr(app.state, "billing_task", None)
    if task:
        task.cancel()
    client.close()
    if audit_client is not None:
        audit_client.close()


IMPORT_HEADERS = {
    "name": "name", "product": "name", "product_name": "name", "სახელი": "name",
    "დასახელება": "name", "პროდუქტი": "name", "პროდუქტის_სახელი": "name",
    "პროდუქტის_დასახელება": "name",
    "id": "external_id", "product_id": "external_id", "external_id": "external_id",
    "პროდუქტის_კოდი": "external_id", "sku": "sku", "item_number": "sku", "კოდი": "sku",
    "barcode": "barcode", "bar_code": "barcode", "ean": "barcode", "gtin": "barcode",
    "შტრიხკოდი": "barcode", "ბარკოდი": "barcode",
    "category": "category", "კატეგორია": "category",
    "city": "city", "ქალაქი": "city",
    "price": "price_per_unit", "unit_price": "price_per_unit",
    "price_per_unit": "price_per_unit", "ფასი": "price_per_unit",
    "ერთეულის_ფასი": "price_per_unit", "ფასი_ერთეულზე": "price_per_unit",
    "moq": "moq", "min_qty": "moq", "minimum_order_quantity": "moq",
    "მინ_შეკვეთა": "moq", "მინიმალური_შეკვეთა": "moq", "მინ_რაოდენობა": "moq",
    "მინიმალური_რაოდენობა": "moq", "minimum_quantity": "moq", "minimum_stock": "moq",
    "min_stock": "moq", "minimum_stock_level": "moq", "reorder_level": "moq",
    "მინიმალური_მარაგი": "moq", "მინ_მარაგი": "moq", "მარაგის_მინიმალური_დონე": "moq",
    "stock": "stock", "მარაგი": "stock", "მარაგის_რაოდენობა": "stock", "ნაშთი": "stock", "რაოდენობა": "stock",
    "quantity": "stock", "qty": "stock", "current_stock": "stock", "available_quantity": "stock",
    "რაოდენობა_მარაგში": "stock", "მიმდინარე_მარაგი": "stock",
    "unit": "unit", "unit_of_measure": "unit", "ერთეული": "unit", "საზომი_ერთეული": "unit",
    "image": "image", "image_url": "image", "სურათი": "image", "სურათის_url": "image",
    "description": "description", "აღწერა": "description",
    "tier_pricing": "tier_pricing", "მოცულობითი_ფასები": "tier_pricing",
}

IMPORT_FIELD_LABELS = {
    "name": "სახელი", "category": "კატეგორია", "city": "ქალაქი",
    "price_per_unit": "ფასი", "moq": "მინიმალური შეკვეთა", "stock": "მარაგი",
    "image": "სურათი", "description": "აღწერა", "tier_pricing": "მოცულობითი ფასები",
    "sku": "SKU / კოდი", "barcode": "შტრიხკოდი", "unit": "საზომი ერთეული",
    "external_id": "პროდუქტის ID",
}


def _import_key(name: str, category: str) -> tuple:
    return (" ".join(name.casefold().split()), " ".join(category.casefold().split()))


def _import_error(row: int, column: str, message: str) -> dict:
    return {"row": row, "column": column, "message": message}


async def _read_import_file(file: UploadFile, mapping_json: str = "") -> tuple:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".xlsx", ".xls", ".csv", ".txt"):
        raise HTTPException(400, "ფაილის ფორმატი არასწორია. ატვირთეთ Excel-ის (.xlsx, .xls), CSV (.csv) ან ტექსტური (.txt) ფაილი.")

    contents = await file.read()
    if not contents or not contents.strip():
        raise HTTPException(400, "ფაილი ცარიელია ან მასში მონაცემები ვერ მოიძებნა.")

    try:
        if suffix in (".csv", ".txt"):
            frame = pd.read_csv(io.BytesIO(contents), encoding="utf-8-sig", dtype=object, sep=None, engine="python")
        else:
            frame = pd.read_excel(io.BytesIO(contents), dtype=object)
    except UnicodeDecodeError:
        logger.info("Product CSV upload rejected because it is not valid UTF-8")
        raise HTTPException(400, "CSV ფაილი UTF-8 კოდირებით უნდა იყოს შენახული.")
    except (pd.errors.ParserError, ValueError, OSError):
        logger.info("Product import file is malformed or unreadable")
        raise HTTPException(400, "ფაილი დაზიანებულია ან მისი წაკითხვა ვერ მოხერხდა. გადაამოწმეთ ფაილი და სცადეთ ხელახლა.")
    except Exception:
        logger.exception("Product import file could not be parsed")
        raise HTTPException(400, "ფაილი დაზიანებულია ან მისი წაკითხვა ვერ მოხერხდა. გადაამოწმეთ ფაილი და სცადეთ ხელახლა.")

    if frame.empty or len(frame.columns) == 0:
        raise HTTPException(400, "ფაილი ცარიელია ან მასში მონაცემები ვერ მოიძებნა.")

    frame.columns = [str(column).replace("\ufeff", "").strip() for column in frame.columns]
    frame = frame.astype(object).where(pd.notnull(frame), None)
    columns = list(frame.columns)
    mapping = {}
    for column in columns:
        normalized = "_".join(column.casefold().replace("_", " ").split())
        field = IMPORT_HEADERS.get(normalized)
        if field and field not in mapping:
            mapping[field] = column
    if mapping_json:
        try:
            requested_mapping = json.loads(mapping_json)
        except json.JSONDecodeError:
            raise HTTPException(400, "სვეტების შესაბამისობა არასწორია. აირჩიეთ სვეტები ხელახლა.")
        if not isinstance(requested_mapping, dict):
            raise HTTPException(400, "სვეტების შესაბამისობა არასწორია. აირჩიეთ სვეტები ხელახლა.")
        allowed_fields = set(IMPORT_FIELD_LABELS)
        mapping = {}
        for field, column in requested_mapping.items():
            if field not in allowed_fields or column in (None, ""):
                continue
            if column not in columns:
                raise HTTPException(400, "არჩეული სვეტი ფაილში ვერ მოიძებნა. აირჩიეთ სვეტები ხელახლა.")
            mapping[field] = column

    missing_columns = sorted({"name"} - set(mapping))
    rows, errors = [], []
    for row_number, source in enumerate(frame.to_dict(orient="records"), start=2):
        values = {field: source.get(column) for field, column in mapping.items()}
        values = {
            field: value for field, value in values.items()
            if value is not None and str(value).strip() != ""
        }
        if not values:
            continue

        missing_values = [field for field in ("name",) if field not in values]
        if missing_values:
            for field in missing_values:
                errors.append(_import_error(
                    row_number, IMPORT_FIELD_LABELS[field],
                    "პროდუქტის სახელი სავალდებულოა." if field == "name" else "ეს ველი სავალდებულოა.",
                ))
            continue

        for field in ("name", "category", "city", "image", "description", "sku", "barcode", "unit", "external_id"):
            if field in values:
                values[field] = str(values[field]).strip()
        if values.get("tier_pricing") and isinstance(values["tier_pricing"], str):
            try:
                values["tier_pricing"] = json.loads(values["tier_pricing"])
            except json.JSONDecodeError:
                errors.append(_import_error(row_number, IMPORT_FIELD_LABELS["tier_pricing"], "მიუთითეთ სწორი JSON სია."))
                continue

        try:
            row_data = ProductImportRow.model_validate(values).model_dump(exclude_unset=True, exclude_none=True)
            row_data["_category_inferred"] = not row_data.get("category")
            row_data.setdefault("category", "Other")
            row_data["_row"] = row_number
            rows.append(row_data)
        except ValidationError as exc:
            for issue in exc.errors():
                field = issue["loc"][0] if issue.get("loc") else ""
                label = IMPORT_FIELD_LABELS.get(field, "მონაცემები")
                if issue["type"] == "missing":
                    message = "სავალდებულო სვეტი ან მნიშვნელობა აკლია."
                elif field == "price_per_unit":
                    message = "მიუთითეთ სწორი რიცხვითი ფასი."
                elif field in ("moq", "stock"):
                    message = "მიუთითეთ მთელი რიცხვი."
                else:
                    message = "მნიშვნელობის ფორმატი არასწორია."
                errors.append(_import_error(row_number, label, message))

    if not rows and not errors and not missing_columns:
        raise HTTPException(400, "ფაილი ცარიელია ან მასში მონაცემები ვერ მოიძებნა.")
    metadata = {
        "columns": columns,
        "mapping": mapping,
        "missing_columns": missing_columns,
        "unmapped_columns": [column for column in columns if column not in mapping.values()],
    }
    return rows, errors, metadata


def _identity_value(value: Optional[str]) -> str:
    return " ".join(str(value or "").casefold().split())


def _primary_import_key(row: dict) -> Optional[tuple]:
    for field in ("external_id", "barcode", "sku"):
        if row.get(field):
            return field, _identity_value(row[field])
    if row.get("name") and row.get("_category_inferred"):
        return "name", " ".join(row["name"].casefold().split())
    if row.get("name") and row.get("category"):
        return "name_category", _import_key(row["name"], row["category"])
    return None


def _plan_product_import(rows: list, existing: list) -> tuple:
    errors, unique_rows, seen_rows = [], [], {}
    duplicate_count = 0
    for row in rows:
        key = _primary_import_key(row)
        row_number = row["_row"]
        if not key:
            errors.append(_import_error(row_number, "პროდუქტის კოდი", "მიუთითეთ პროდუქტის სახელი და კატეგორია, ან SKU/შტრიხკოდი."))
            continue
        previous = seen_rows.get(key)
        if previous:
            differences = [
                field for field in set(previous) & set(row)
                if field != "_row" and previous[field] != row[field]
            ]
            if differences:
                labels = ", ".join(IMPORT_FIELD_LABELS.get(field, field) for field in differences)
                errors.append(_import_error(row_number, labels, "ერთი და იმავე პროდუქტის ჩანაწერები ერთმანეთს ეწინააღმდეგება."))
                continue
            previous.update({field: value for field, value in row.items() if field != "_row"})
            duplicate_count += 1
            continue
        seen_rows[key] = dict(row)
        unique_rows.append(seen_rows[key])

    index = {}
    for product in existing:
        for field in ("id", "external_id", "sku", "barcode"):
            value = _identity_value(product.get(field))
            if value:
                index.setdefault((field, value), []).append(product)
        if product.get("name") and product.get("category"):
            index.setdefault(("name_category", _import_key(product["name"], product["category"])), []).append(product)
        if product.get("name"):
            index.setdefault(("name", " ".join(product["name"].casefold().split())), []).append(product)

    plan, claimed_ids = [], {}
    for row in unique_rows:
        stable_keys = [
            (field, _identity_value(row[field]))
            for field in ("external_id", "barcode", "sku") if row.get(field)
        ]
        if row.get("external_id"):
            stable_keys.append(("id", _identity_value(row["external_id"])))
        if row.get("name") and row.get("_category_inferred"):
            name_key = ("name", " ".join(row["name"].casefold().split()))
        else:
            name_key = ("name_category", _import_key(row["name"], row["category"])) if row.get("name") and row.get("category") else None
        stable_matches = {p["id"]: p for key in stable_keys for p in index.get(key, [])}
        name_matches = {p["id"]: p for key in ([name_key] if name_key else []) for p in index.get(key, [])}
        candidates = stable_matches or name_matches
        if stable_matches and name_matches and set(stable_matches) != set(name_matches):
            errors.append(_import_error(row["_row"], "SKU / შტრიხკოდი", "იდენტიფიკატორი და სახელი სხვადასხვა პროდუქტს ემთხვევა."))
            continue
        if len(candidates) > 1:
            errors.append(_import_error(row["_row"], "SKU / შტრიხკოდი", "ეს იდენტიფიკატორი ერთზე მეტ პროდუქტს შეესაბამება."))
            continue
        match = next(iter(candidates.values()), None)
        if match and match["id"] in claimed_ids:
            errors.append(_import_error(row["_row"], "SKU / შტრიხკოდი", "ფაილის რამდენიმე სტრიქონი ერთ არსებულ პროდუქტს ემთხვევა."))
            continue
        if match and not set(row) - {"_row", "external_id", "sku", "barcode"}:
            errors.append(_import_error(row["_row"], "მონაცემები", "არსებული პროდუქტის განახლებისთვის მიუთითეთ ფასი, მარაგი ან სხვა ველი."))
            continue
        if match:
            claimed_ids[match["id"]] = row["_row"]
        else:
            row.setdefault("price_per_unit", 0)
            row.setdefault("stock", 0)
            row.setdefault("moq", 1)
        plan.append({"row": row, "match": match})
    return plan, errors, duplicate_count


async def _prepare_product_import(file: UploadFile, mapping: str, user: dict) -> tuple:
    rows, errors, metadata = await _read_import_file(file, mapping)
    for field in metadata["missing_columns"]:
        errors.append(_import_error(1, IMPORT_FIELD_LABELS[field], "შეარჩიეთ შესაბამისი სვეტი."))
    existing = await db.products.find({"supplier_id": supplier_owner_id(user)}, {"_id": 0}).to_list(None)
    plan, plan_errors, duplicate_count = _plan_product_import(rows, existing)
    return plan, errors + plan_errors, duplicate_count, metadata


async def _product_import_warehouse_id(user: dict, requested_id: Optional[str]) -> Optional[str]:
    if getattr(db, "supplier_warehouses", None) is None:
        return None
    selected_id = await supplier_warehouse_id(user, requested_id)
    if selected_id:
        return selected_id
    owner_id = supplier_owner_id(user)
    warehouse_query = {"supplier_id": owner_id, "active": True}
    warehouse = await db.supplier_warehouses.find_one(
        {**warehouse_query, "is_default": True}, {"_id": 0, "id": 1},
    )
    if not warehouse:
        warehouses = await db.supplier_warehouses.find(
            warehouse_query, {"_id": 0, "id": 1},
        ).sort("created_at", 1).to_list(1)
        warehouse = warehouses[0] if warehouses else None
    # No active warehouse: import into the central pool instead of blocking.
    return warehouse["id"] if warehouse else None


@api.post("/products/import-preview")
async def preview_product_import(
    file: UploadFile = File(...), mapping: str = Form(""),
    warehouse_id: Optional[str] = None,
    user: dict = Depends(require_role("supplier")),
):
    require_supplier_permission(user, "inventory")
    if user.get("supplier_access_role", "global_admin") != "global_admin":
        raise HTTPException(403, "Only the distributor owner can import shared product records.")
    await _product_import_warehouse_id(user, warehouse_id)
    try:
        plan, errors, duplicate_count, metadata = await _prepare_product_import(file, mapping, user)
        updates = sum(item["match"] is not None for item in plan)
        return {
            **metadata, "valid_count": len(plan), "new_count": len(plan) - updates,
            "update_count": updates, "duplicate_count": duplicate_count, "errors": errors,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Product import preview failed")
        raise HTTPException(500, "მონაცემების დამუშავება ვერ მოხერხდა. გთხოვთ, სცადოთ ხელახლა.")


@api.post("/products/upload-excel")
async def upload_excel(
    file: UploadFile = File(...), mapping: str = Form(""),
    stock_mode: str = Form("replace"),
    warehouse_id: Optional[str] = None,
    user: dict = Depends(require_role("supplier")),
):
    require_supplier_permission(user, "inventory")
    if user.get("supplier_access_role", "global_admin") != "global_admin":
        raise HTTPException(403, "Only the distributor owner can import shared product records.")
    if stock_mode not in ("add", "replace", "new_only"):
        raise HTTPException(400, "მარაგის რეჟიმი არასწორია. აირჩიეთ „დამატება“, „ჩანაცვლება“ ან „მხოლოდ ახალი“.")
    add_stock = stock_mode == "add"
    new_only = stock_mode == "new_only"
    owner_id = supplier_owner_id(user)
    selected_warehouse_id = await _product_import_warehouse_id(user, warehouse_id)
    try:
        plan, errors, duplicate_count, _ = await _prepare_product_import(file, mapping, user)
        if errors:
            raise HTTPException(422, detail={
                "message": "ფაილში შეცდომები ან ურთიერთგამომრიცხავი მონაცემებია. არაფერი შეცვლილა.",
                "errors": errors,
            })
        if not plan:
            raise HTTPException(400, "ფაილში დასამატებელი ან გასაახლებელი მონაცემები ვერ მოიძებნა.")

        operations, stock_updates, new_count, update_count, skipped_count = [], [], 0, 0, 0
        for item in plan:
            row, match = item["row"], item["match"]
            if new_only and match:
                skipped_count += 1
                continue
            product_data = {field: value for field, value in row.items() if field not in ("_row", "_category_inferred")}
            stock_amount = product_data.pop("stock", None) if selected_warehouse_id else None
            if match:
                category_input = None if row.get("_category_inferred") else product_data.get("category")
                product_data["category"], category_id = await resolve_product_category(
                    product_data.get("name") or match.get("name", ""), owner_id, category_input,
                )
                product_data["category_id"] = category_id
                update_doc = {}
                # Without warehouses the quantity lives on the product itself.
                if add_stock and not selected_warehouse_id and "stock" in product_data:
                    update_doc["$inc"] = {"stock": int(product_data.pop("stock"))}
                if product_data:
                    update_doc["$set"] = product_data
                operations.append(UpdateOne({"id": match["id"], "supplier_id": owner_id}, update_doc))
                product_id = match["id"]
                update_count += 1
            else:
                if selected_warehouse_id:
                    product_data["stock"] = stock_amount or 0
                product_data = ProductIn.model_validate(product_data).model_dump()
                category_input = None if row.get("_category_inferred") else product_data.get("category")
                product_data["category"], category_id = await resolve_product_category(
                    product_data.get("name", ""), owner_id, category_input,
                )
                product_data["category_id"] = category_id
                product_data["city"] = product_data.get("city") or user.get("city", "")
                product_id = str(uuid.uuid4())
                doc = {
                    "id": product_id, "supplier_id": owner_id,
                    "supplier_name": user.get("business_name", ""),
                    **product_data, "created_at": now_iso(),
                }
                if selected_warehouse_id:
                    doc["warehouse_id"] = selected_warehouse_id
                operations.append(UpdateOne(
                    {"id": product_id, "supplier_id": owner_id},
                    {"$setOnInsert": doc}, upsert=True,
                ))
                new_count += 1
            if stock_amount is not None:
                stock_updates.append((product_id, int(stock_amount), match is not None))

        if not operations:
            return {
                "status": "success", "added": 0, "updated": 0, "skipped": skipped_count,
                "duplicates": duplicate_count, "processed_count": 0, "stock_mode": stock_mode,
                "message": f"ახალი პროდუქტი ვერ მოიძებნა. გამოტოვებულია {skipped_count} არსებული პროდუქტი.",
            }

        async with await client.start_session() as session:
            async with session.start_transaction():
                await db.products.bulk_write(operations, ordered=True, session=session)
                for product_id, stock_amount, is_existing in stock_updates:
                    stock_filter = {"supplier_id": owner_id, "product_id": product_id,
                                    "warehouse_id": selected_warehouse_id}
                    stock_change = (
                        {"$inc": {"stock": stock_amount}} if add_stock and is_existing
                        else {"$set": {"stock": stock_amount}}
                    )
                    await db.warehouse_inventory.update_one(
                        stock_filter,
                        {**stock_change, "$set": {**stock_change.get("$set", {}), "updated_at": now_iso()},
                         "$setOnInsert": {"id": str(uuid.uuid4()), "supplier_id": owner_id,
                                          "product_id": product_id, "warehouse_id": selected_warehouse_id}},
                        upsert=True, session=session,
                    )

        return {
            "status": "success", "added": new_count, "updated": update_count, "skipped": skipped_count,
            "duplicates": duplicate_count, "processed_count": new_count + update_count,
            "stock_mode": stock_mode,
            "message": (
                f"დაემატა {new_count} ახალი პროდუქტი, გამოტოვებულია {skipped_count} არსებული პროდუქტი."
                if new_only else
                f"წარმატებით განახლდა {update_count} არსებული პროდუქტი, დაემატა {new_count} ახალი პროდუქტი."
            ),
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Product import transaction failed")
        raise HTTPException(500, "მონაცემების შენახვა ვერ მოხერხდა. არაფერი შეცვლილა; გთხოვთ, სცადოთ ხელახლა.")


app.include_router(api, prefix="/api", tags=["api"])
