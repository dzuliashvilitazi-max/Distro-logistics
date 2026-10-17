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

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class TierPrice(BaseModel):
    min_qty: int
    price: float

class ProductIn(BaseModel):
    name: str
    category: str
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
    uid = str(uuid.uuid4())
    user = {
        "id": uid, "email": email, "password_hash": hash_password(body.password),
        "name": body.name, "role": body.role, "business_name": body.business_name or body.name,
        "address": body.address or "", "phone": "",
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
                        search: Optional[str] = None, availability: Optional[str] = None):
    q = {}
    if category and category not in ("All Products", "all"):
        q["category"] = category
    if supplier_id:
        q["supplier_id"] = supplier_id
    if search:
        q["name"] = {"$regex": search, "$options": "i"}
    if availability == "in_stock":
        q["stock"] = {"$gt": 0}
    docs = await db.products.find(q, {"_id": 0}).to_list(500)
    return docs

@api.post("/products")
async def create_product(body: ProductIn, user: dict = Depends(require_role("supplier"))):
    pid = str(uuid.uuid4())
    doc = {"id": pid, "supplier_id": user["id"], "supplier_name": user["business_name"],
           **body.model_dump(), "created_at": now_iso()}
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
    created = []
    for sid in supplier_ids:
        items = [i for i in body.items if i.supplier_id == sid]
        total = sum(i.unit_price * i.quantity for i in items)
        supplier = await db.users.find_one({"id": sid})
        oid = str(uuid.uuid4())
        order = {
            "id": oid, "order_no": "ORD-" + oid[:8].upper(),
            "retailer_id": user["id"], "retailer_name": user["business_name"],
            "supplier_id": sid, "supplier_name": supplier["business_name"] if supplier else "Supplier",
            "items": [i.model_dump() for i in items], "total": round(total, 2),
            "status": "Pending", "delivery_address": body.delivery_address,
            "notes": body.notes or "", "delivery_window": body.delivery_window or "",
            "timeline": [{"status": "Pending", "at": now_iso()}],
            "created_at": now_iso(), "updated_at": now_iso(),
        }
        await db.orders.insert_one(dict(order))
        # decrement stock
        for i in items:
            await db.products.update_one({"id": i.product_id}, {"$inc": {"stock": -i.quantity}})
        await notify(sid, f"New order {order['order_no']} from {user['business_name']} (${order['total']})", "order")
        created.append(clean(order))
    return {"orders": created}

@api.get("/orders")
async def list_orders(user: dict = Depends(get_current_user)):
    if user["role"] == "retailer":
        q = {"retailer_id": user["id"]}
    elif user["role"] == "supplier":
        q = {"supplier_id": user["id"]}
    else:
        q = {}
    docs = await db.orders.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
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
    elif user["role"] == "retailer":
        if order["retailer_id"] != user["id"] or body.status != "Cancelled":
            raise HTTPException(403, "Not allowed")
    elif user["role"] != "admin":
        raise HTTPException(403, "Not allowed")
    tl = order.get("timeline", [])
    tl.append({"status": body.status, "at": now_iso()})
    await db.orders.update_one({"id": oid}, {"$set": {"status": body.status, "updated_at": now_iso(), "timeline": tl}})
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
    return {"gmv": round(gmv, 2), "total_orders": len(orders), "fulfillment_rate": fulfillment,
            "fee_revenue": round(gmv * 0.05, 2),
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
    await db.users.update_one({"id": user["id"]}, {"$set": upd})
    return await db.users.find_one({"id": user["id"]}, {"_id": 0, "password_hash": 0})


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

@app.on_event("shutdown")
async def shutdown():
    client.close()
