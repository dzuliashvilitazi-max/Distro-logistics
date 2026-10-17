from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parent / '.env')

import os
import uuid
import jwt
import bcrypt
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr

from seed import seed_data
import io
import secrets
from fastapi import Header, BackgroundTasks
from fastapi.responses import StreamingResponse
from email_service import try_send_email, invoice_email_html, reminder_email_html
from invoices import build_invoice_pdf
from payments import validate_card, gen_token, simulate_hold, simulate_charge, CardError

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

JWT_SECRET = os.environ['JWT_SECRET']
JWT_ALGORITHM = "HS256"

app = FastAPI()
api = APIRouter(prefix="/api")
security = HTTPBearer(auto_error=False)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("distro")


# ---------- helpers ----------
def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()

def verify_password(p: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode(), h.encode())
    except Exception:
        return False

def create_token(user_id: str) -> str:
    payload = {"sub": user_id, "exp": datetime.now(timezone.utc) + timedelta(days=7), "type": "access"}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

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
    return user

def require_role(*roles):
    async def checker(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(403, "Insufficient permissions")
        return user
    return checker


# ---------- models ----------
class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: str  # retailer | supplier
    business_name: Optional[str] = ""
    address: Optional[str] = ""
    city: Optional[str] = ""
    identification_number: str  # Tax ID / Personal ID (mandatory)
    establishment_type: Optional[str] = ""  # retailer only
    # retailer card (store masked only)
    card_name: Optional[str] = ""
    card_number: Optional[str] = ""
    card_expiry: Optional[str] = ""
    # supplier banking
    bank_name: Optional[str] = ""
    iban: Optional[str] = ""

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class TierPrice(BaseModel):
    min_qty: int
    price: float

class ProductIn(BaseModel):
    name: str
    category: str
    city: Optional[str] = ""
    price_per_unit: float
    tier_pricing: List[TierPrice] = []
    moq: int = 1
    stock: int = 0
    image: str = ""
    description: Optional[str] = ""

class OrderItem(BaseModel):
    product_id: str
    name: str
    image: str = ""
    supplier_id: str
    quantity: int
    unit_price: float

class OrderIn(BaseModel):
    items: List[OrderItem]
    delivery_address: str
    notes: Optional[str] = ""
    delivery_window: Optional[str] = ""
    payment_method: Optional[str] = "cash"  # cash | card | consignment

class StatusUpdate(BaseModel):
    status: str

class MessageIn(BaseModel):
    to_id: str
    text: str
    order_id: Optional[str] = ""

class ProfileIn(BaseModel):
    name: Optional[str] = None
    business_name: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    city: Optional[str] = None
    identification_number: Optional[str] = None
    establishment_type: Optional[str] = None
    card_name: Optional[str] = None
    card_number: Optional[str] = None
    card_expiry: Optional[str] = None
    bank_name: Optional[str] = None
    iban: Optional[str] = None

class SettingsIn(BaseModel):
    fee_type: str = "percent"       # percent | fixed
    fee_value: float = 5.0          # percent (%) or fixed amount (₾)
    fee_payer: str = "supplier"     # supplier | retailer | split
    issuer_name: Optional[str] = None
    issuer_tax_id: Optional[str] = None
    issuer_iban: Optional[str] = None

class CategoryIn(BaseModel):
    name: str


def mask_card(number: str) -> str:
    digits = "".join(ch for ch in (number or "") if ch.isdigit())
    return digits[-4:] if len(digits) >= 4 else ""

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
    if changed:
        await db.settings.update_one({"id": "platform"}, {"$set": changed})
    return s

def compute_fee(total: float, s: dict) -> float:
    if s["fee_type"] == "fixed":
        return round(float(s["fee_value"]), 2)
    return round(total * float(s["fee_value"]) / 100.0, 2)


async def notify(user_id: str, text: str, ntype: str = "info"):
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()), "user_id": user_id, "text": text,
        "type": ntype, "read": False, "created_at": now_iso()
    })

def clean(doc):
    doc.pop("_id", None)
    return doc


# ---------- auth ----------
@api.post("/auth/register")
async def register(body: RegisterIn):
    email = body.email.lower()
    if body.role not in ("retailer", "supplier"):
        raise HTTPException(400, "Invalid role")
    if await db.users.find_one({"email": email}):
        raise HTTPException(400, "Email already registered")
    if not (body.identification_number or "").strip():
        raise HTTPException(400, "Identification number is required")
    uid = str(uuid.uuid4())
    user = {
        "id": uid, "email": email, "password_hash": hash_password(body.password),
        "name": body.name, "role": body.role, "business_name": body.business_name or body.name,
        "address": body.address or "", "phone": "", "city": body.city or "",
        "identification_number": body.identification_number.strip(),
        "establishment_type": body.establishment_type or "",
        "card_name": body.card_name or "", "card_last4": mask_card(body.card_number),
        "card_expiry": body.card_expiry or "",
        "bank_name": body.bank_name or "", "iban": body.iban or "",
        "status": "pending" if body.role == "supplier" else "active",
        "created_at": now_iso(),
    }
    await db.users.insert_one(user)
    if body.role == "supplier":
        admins = await db.users.find({"role": "admin"}).to_list(10)
        for a in admins:
            await notify(a["id"], f"New supplier '{user['business_name']}' awaiting approval", "approval")
    token = create_token(uid)
    return {"token": token, "user": clean({**user, "password_hash": None})}

@api.post("/auth/login")
async def login(body: LoginIn):
    user = await db.users.find_one({"email": body.email.lower()})
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password")
    token = create_token(user["id"])
    user = clean(user); user.pop("password_hash", None)
    return {"token": token, "user": user}

@api.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return user


# ---------- products ----------
@api.get("/products")
async def list_products(category: Optional[str] = None, supplier_id: Optional[str] = None,
                        search: Optional[str] = None, availability: Optional[str] = None,
                        city: Optional[str] = None):
    q = {}
    if category and category not in ("All Products", "all"):
        q["category"] = category
    if supplier_id:
        q["supplier_id"] = supplier_id
    if city and city not in ("All Cities", "all"):
        q["city"] = city
    if search:
        q["name"] = {"$regex": search, "$options": "i"}
    if availability == "in_stock":
        q["stock"] = {"$gt": 0}
    docs = await db.products.find(q, {"_id": 0}).to_list(500)
    return docs

@api.post("/products")
async def create_product(body: ProductIn, user: dict = Depends(require_role("supplier"))):
    pid = str(uuid.uuid4())
    data = body.model_dump()
    data["city"] = data.get("city") or user.get("city", "")
    doc = {"id": pid, "supplier_id": user["id"], "supplier_name": user["business_name"],
           **data, "created_at": now_iso()}
    await db.products.insert_one(dict(doc))
    return clean(doc)

@api.put("/products/{pid}")
async def update_product(pid: str, body: ProductIn, user: dict = Depends(require_role("supplier"))):
    prod = await db.products.find_one({"id": pid})
    if not prod:
        raise HTTPException(404, "Product not found")
    if prod["supplier_id"] != user["id"]:
        raise HTTPException(404, "Product not found")
    await db.products.update_one({"id": pid}, {"$set": body.model_dump()})
    updated = await db.products.find_one({"id": pid}, {"_id": 0})
    return updated

@api.delete("/products/{pid}")
async def delete_product(pid: str, user: dict = Depends(require_role("supplier"))):
    res = await db.products.delete_one({"id": pid, "supplier_id": user["id"]})
    if res.deleted_count == 0:
        raise HTTPException(404, "Product not found")
    return {"ok": True}


# ---------- orders ----------
@api.post("/orders")
async def create_order(body: OrderIn, user: dict = Depends(require_role("retailer"))):
    supplier_ids = {i.supplier_id for i in body.items}
    frozen = await db.users.find({"id": {"$in": list(supplier_ids)}, "billing_frozen": True}, {"_id": 0}).to_list(100)
    if frozen:
        names = ", ".join(f.get("business_name", "supplier") for f in frozen)
        raise HTTPException(403, f"Cannot place order: {names} is temporarily frozen due to overdue commission billing.")
    settings = await get_settings()
    online = body.payment_method == "online"
    grand_total = round(sum(i.unit_price * i.quantity for i in body.items), 2)
    charge_id = None
    if online:
        if not user.get("card_verified"):
            raise HTTPException(400, "Add a verified payment card before paying online.")
        try:
            charge_id = simulate_charge(user.get("card_sim_status", "ok"), grand_total)
        except CardError as e:
            raise HTTPException(402, f"Payment failed: {e}")
    created = []
    for sid in supplier_ids:
        items = [i for i in body.items if i.supplier_id == sid]
        total = round(sum(i.unit_price * i.quantity for i in items), 2)
        supplier = await db.users.find_one({"id": sid})
        fee = compute_fee(total, settings)
        payer = settings["fee_payer"]
        oid = str(uuid.uuid4())
        order = {
            "id": oid, "order_no": "ORD-" + oid[:8].upper(),
            "retailer_id": user["id"], "retailer_name": user["business_name"],
            "retailer_tax_id": user.get("identification_number", ""),
            "retailer_establishment": user.get("establishment_type", ""),
            "supplier_id": sid, "supplier_name": supplier["business_name"] if supplier else "Supplier",
            "supplier_tax_id": supplier.get("identification_number", "") if supplier else "",
            "items": [i.model_dump() for i in items], "total": total,
            "service_fee": fee, "fee_payer": payer, "fee_type": settings["fee_type"], "fee_value": settings["fee_value"],
            "status": "Pending", "delivery_address": body.delivery_address,
            "notes": body.notes or "", "delivery_window": body.delivery_window or "",
            "payment_method": body.payment_method or "cash",
            "timeline": [{"status": "Pending", "at": now_iso()}],
            "created_at": now_iso(), "updated_at": now_iso(),
        }
        if online:
            payout = round(total - fee, 2)
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
        # decrement stock
        for i in items:
            await db.products.update_one({"id": i.product_id}, {"$inc": {"stock": -i.quantity}})
        if online:
            await notify(sid, f"New PAID order {order['order_no']} from {user['business_name']} (₾{total:.2f}) — payout ₾{order['supplier_payout']:.2f} after ₾{fee:.2f} commission", "order")
        else:
            await notify(sid, f"New order {order['order_no']} from {user['business_name']} (₾{total:.2f})", "order")
        created.append(clean(order))
    return {"orders": created, "paid": online, "charged": grand_total if online else 0}

@api.get("/orders")
async def list_orders(user: dict = Depends(get_current_user)):
    if user["role"] == "retailer":
        q = {"retailer_id": user["id"]}
    elif user["role"] == "supplier":
        q = {"supplier_id": user["id"]}
    else:
        q = {}
    docs = await db.orders.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    for d in docs:
        d.setdefault("payment_method", "cash")
    return docs

VALID_STATUS = ["Pending", "Processing", "In Transit", "Delivered", "Cancelled"]

@api.put("/orders/{oid}/status")
async def update_order_status(oid: str, body: StatusUpdate, user: dict = Depends(get_current_user)):
    order = await db.orders.find_one({"id": oid})
    if not order:
        raise HTTPException(404, "Order not found")
    if body.status not in VALID_STATUS:
        raise HTTPException(400, "Invalid status")
    # supplier owns status transitions; retailer may only cancel own pending order
    if user["role"] == "supplier":
        if order["supplier_id"] != user["id"]:
            raise HTTPException(404, "Order not found")
        if user.get("billing_frozen") and body.status != "Cancelled":
            raise HTTPException(403, "Account frozen due to an overdue commission invoice. Settle the outstanding invoice to resume accepting orders.")
    elif user["role"] == "retailer":
        if order["retailer_id"] != user["id"] or body.status != "Cancelled":
            raise HTTPException(403, "Not allowed")
    elif user["role"] != "admin":
        raise HTTPException(403, "Not allowed")
    tl = order.get("timeline", [])
    tl.append({"status": body.status, "at": now_iso()})
    set_fields = {"status": body.status, "updated_at": now_iso(), "timeline": tl}
    if body.status == "Delivered" and not order.get("delivered_at"):
        set_fields["delivered_at"] = now_iso()
        set_fields["commission_amount"] = order.get("service_fee", round(order.get("total", 0) * 0.05, 2))
    await db.orders.update_one({"id": oid}, {"$set": set_fields})
    # notify the other party
    target = order["retailer_id"] if user["role"] != "retailer" else order["supplier_id"]
    await notify(target, f"Order {order['order_no']} is now {body.status}", "status")
    updated = await db.orders.find_one({"id": oid}, {"_id": 0})
    return updated


# ---------- analytics ----------
@api.get("/analytics/supplier")
async def supplier_analytics(user: dict = Depends(require_role("supplier"))):
    orders = await db.orders.find({"supplier_id": user["id"]}, {"_id": 0}).to_list(1000)
    products = await db.products.find({"supplier_id": user["id"]}, {"_id": 0}).to_list(500)
    today = datetime.now(timezone.utc).date().isoformat()
    revenue = sum(o["total"] for o in orders if o["status"] != "Cancelled")
    daily = sum(o["total"] for o in orders if o["created_at"][:10] == today and o["status"] != "Cancelled")
    active = len([o for o in orders if o["status"] in ("Pending", "Processing", "In Transit")])
    low_stock = [p for p in products if p["stock"] < 50]
    # popular items
    counts = {}
    for o in orders:
        for i in o["items"]:
            counts[i["name"]] = counts.get(i["name"], 0) + i["quantity"]
    popular = sorted([{"name": k, "qty": v} for k, v in counts.items()], key=lambda x: -x["qty"])[:5]
    # last 7 days series
    series = []
    for d in range(6, -1, -1):
        day = (datetime.now(timezone.utc) - timedelta(days=d)).date().isoformat()
        amt = sum(o["total"] for o in orders if o["created_at"][:10] == day and o["status"] != "Cancelled")
        series.append({"day": day[5:], "sales": round(amt, 2)})
    return {"revenue": round(revenue, 2), "daily": round(daily, 2), "active_orders": active,
            "total_orders": len(orders), "product_count": len(products),
            "low_stock": low_stock, "popular": popular, "series": series}

@api.get("/analytics/admin")
async def admin_analytics(user: dict = Depends(require_role("admin"))):
    orders = await db.orders.find({}, {"_id": 0}).to_list(2000)
    users = await db.users.find({}, {"_id": 0, "password_hash": 0}).to_list(1000)
    gmv = sum(o["total"] for o in orders if o["status"] != "Cancelled")
    delivered = len([o for o in orders if o["status"] == "Delivered"])
    fulfillment = round((delivered / len(orders) * 100), 1) if orders else 0
    fee_revenue = sum(o.get("service_fee", round(o["total"] * 0.05, 2)) for o in orders if o["status"] != "Cancelled")
    return {"gmv": round(gmv, 2), "total_orders": len(orders), "fulfillment_rate": fulfillment,
            "fee_revenue": round(fee_revenue, 2),
            "retailers": len([u for u in users if u["role"] == "retailer"]),
            "suppliers": len([u for u in users if u["role"] == "supplier"]),
            "pending_suppliers": len([u for u in users if u["role"] == "supplier" and u.get("status") == "pending"])}


# ---------- admin user mgmt ----------
@api.get("/admin/users")
async def admin_users(role: Optional[str] = None, user: dict = Depends(require_role("admin"))):
    q = {} if not role or role == "all" else {"role": role}
    return await db.users.find(q, {"_id": 0, "password_hash": 0}).sort("created_at", -1).to_list(1000)

@api.put("/admin/users/{uid}/status")
async def set_user_status(uid: str, body: StatusUpdate, user: dict = Depends(require_role("admin"))):
    if body.status not in ("active", "pending", "suspended"):
        raise HTTPException(400, "Invalid status")
    res = await db.users.update_one({"id": uid}, {"$set": {"status": body.status}})
    if res.matched_count == 0:
        raise HTTPException(404, "User not found")
    await notify(uid, f"Your account status is now {body.status}", "account")
    return {"ok": True}


# ---------- messaging ----------
@api.get("/contacts")
async def contacts(user: dict = Depends(get_current_user)):
    # people this user has transacted with
    if user["role"] == "retailer":
        orders = await db.orders.find({"retailer_id": user["id"]}, {"_id": 0}).to_list(500)
        ids = {o["supplier_id"] for o in orders}
    elif user["role"] == "supplier":
        orders = await db.orders.find({"supplier_id": user["id"]}, {"_id": 0}).to_list(500)
        ids = {o["retailer_id"] for o in orders}
    else:
        us = await db.users.find({"id": {"$ne": user["id"]}}, {"_id": 0, "password_hash": 0}).to_list(100)
        return us
    us = await db.users.find({"id": {"$in": list(ids)}}, {"_id": 0, "password_hash": 0}).to_list(200)
    return us

@api.get("/messages/{other_id}")
async def get_messages(other_id: str, user: dict = Depends(get_current_user)):
    msgs = await db.messages.find({
        "$or": [{"from_id": user["id"], "to_id": other_id}, {"from_id": other_id, "to_id": user["id"]}]
    }, {"_id": 0}).sort("created_at", 1).to_list(500)
    await db.messages.update_many({"from_id": other_id, "to_id": user["id"], "read": False}, {"$set": {"read": True}})
    return msgs

@api.post("/messages")
async def send_message(body: MessageIn, user: dict = Depends(get_current_user)):
    msg = {"id": str(uuid.uuid4()), "from_id": user["id"], "from_name": user["business_name"],
           "to_id": body.to_id, "text": body.text, "order_id": body.order_id or "",
           "read": False, "created_at": now_iso()}
    await db.messages.insert_one(dict(msg))
    await notify(body.to_id, f"New message from {user['business_name']}", "message")
    return clean(msg)


# ---------- notifications ----------
@api.get("/notifications")
async def get_notifications(user: dict = Depends(get_current_user)):
    return await db.notifications.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(100)

@api.post("/notifications/read")
async def read_notifications(user: dict = Depends(get_current_user)):
    await db.notifications.update_many({"user_id": user["id"]}, {"$set": {"read": True}})
    return {"ok": True}


# ---------- profile ----------
@api.put("/profile")
async def update_profile(body: ProfileIn, user: dict = Depends(get_current_user)):
    upd = {k: v for k, v in body.model_dump().items() if v is not None}
    if "card_number" in upd:
        num = upd.pop("card_number")
        if num:
            upd["card_last4"] = mask_card(num)
    await db.users.update_one({"id": user["id"]}, {"$set": upd})
    return await db.users.find_one({"id": user["id"]}, {"_id": 0, "password_hash": 0})


# ---------- platform settings (service fee) ----------
@api.get("/settings")
async def read_settings(user: dict = Depends(get_current_user)):
    return await get_settings()

@api.put("/admin/settings")
async def write_settings(body: SettingsIn, user: dict = Depends(require_role("admin"))):
    if body.fee_type not in ("percent", "fixed"):
        raise HTTPException(400, "Invalid fee type")
    if body.fee_payer not in ("supplier", "retailer", "split"):
        raise HTTPException(400, "Invalid fee payer")
    upd = {"fee_type": body.fee_type, "fee_value": body.fee_value, "fee_payer": body.fee_payer}
    for k in ("issuer_name", "issuer_tax_id", "issuer_iban"):
        v = getattr(body, k)
        if v is not None:
            upd[k] = v
    await db.settings.update_one({"id": "platform"}, {"$set": upd}, upsert=True)
    return await get_settings()


# ---------- categories ----------
@api.get("/categories")
async def list_categories():
    cats = await db.categories.find({}, {"_id": 0}).sort("name", 1).to_list(200)
    return [c["name"] for c in cats]

@api.post("/categories")
async def add_category(body: CategoryIn, user: dict = Depends(get_current_user)):
    if user["role"] not in ("admin", "supplier"):
        raise HTTPException(403, "Not allowed")
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Name required")
    if not await db.categories.find_one({"name": name}):
        await db.categories.insert_one({"id": str(uuid.uuid4()), "name": name})
    return await list_categories()


# ---------- commission billing & financials ----------
ISSUER_DEFAULTS = {"issuer_name": "Distro Logistics LLC", "issuer_tax_id": "400123456",
                   "issuer_iban": "GE00DL0000000000001234"}


def _month_bounds(year, month):
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    nxt = datetime(year + 1, 1, 1, tzinfo=timezone.utc) if month == 12 else datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, nxt, start.strftime("%B %Y"), f"{year:04d}-{month:02d}"


def _prev_month(dt):
    return (dt.year - 1, 12) if dt.month == 1 else (dt.year, dt.month - 1)


def _fmt(dt):
    return dt.strftime("%d %b %Y")


def order_commission(o):
    return round(float(o.get("commission_amount", o.get("service_fee", round(o.get("total", 0) * 0.05, 2)))), 2)


def effective_status(inv):
    if inv.get("status") == "paid":
        return "paid"
    try:
        due = datetime.fromisoformat(inv["due_date"])
    except Exception:
        return inv.get("status", "pending")
    return "overdue" if datetime.now(timezone.utc) > due else "pending"


async def recompute_freeze(supplier_id):
    invs = await db.invoices.find({"supplier_id": supplier_id}, {"_id": 0}).to_list(500)
    frozen = any(effective_status(i) == "overdue" for i in invs)
    await db.users.update_one({"id": supplier_id}, {"$set": {"billing_frozen": frozen}})
    return frozen


async def do_generate_invoices(period=None):
    settings = await get_settings()
    issuer = {k: settings.get(k, ISSUER_DEFAULTS[k]) for k in ISSUER_DEFAULTS}
    now = datetime.now(timezone.utc)
    if period:
        y, m = int(period[:4]), int(period[5:7])
    else:
        y, m = _prev_month(now)
    start, nxt, label, period_str = _month_bounds(y, m)
    issue_dt = now
    due_dt = issue_dt + timedelta(days=5)
    created = []
    suppliers = await db.users.find({"role": "supplier"}, {"_id": 0, "password_hash": 0}).to_list(1000)
    for sup in suppliers:
        if await db.invoices.find_one({"supplier_id": sup["id"], "period": period_str}):
            continue
        orders = await db.orders.find({"supplier_id": sup["id"], "status": "Delivered",
            "delivered_at": {"$gte": start.isoformat(), "$lt": nxt.isoformat()}}, {"_id": 0}).to_list(5000)
        orders = [o for o in orders if not o.get("invoice_id") and not o.get("paid_at_checkout")]
        if not orders:
            continue
        line_items, amount, sales = [], 0.0, 0.0
        for o in orders:
            c = order_commission(o)
            amount += c
            sales += float(o.get("total", 0))
            line_items.append({"order_no": o["order_no"], "date": (o.get("delivered_at") or "")[:10],
                               "order_total": round(float(o.get("total", 0)), 2), "commission": c})
        iid = str(uuid.uuid4())
        inv = {"id": iid, "invoice_no": f"INV-{period_str.replace('-', '')}-{iid[:4].upper()}",
               "supplier_id": sup["id"], "supplier_name": sup.get("business_name", ""),
               "supplier_tax_id": sup.get("identification_number", ""), "supplier_email": sup.get("email", ""),
               "period": period_str, "period_label": label,
               "line_items": line_items, "order_count": len(orders),
               "total_sales": round(sales, 2), "amount": round(amount, 2), "currency": "GEL",
               "status": "pending", "issue_date": issue_dt.isoformat(), "issue_label": _fmt(issue_dt),
               "due_date": due_dt.isoformat(), "due_label": _fmt(due_dt), "paid_at": None,
               **issuer, "created_at": now_iso()}
        await db.invoices.insert_one(dict(inv))
        await db.orders.update_many({"id": {"$in": [o["id"] for o in orders]}}, {"$set": {"invoice_id": iid}})
        await notify(sup["id"], f"New commission invoice {inv['invoice_no']} ({label}) — ₾{inv['amount']:.2f}, due {inv['due_label']}", "billing")
        if sup.get("email"):
            await try_send_email(to=sup["email"], subject=f"Your Distro Logistics commission invoice {inv['invoice_no']}",
                                 html=invoice_email_html(inv))
        created.append(inv["invoice_no"])
    return created


async def do_billing_check():
    now = datetime.now(timezone.utc)
    invs = await db.invoices.find({"status": {"$ne": "paid"}}, {"_id": 0}).to_list(2000)
    reminded, overdue_sups = [], set()
    for inv in invs:
        if effective_status(inv) != "overdue":
            continue
        overdue_sups.add(inv["supplier_id"])
        if inv.get("reminded_on") != now.date().isoformat():
            sup = await db.users.find_one({"id": inv["supplier_id"]}, {"_id": 0})
            if sup and sup.get("email"):
                await try_send_email(to=sup["email"], subject=f"Overdue: commission invoice {inv['invoice_no']}",
                                     html=reminder_email_html(inv))
            await db.invoices.update_one({"id": inv["id"]}, {"$set": {"reminded_on": now.date().isoformat()}})
            await notify(inv["supplier_id"], f"Invoice {inv['invoice_no']} is overdue. New order acceptance is paused until paid.", "billing")
            reminded.append(inv["invoice_no"])
    all_sups = await db.users.find({"role": "supplier"}, {"_id": 0}).to_list(1000)
    for sup in all_sups:
        await db.users.update_one({"id": sup["id"]}, {"$set": {"billing_frozen": sup["id"] in overdue_sups}})
    return reminded


@api.get("/invoices")
async def list_invoices(status: Optional[str] = None, supplier_id: Optional[str] = None, user: dict = Depends(get_current_user)):
    if user["role"] == "supplier":
        q = {"supplier_id": user["id"]}
    elif user["role"] == "admin":
        q = {"supplier_id": supplier_id} if supplier_id else {}
    else:
        raise HTTPException(403, "Not allowed")
    invs = await db.invoices.find(q, {"_id": 0}).sort("created_at", -1).to_list(2000)
    for i in invs:
        i["effective_status"] = effective_status(i)
    if status and status != "all":
        invs = [i for i in invs if i["effective_status"] == status]
    return invs


@api.get("/invoices/{iid}/pdf")
async def invoice_pdf(iid: str, user: dict = Depends(get_current_user)):
    inv = await db.invoices.find_one({"id": iid}, {"_id": 0})
    if not inv:
        raise HTTPException(404, "Invoice not found")
    if user["role"] == "retailer":
        raise HTTPException(403, "Not allowed")
    if user["role"] == "supplier" and inv["supplier_id"] != user["id"]:
        raise HTTPException(404, "Invoice not found")
    pdf = build_invoice_pdf(inv)
    return StreamingResponse(io.BytesIO(pdf), media_type="application/pdf",
                             headers={"Content-Disposition": f'inline; filename="{inv["invoice_no"]}.pdf"'})


@api.put("/admin/invoices/{iid}/paid")
async def mark_invoice_paid(iid: str, user: dict = Depends(require_role("admin"))):
    inv = await db.invoices.find_one({"id": iid}, {"_id": 0})
    if not inv:
        raise HTTPException(404, "Invoice not found")
    await db.invoices.update_one({"id": iid}, {"$set": {"status": "paid", "paid_at": now_iso()}})
    await recompute_freeze(inv["supplier_id"])
    await notify(inv["supplier_id"], f"Invoice {inv['invoice_no']} has been marked as paid. Thank you!", "billing")
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
    await notify(inv["supplier_id"], f"Payment reminder sent for invoice {inv['invoice_no']}.", "billing")
    return {"sent": sent, "email": sup.get("email") if sup else ""}


@api.post("/admin/invoices/generate")
async def admin_generate_invoices(user: dict = Depends(require_role("admin"))):
    created = await do_generate_invoices()
    return {"created": created, "count": len(created)}


@api.get("/admin/financials")
async def admin_financials(user: dict = Depends(require_role("admin"))):
    now = datetime.now(timezone.utc)
    cs, cn, clabel, _ = _month_bounds(now.year, now.month)
    suppliers = await db.users.find({"role": "supplier"}, {"_id": 0, "password_hash": 0}).to_list(1000)
    invs_all = await db.invoices.find({}, {"_id": 0}).sort("created_at", -1).to_list(3000)
    rows = []
    tot_outstanding = tot_accrued = tot_collected = 0.0
    for sup in suppliers:
        s_invs = [i for i in invs_all if i["supplier_id"] == sup["id"]]
        for i in s_invs:
            i["effective_status"] = effective_status(i)
        cur = await db.orders.find({"supplier_id": sup["id"], "status": "Delivered",
            "delivered_at": {"$gte": cs.isoformat(), "$lt": cn.isoformat()}}, {"_id": 0}).to_list(5000)
        cur = [o for o in cur if not o.get("invoice_id") and not o.get("paid_at_checkout")]
        accrued = round(sum(order_commission(o) for o in cur), 2)
        month_sales = round(sum(float(o.get("total", 0)) for o in cur), 2)
        chk = await db.orders.find({"supplier_id": sup["id"], "paid_at_checkout": True,
            "created_at": {"$gte": cs.isoformat(), "$lt": cn.isoformat()}}, {"_id": 0}).to_list(5000)
        checkout_collected = round(sum(order_commission(o) for o in chk), 2)
        outstanding = round(sum(i["amount"] for i in s_invs if i["effective_status"] != "paid"), 2)
        collected = round(sum(i["amount"] for i in s_invs if i["effective_status"] == "paid") + checkout_collected, 2)
        tot_outstanding += outstanding
        tot_accrued += accrued
        tot_collected += collected
        rows.append({"supplier_id": sup["id"], "supplier_name": sup.get("business_name", ""),
                     "email": sup.get("email", ""), "tax_id": sup.get("identification_number", ""),
                     "frozen": bool(sup.get("billing_frozen")), "month_sales": month_sales,
                     "accrued_commission": accrued, "checkout_collected": checkout_collected,
                     "outstanding": outstanding, "collected": collected,
                     "invoices": s_invs})
    return {"period_label": clabel, "suppliers": rows,
            "totals": {"outstanding": round(tot_outstanding, 2), "accrued": round(tot_accrued, 2),
                       "collected": round(tot_collected, 2)}}


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


def _card_public(u: dict):
    if not u.get("card_verified"):
        return None
    return {"brand": u.get("card_brand", "card"), "last4": u.get("card_last4", ""),
            "exp": u.get("card_expiry", ""), "name": u.get("card_name", ""), "verified": True}


@api.post("/payments/cards")
async def add_card(body: CardIn, user: dict = Depends(get_current_user)):
    try:
        info = validate_card(body.number, body.exp, body.cvc)
    except CardError as e:
        raise HTTPException(400, str(e))
    try:
        simulate_hold(info["sim_status"], 1.0)  # 1 GEL validation hold, released immediately
    except CardError as e:
        raise HTTPException(402, f"Card validation failed: {e}")
    upd = {"card_token": gen_token(), "card_brand": info["brand"], "card_last4": info["last4"],
           "card_expiry": info["exp"], "card_name": body.name or user.get("card_name", ""),
           "card_verified": True, "card_sim_status": info["sim_status"]}
    await db.users.update_one({"id": user["id"]}, {"$set": upd})
    return {"card": _card_public({**user, **upd})}


@api.get("/payments/cards")
async def get_card(user: dict = Depends(get_current_user)):
    return {"card": _card_public(user)}


@api.delete("/payments/cards")
async def delete_card(user: dict = Depends(get_current_user)):
    await db.users.update_one({"id": user["id"]}, {"$set": {"card_verified": False, "card_token": "", "card_sim_status": ""}})
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
            await notify(inv["supplier_id"], f"Auto-debit failed for invoice {inv['invoice_no']}. Please update your card or pay manually.", "billing")
            continue
        await db.invoices.update_one({"id": inv["id"]}, {"$set": {"status": "paid", "paid_at": now_iso(),
                                                                  "payment_ref": ref, "auto_debited": True}})
        await recompute_freeze(inv["supplier_id"])
        await notify(inv["supplier_id"], f"Invoice {inv['invoice_no']} (₾{inv['amount']:.2f}) was auto-debited from your saved card.", "billing")
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


app.include_router(api)
app.add_middleware(CORSMiddleware, allow_credentials=False, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup():
    await db.users.create_index("email", unique=True)
    await db.products.create_index("supplier_id")
    await db.orders.create_index("retailer_id")
    await db.orders.create_index("supplier_id")
    await seed_data(db, hash_password)
    await get_settings()
    if await db.categories.count_documents({}) == 0:
        for c in ["Beverages", "Groceries", "Snacks & Sweets", "Dry Goods", "Household Chemicals", "Packaging", "Hygiene"]:
            await db.categories.insert_one({"id": str(uuid.uuid4()), "name": c})

@app.on_event("shutdown")
async def shutdown():
    client.close()
