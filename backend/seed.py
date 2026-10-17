import os
import uuid
from datetime import datetime, timezone, timedelta

def iso(days_ago=0):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()

SUPPLIERS = [
    {"email": "metro@distro.com", "name": "Metro Bev", "business_name": "Metro Bev Distributors", "address": "14 Dockside Ave, Port City"},
    {"email": "apex@distro.com", "name": "Apex Foods", "business_name": "Apex Food Group", "address": "88 Harvest Rd, Greenfield"},
    {"email": "snacknation@distro.com", "name": "SnackNation", "business_name": "SnackNation Wholesalers", "address": "5 Crunch Blvd, Midtown"},
]

RETAILERS = [
    {"email": "cornerstore@distro.com", "name": "Corner Store", "business_name": "Corner Store Market", "address": "22 Main St, Downtown"},
    {"email": "freshmart@distro.com", "name": "Fresh Mart", "business_name": "FreshMart Grocery", "address": "9 Elm Street, Uptown"},
]

PRODUCTS = [
    {"name": "Artisan Craft Soda (24-pack case)", "category": "Beverages", "s": 0, "price_per_unit": 18.50,
     "tier_pricing": [{"min_qty": 10, "price": 18.50}, {"min_qty": 50, "price": 16.20}, {"min_qty": 100, "price": 14.50}],
     "moq": 10, "stock": 450, "image": "https://images.pexels.com/photos/5532831/pexels-photo-5532831.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
     "description": "Small-batch artisan craft soda, assorted flavors. Case of 24."},
    {"name": "Craft Lager Crates Stack (24 Bottles)", "category": "Beverages", "s": 0, "price_per_unit": 38.00,
     "tier_pricing": [{"min_qty": 10, "price": 38.00}, {"min_qty": 40, "price": 33.50}, {"min_qty": 100, "price": 29.90}],
     "moq": 10, "stock": 620, "image": "https://images.pexels.com/photos/533353/pexels-photo-533353.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
     "description": "Premium craft lager, 24 glass bottles per crate."},
    {"name": "Organic Oat Milk - Barista Edition (12x1L)", "category": "Beverages", "s": 1, "price_per_unit": 32.00,
     "tier_pricing": [{"min_qty": 5, "price": 32.00}, {"min_qty": 25, "price": 28.50}, {"min_qty": 60, "price": 25.00}],
     "moq": 5, "stock": 280, "image": "https://images.unsplash.com/photo-1625865019845-7b2c89b8a8a9?crop=entropy&cs=srgb&fm=jpg&q=85",
     "description": "Barista-grade organic oat milk, 12 x 1L cartons."},
    {"name": "Whole Grain Pasta Bulk Sack (10kg)", "category": "Dry Goods", "s": 1, "price_per_unit": 24.00,
     "tier_pricing": [{"min_qty": 5, "price": 24.00}, {"min_qty": 20, "price": 21.00}, {"min_qty": 50, "price": 18.50}],
     "moq": 5, "stock": 40, "image": "https://images.unsplash.com/photo-1551462147-37885acc36f1?crop=entropy&cs=srgb&fm=jpg&q=85",
     "description": "Durum whole grain pasta, 10kg catering sack."},
    {"name": "Wholesale Chocolate Bars Variety Box (48 Count)", "category": "Snacks & Sweets", "s": 2, "price_per_unit": 42.90,
     "tier_pricing": [{"min_qty": 5, "price": 42.90}, {"min_qty": 20, "price": 38.00}, {"min_qty": 50, "price": 34.00}],
     "moq": 5, "stock": 120, "image": "https://images.unsplash.com/photo-1621939514649-280e2ee25f60?crop=entropy&cs=srgb&fm=jpg&q=85",
     "description": "Assorted premium chocolate bars, 48 per display box."},
    {"name": "Premium Potato Chips Display Box (36 Units)", "category": "Snacks & Sweets", "s": 2, "price_per_unit": 27.50,
     "tier_pricing": [{"min_qty": 10, "price": 27.50}, {"min_qty": 30, "price": 24.00}, {"min_qty": 100, "price": 21.00}],
     "moq": 10, "stock": 500, "image": "https://images.unsplash.com/photo-1688217170693-e821c6e18d72?crop=entropy&cs=srgb&fm=jpg&q=85",
     "description": "Kettle-cooked potato chips, 36-unit retail display box."},
    {"name": "Organic Basmati Rice (25kg)", "category": "Groceries", "s": 1, "price_per_unit": 46.00,
     "tier_pricing": [{"min_qty": 4, "price": 46.00}, {"min_qty": 16, "price": 41.00}, {"min_qty": 40, "price": 37.00}],
     "moq": 4, "stock": 90, "image": "https://images.unsplash.com/photo-1586201375761-83865001e31c?crop=entropy&cs=srgb&fm=jpg&q=85",
     "description": "Aged organic basmati rice, 25kg food-service bag."},
    {"name": "Sparkling Water Cans Bulk (48-pack)", "category": "Beverages", "s": 0, "price_per_unit": 21.00,
     "tier_pricing": [{"min_qty": 10, "price": 21.00}, {"min_qty": 50, "price": 18.00}, {"min_qty": 120, "price": 15.50}],
     "moq": 10, "stock": 30, "image": "https://images.pexels.com/photos/2983100/pexels-photo-2983100.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
     "description": "Zero-sugar sparkling water, 48 slim cans per case."},
]


async def seed_data(db, hash_password):
    if await db.users.count_documents({}) > 0:
        return
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@distro.com")
    admin_password = os.environ.get("ADMIN_PASSWORD", "Admin@123")

    await db.users.insert_one({
        "id": str(uuid.uuid4()), "email": admin_email.lower(), "password_hash": hash_password(admin_password),
        "name": "Platform Admin", "role": "admin", "business_name": "Distro Logistics HQ",
        "address": "1 Logistics Plaza", "phone": "", "status": "active", "created_at": iso(30),
    })

    sup_ids = []
    for s in SUPPLIERS:
        sid = str(uuid.uuid4())
        sup_ids.append(sid)
        await db.users.insert_one({
            "id": sid, "email": s["email"], "password_hash": hash_password("Password@123"),
            "name": s["name"], "role": "supplier", "business_name": s["business_name"],
            "address": s["address"], "phone": "+995-555-0100",
            "city": ["Tbilisi", "Batumi", "Kutaisi"][SUPPLIERS.index(s) % 3],
            "identification_number": "20500" + str(SUPPLIERS.index(s) + 1).zfill(4),
            "bank_name": ["TBC Bank", "Bank of Georgia", "Liberty Bank"][SUPPLIERS.index(s) % 3],
            "iban": "GE29TB00000" + str(100000 + SUPPLIERS.index(s)),
            "status": "active", "created_at": iso(25),
        })
    # one pending supplier for admin approval queue
    pending_id = str(uuid.uuid4())
    await db.users.insert_one({
        "id": pending_id, "email": "newdist@distro.com", "password_hash": hash_password("Password@123"),
        "name": "New Distributor", "role": "supplier", "business_name": "Coastal Goods Supply",
        "address": "77 Pier Lane", "phone": "", "city": "Batumi",
        "identification_number": "205099999", "bank_name": "TBC Bank", "iban": "GE29TB00000999999",
        "status": "pending", "created_at": iso(1),
    })

    ret_ids = []
    for r in RETAILERS:
        rid = str(uuid.uuid4())
        ret_ids.append(rid)
        await db.users.insert_one({
            "id": rid, "email": r["email"], "password_hash": hash_password("Password@123"),
            "name": r["name"], "role": "retailer", "business_name": r["business_name"],
            "address": r["address"], "phone": "+995-555-0200",
            "city": ["Tbilisi", "Kutaisi"][RETAILERS.index(r) % 2],
            "identification_number": "0102" + str(RETAILERS.index(r) + 1).zfill(7),
            "establishment_type": ["grocery", "horeca"][RETAILERS.index(r) % 2],
            "card_name": r["name"], "card_last4": "4242", "card_expiry": "12/27",
            "status": "active", "created_at": iso(20),
        })

    prod_docs = []
    for p in PRODUCTS:
        pid = str(uuid.uuid4())
        sid = sup_ids[p["s"]]
        doc = {"id": pid, "supplier_id": sid, "supplier_name": SUPPLIERS[p["s"]]["business_name"],
               "name": p["name"], "category": p["category"], "price_per_unit": p["price_per_unit"],
               "city": ["Tbilisi", "Batumi", "Kutaisi"][p["s"] % 3],
               "tier_pricing": p["tier_pricing"], "moq": p["moq"], "stock": p["stock"],
               "image": p["image"], "description": p["description"], "created_at": iso(18)}
        prod_docs.append(doc)
        await db.products.insert_one(dict(doc))

    # sample orders
    statuses = ["Delivered", "In Transit", "Processing", "Pending", "Delivered", "Cancelled"]
    for n in range(6):
        prod = prod_docs[n % len(prod_docs)]
        rid = ret_ids[n % len(ret_ids)]
        ret = RETAILERS[n % len(RETAILERS)]
        qty = prod["moq"] * (2 + n)
        tier = prod["tier_pricing"]
        price = tier[0]["price"]
        for t in tier:
            if qty >= t["min_qty"]:
                price = t["price"]
        oid = str(uuid.uuid4())
        status = statuses[n]
        payment = ["cash", "card", "consignment"][n % 3]
        tl = [{"status": "Pending", "at": iso(10 - n)}]
        for st in ["Processing", "In Transit", "Delivered"]:
            if ["Pending", "Processing", "In Transit", "Delivered"].index(st) <= ["Pending", "Processing", "In Transit", "Delivered", "Cancelled"].index(status) if status != "Cancelled" else False:
                tl.append({"status": st, "at": iso(9 - n)})
        await db.orders.insert_one({
            "id": oid, "order_no": "ORD-" + oid[:8].upper(),
            "retailer_id": rid, "retailer_name": ret["business_name"],
            "supplier_id": prod["supplier_id"], "supplier_name": prod["supplier_name"],
            "items": [{"product_id": prod["id"], "name": prod["name"], "image": prod["image"],
                       "supplier_id": prod["supplier_id"], "quantity": qty, "unit_price": price}],
            "total": round(price * qty, 2), "status": status,
            "delivery_address": ret["address"], "notes": "Deliver to rear loading dock.",
            "delivery_window": "9am - 12pm", "payment_method": payment, "timeline": tl,
            "created_at": iso(10 - n), "updated_at": iso(8 - n),
        })

    # sample messages between first retailer and first supplier
    await db.messages.insert_one({"id": str(uuid.uuid4()), "from_id": ret_ids[0], "from_name": RETAILERS[0]["business_name"],
                                  "to_id": sup_ids[0], "text": "Hi, can you confirm the lead time on the craft soda order?", "order_id": "",
                                  "read": True, "created_at": iso(3)})
    await db.messages.insert_one({"id": str(uuid.uuid4()), "from_id": sup_ids[0], "from_name": SUPPLIERS[0]["business_name"],
                                  "to_id": ret_ids[0], "text": "Hello! Lead time is 2 business days. Shipping tomorrow.", "order_id": "",
                                  "read": False, "created_at": iso(2)})
