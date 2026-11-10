"""Automatic product/category image assignment.

Images come from the Pixabay API (Pixabay Content License, free commercial use), are validated, resized and uploaded to Cloudinary (local disk at PRODUCT_IMAGE_DIR is only the fallback when Cloudinary is not
configured), so nothing is hot-linked. A photo is only
accepted when its description matches the product with enough confidence; otherwise the frontend shows a
category-specific placeholder. Manually provided images are never overwritten.
"""
import asyncio
import base64
import hashlib
import io
import ipaddress
import logging
import os
import re
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from PIL import Image, UnidentifiedImageError

from product_media import is_generated_placeholder, is_missing_media

logger = logging.getLogger(__name__)

IMAGE_DIR = Path(os.environ.get("PRODUCT_IMAGE_DIR") or Path(__file__).parent / "uploads" / "products")
URL_PREFIX = "/product-images/"
FILE_RE = re.compile(r"^[a-f0-9]{32}\.jpg$")
IMAGE_HOSTS = {"pixabay.com", "cdn.pixabay.com"}
MAX_BYTES = 5 * 1024 * 1024
MAX_SIDE = 800
MAX_ATTEMPTS = 5
CACHE_DAYS = 30
THRESHOLD_PRODUCT = 0.6
THRESHOLD_CATEGORY = 0.5
PLACEHOLDER_REGEX = r"loremflickr\.com|images\.unsplash\.com/photo-(1554866585|1549007994|1563245372|1540420773|1550583724|1509440159|1607623814|1542838132)"
MISSING_VALUES = [None, "", "null", "none", "undefined"]

_STOP = {
    "the", "and", "for", "with", "pcs", "pack", "box", "ml", "kg", "gr", "gram", "grams", "lt", "cm", "mm",
    "new", "set", "mix", "pro", "max", "big", "small",
}

# Georgian/English product vocabulary -> English search phrase. Longest keys are matched first.
_VOCAB = {
    # brands
    "კოკაკოლა": "coca cola", "ფანტა": "fanta", "სპრაით": "sprite", "პეპსი": "pepsi", "სნიკერს": "snickers chocolate bar",
    "ბორჯომ": "borjomi mineral water", "ნაბეღლავ": "mineral water", "მარს": "mars chocolate bar",
    # food and drink
    "მინერალური წყალი": "mineral water", "წყალი": "mineral water", "წვენ": "juice", "ლიმონად": "lemonade",
    "კოლა": "cola", "ლუდ": "beer", "ღვინ": "wine", "არაყ": "vodka", "ვისკი": "whisky", "ყავა": "coffee",
    "ჩაი": "tea", "შოკოლად": "chocolate", "კანფეტ": "candy", "ვაფლ": "wafer", "ნამცხვარ": "cake",
    "ორცხობილ": "biscuits", "ბისკვიტ": "biscuits", "ჩიფს": "potato chips", "სნექ": "snacks", "ხინკალ": "dumplings",
    "პელმენ": "dumplings", "პილმენ": "dumplings", "ხორც": "meat", "ქათამ": "chicken", "ძეხვ": "sausage",
    "თევზ": "fish", "რძე": "milk", "იოგურტ": "yogurt", "ყველ": "cheese", "კარაქ": "butter", "კვერც": "eggs",
    "პური": "bread", "ფქვილ": "flour", "შაქარ": "sugar", "მარილ": "salt", "ზეთი": "cooking oil",
    "ბრინჯ": "rice", "მაკარონ": "pasta", "ბურღულ": "cereal grains", "ხილი": "fruit", "ვაშლ": "apple",
    "ბანან": "banana", "ბოსტნეულ": "vegetables", "პომიდორ": "tomato", "კიტრ": "cucumber",
    "კარტოფილ": "potato", "მაიონეზ": "mayonnaise", "კეტჩუპ": "ketchup", "თაფლ": "honey", "ხაჭო": "cottage cheese",
    # household and hygiene
    "საპონ": "soap", "შამპუნ": "shampoo", "კბილის პასტა": "toothpaste", "სარეცხი მანქანა": "washing machine",
    "სარეცხ": "laundry detergent", "ფხვნილ": "washing powder", "გამწმენდ": "cleaning supplies",
    "ტუალეტის ქაღალდ": "toilet paper", "ქაღალდ": "paper", "სალფეტ": "napkins", "საფენ": "diapers",
    "ჭურჭ": "dishes", "ცოცხ": "broom", "ხელთათმან": "gloves", "პარკ": "plastic bags", "კოლოფ": "cardboard box",
    "სკოჩ": "packing tape", "კრემ": "cream", "პარფიუმ": "perfume", "მაკიაჟ": "makeup", "ბალზამ": "hair conditioner",
    # electronics
    "ტელეფონ": "smartphone", "დამტენ": "phone charger", "ყურსასმენ": "headphones", "კაბელ": "cable",
    "ლეპტოპ": "laptop", "ტელევიზორ": "television", "მაცივარ": "refrigerator", "ბატარე": "batteries",
    "ნათურ": "light bulb", "პლანშეტ": "tablet", "კლავიატურ": "keyboard", "პრინტერ": "printer",
    # clothing
    "სპორტული ფეხსაცმელ": "sneakers", "ფეხსაცმელ": "shoes", "მაისურ": "t-shirt", "შარვალ": "trousers",
    "ჯინს": "jeans", "კაბა": "dress", "პალტო": "coat", "ქურთუკ": "jacket", "ჩექმ": "boots", "წინდ": "socks",
    "ჩანთ": "bag", "ქამარ": "belt", "ქუდ": "hat", "სათვალე": "sunglasses",
    # construction and tools
    "ცემენტ": "cement bag", "კაფელ": "ceramic tile", "ფილა": "ceramic tile", "აგური": "bricks", "ქვიშა": "sand",
    "ბათქაშ": "plaster", "საღებავ": "paint bucket", "ლამინატ": "laminate flooring", "ხრახნ": "screws",
    "ლურსმ": "nails", "ბურღ": "power drill", "ჩაქუჩ": "hammer", "ფიცარ": "wood planks", "სანტექნიკ": "plumbing",
    "ინსტრუმენტ": "tools",
    # furniture, auto, pets, baby, pharma
    "ავეჯ": "furniture", "დივან": "sofa", "მაგიდ": "table", "სკამ": "chair", "საწოლ": "bed", "კარადა": "wardrobe",
    "მატრას": "mattress", "საბურავ": "car tire", "აკუმულატორ": "car battery", "ძრავის ზეთ": "motor oil",
    "ძაღლ": "dog food", "კატ": "cat food", "ცხოველ": "pet supplies", "ბავშვ": "baby products",
    "ტაბლეტ": "medicine tablets", "მედიკამენტ": "medicine", "ვიტამინ": "vitamins", "ბინტ": "bandage",
    "ნიღაბ": "face mask", "თერმომეტრ": "thermometer",
    # stationery, agriculture, sport, music, flowers, print, toys
    "რვეულ": "notebook", "კალამ": "pen", "ფანქარ": "pencil", "მარკერ": "marker", "საქაღალდე": "folder",
    "სტეპლერ": "stapler", "თესლ": "seeds", "სასუქ": "fertilizer", "ტრაქტორ": "tractor", "ბურთ": "ball",
    "ჰანტელ": "dumbbell", "ველოსიპედ": "bicycle", "იოგა": "yoga mat", "გიტარ": "guitar", "ფორტეპიან": "piano",
    "ვიოლინ": "violin", "დრამ": "drums", "ყვავილ": "flowers", "ვარდ": "roses", "მცენარ": "houseplant",
    "ქოთან": "flower pot", "ბანერ": "banner", "ვიზიტ": "business cards", "ბუშტ": "balloons", "სათამაშო": "toy",
    "ნაძვ": "christmas tree", "საჩუქარ": "gift",
    # category labels (Georgian)
    "სასმელ": "beverages drinks", "სურსათი": "groceries", "სნექები და ტკბილეული": "snacks sweets",
    "ტკბილეული": "sweets", "მშრალი პროდუქტები": "dry goods", "ნახევარფაბრიკატ": "frozen food",
    "საყოფაცხოვრებო ქიმია": "cleaning supplies", "ჰიგიენა": "personal hygiene", "შეფუთვა": "packaging",
    "სამშენებლო": "construction materials", "ტექნიკა": "electronics", "ტანსაცმელი": "clothing",
    "ავტოპროდუქცია": "auto parts", "სამედიცინო": "medical supplies", "სოფლის მეურნეობა": "agriculture",
    "სილამაზე": "cosmetics", "კოსმეტიკა": "cosmetics", "სპორტი": "sports equipment", "პოლიგრაფია": "printing",
    "საკანცელარიო": "stationery", "საკონდიტრო": "pastry bakery",
}

# English category names used by the platform -> search phrase.
_CATEGORY_EN = {
    "beverages": "beverages drinks", "groceries": "groceries", "snacks & sweets": "snacks sweets",
    "dry goods": "dry goods pantry", "household chemicals": "cleaning supplies", "packaging": "packaging materials",
    "hygiene": "personal hygiene", "pet supplies": "pet supplies", "food": "food groceries",
    "alcoholic beverages": "alcoholic drinks bottles", "dairy": "dairy products", "meat": "meat",
    "fruits & vegetables": "fresh fruits vegetables", "cleaning supplies": "cleaning supplies",
    "personal care & cosmetics": "cosmetics personal care", "electronics": "electronics",
    "phones & accessories": "smartphone accessories", "clothing & fashion": "clothing fashion",
    "shoes & accessories": "shoes", "construction materials": "construction materials", "tools & equipment": "tools",
    "furniture & home goods": "furniture", "automotive products": "auto parts", "office & stationery": "stationery",
    "baby products": "baby products", "pharmaceuticals & health products": "medicine pharmacy",
    "agricultural products": "agriculture farm", "packaging materials": "packaging materials",
}

_VOCAB_KEYS = sorted(_VOCAB, key=len, reverse=True)


class ImageError(ValueError):
    pass


class ProviderBusy(Exception):
    """The image provider is rate limiting us; stop the current batch."""


def search_enabled() -> bool:
    return bool(os.environ.get("PIXABAY_API_KEY", "").strip())


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(text) -> str:
    return " ".join(str(text or "").casefold().replace("-", "").replace("_", " ").replace("&", " & ").split())


def _tokens(phrase: str) -> list:
    out = []
    for word in re.findall(r"[a-z]{3,}", phrase.casefold()):
        if word not in _STOP and word not in out:
            out.append(word)
    return out


def build_terms(name, category="", description="") -> dict:
    """Split a product into brand tokens, product-type tokens and category tokens (all English)."""
    remaining = _norm(name)
    type_phrases = []
    for key in _VOCAB_KEYS:
        if key in remaining:
            type_phrases.append(_VOCAB[key])
            remaining = remaining.replace(key, " ")
    # Latin words that are not vocabulary hits are treated as brand/product words.
    brand = _tokens(re.sub(r"[^a-z\s]", " ", remaining))
    type_tokens = []
    for phrase in type_phrases:
        for token in _tokens(phrase):
            if token not in type_tokens:
                type_tokens.append(token)
    category_text = _norm(category)
    category_phrases = [_CATEGORY_EN[category_text]] if category_text in _CATEGORY_EN else []
    if not category_phrases:
        category_phrases = [_VOCAB[key] for key in _VOCAB_KEYS if key in category_text][:2]
    category_tokens = []
    for phrase in category_phrases:
        for token in _tokens(phrase):
            if token not in category_tokens:
                category_tokens.append(token)
    if not category_tokens:
        category_tokens = [t for t in _tokens(category_text)][:3]
    return {"brand": brand[:3], "type": type_tokens[:4], "category": category_tokens[:4]}


def score_photo(alt: str, tokens: list) -> float:
    if not tokens or not alt:
        return 0.0
    text = _norm(alt)
    hits = sum(1 for token in tokens if token in text or (token.endswith("s") and token[:-1] in text))
    return hits / len(tokens)


def pick_photo(photos: list, tokens: list, excluded=(), uses=None):
    """Best photo by description match; mildly penalises photos already used by many products."""
    uses = uses or {}
    best, best_adjusted, best_raw = None, 0.0, 0.0
    for rank, photo in enumerate(photos):
        if photo["id"] in excluded:
            continue
        raw = score_photo(photo.get("alt", ""), tokens)
        if raw <= 0:
            continue
        adjusted = raw - 0.05 * min(uses.get(photo["id"], 0), 4) - rank * 0.002
        if adjusted > best_adjusted:
            best, best_adjusted, best_raw = photo, adjusted, raw
    return best, best_raw


def process_image(data: bytes) -> bytes:
    """Validate and re-encode as a size-limited progressive JPEG (drops metadata and embedded payloads)."""
    if not data:
        raise ImageError("Empty image")
    if len(data) > MAX_BYTES:
        raise ImageError("Image is larger than 5 MB")
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.format not in {"JPEG", "PNG", "WEBP"}:
                raise ImageError("Unsupported image type")
            img.load()
            img = img.convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ImageError("The file is not a valid image")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=82, optimize=True, progressive=True)
    return out.getvalue()


def store_image_bytes(jpeg: bytes) -> str:
    name = hashlib.sha256(jpeg).hexdigest()[:32] + ".jpg"
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    path = IMAGE_DIR / name
    if not path.exists():
        path.write_bytes(jpeg)
    return URL_PREFIX + name


def cloudinary_configured() -> bool:
    return all(os.environ.get(key, "").strip() for key in (
        "CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET"))


def _upload_to_cloudinary(jpeg: bytes) -> str:
    import cloudinary.uploader
    folder = os.environ.get("CLOUDINARY_FOLDER", "distro/products").strip("/")
    try:
        result = cloudinary.uploader.upload(
            io.BytesIO(jpeg),
            cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"].strip(),
            api_key=os.environ["CLOUDINARY_API_KEY"].strip(),
            api_secret=os.environ["CLOUDINARY_API_SECRET"].strip(),
            folder=folder, public_id=hashlib.sha256(jpeg).hexdigest()[:32],
            overwrite=False, unique_filename=False, resource_type="image",
        )
        return result["secure_url"]
    except Exception as error:  # SDK and network errors alike: the caller retries later
        raise ImageError(f"Cloud image upload failed ({type(error).__name__})") from error


async def store_image(jpeg: bytes) -> str:
    """Cloudinary secure_url when configured (the only thing saved in MongoDB); otherwise the local fallback."""
    if cloudinary_configured():
        return await asyncio.to_thread(_upload_to_cloudinary, jpeg)
    return store_image_bytes(jpeg)


async def externalize_data_url(image) -> str:
    """Supplier uploads arrive as base64 data URLs. With Cloudinary configured they are uploaded and replaced by the
    secure_url, so MongoDB holds a link instead of the picture. If the upload fails the original value is kept."""
    value = str(image or "")
    if not value.startswith("data:image/") or not cloudinary_configured():
        return image or ""
    try:
        encoded = value.split(",", 1)[1]
        if len(encoded) > MAX_BYTES * 4 // 3 + 16:
            raise ImageError("Image is larger than 5 MB")
        raw = await asyncio.to_thread(base64.b64decode, encoded)
        return await store_image(await asyncio.to_thread(process_image, raw))
    except (ImageError, IndexError, ValueError):
        logger.warning("Could not move an uploaded product image to Cloudinary; keeping the original")
        return value


def local_image_path(name: str):
    return IMAGE_DIR / name if FILE_RE.match(name or "") else None


def image_exists_locally(url: str) -> bool:
    path = local_image_path(str(url).rsplit("/", 1)[-1].split("?")[0])
    return bool(path and path.exists())


async def is_public_http_url(url: str) -> bool:
    parsed = urlparse(str(url))
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, parsed.hostname, None)
        return bool(infos) and all(ipaddress.ip_address(info[4][0]).is_global for info in infos)
    except (OSError, ValueError):
        return False


async def check_image_url(client, url: str):
    """True = loads, False = definitely broken, None = could not tell (network trouble)."""
    url = str(url).strip()
    if url.startswith("data:image/"):
        return True
    if url.startswith(URL_PREFIX):
        return image_exists_locally(url)
    if not await is_public_http_url(url):
        return False
    try:
        response = await client.get(url, headers={"Range": "bytes=0-1023"})
    except httpx.HTTPError:
        return None
    if response.status_code >= 500:
        return None
    if response.status_code >= 400:
        return False
    if response.status_code < 300 and not response.headers.get("content-type", "").lower().startswith("image/"):
        return False
    return True


_inflight: dict = {}
_semaphore = None


def _limiter():
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(2)
    return _semaphore


async def _pixabay_search(client, query: str) -> list:
    response = await client.get(
        "https://pixabay.com/api/",
        params={"key": os.environ["PIXABAY_API_KEY"].strip(), "q": query[:100], "image_type": "photo",
                "safesearch": "true", "per_page": 15},
    )
    if response.status_code == 429:
        raise ProviderBusy()
    response.raise_for_status()
    # Pixabay describes each photo with comma-separated tags; they play the role of a caption for scoring.
    return [{
        "id": str(hit["id"]), "alt": hit.get("tags") or "",
        "url": hit.get("largeImageURL") or hit["webformatURL"],
        "photographer": hit.get("user", ""), "page": hit.get("pageURL", ""),
    } for hit in response.json().get("hits", [])]


async def cached_search(db, client, query: str, search=_pixabay_search) -> list:
    """One provider call per distinct query: results are cached in Mongo and concurrent callers share a request."""
    key = _norm(query)
    cache = getattr(db, "image_search_cache", None)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=CACHE_DAYS)).isoformat()
    if cache is not None:
        hit = await cache.find_one({"query": key}, {"_id": 0})
        if hit and hit.get("cached_at", "") >= cutoff:
            return hit["photos"]
    if key in _inflight:
        return await _inflight[key]

    async def fetch():
        async with _limiter():
            return await search(client, key)

    future = asyncio.ensure_future(fetch())
    _inflight[key] = future
    try:
        photos = await future
    finally:
        _inflight.pop(key, None)
    if cache is not None:
        await cache.update_one({"query": key}, {"$set": {"query": key, "photos": photos, "cached_at": now_iso()}}, upsert=True)
    return photos


async def _download(client, photo: dict) -> bytes:
    parsed = urlparse(photo["url"])
    if parsed.scheme != "https" or parsed.hostname not in IMAGE_HOSTS:
        raise ImageError("Image host is not allowed")
    response = await client.get(photo["url"])
    response.raise_for_status()
    return response.content


async def _stored_photo_url(db, client, photo: dict, download=_download) -> str:
    """Reuse a previously stored copy of the same provider photo; download it only once."""
    key = f"pixabay:{photo['id']}"
    assets = getattr(db, "product_image_assets", None)
    if assets is not None:
        asset = await assets.find_one({"photo_key": key}, {"_id": 0})
        if asset and (str(asset["url"]).startswith("https://") or image_exists_locally(asset["url"])):
            await assets.update_one({"photo_key": key}, {"$inc": {"uses": 1}})
            return asset["url"]
    url = await store_image(process_image(await download(client, photo)))
    if assets is not None:
        await assets.update_one({"photo_key": key}, {"$set": {"photo_key": key, "url": url}, "$inc": {"uses": 1}}, upsert=True)
    return url


async def _photo_uses(db, photos: list) -> dict:
    assets = getattr(db, "product_image_assets", None)
    if assets is None or not photos:
        return {}
    rows = await assets.find({"photo_key": {"$in": [f"pixabay:{p['id']}" for p in photos]}}, {"_id": 0}).to_list(len(photos))
    return {row["photo_key"].split(":", 1)[1]: row.get("uses", 0) for row in rows}


def _query(tokens: list) -> str:
    return " ".join(tokens[:6])


async def find_best_image(db, client, name, category="", description="", excluded=(), search=_pixabay_search):
    """Returns (photo, confidence, level) or (None, 0.0, None)."""
    terms = build_terms(name, category, description)
    product_tokens = list(dict.fromkeys(terms["brand"] + terms["type"]))
    if product_tokens:
        photos = await cached_search(db, client, _query(product_tokens), search)
        photo, raw = pick_photo(photos, product_tokens, excluded, await _photo_uses(db, photos))
        if photo and raw >= THRESHOLD_PRODUCT:
            brand_hit = bool(terms["brand"]) and score_photo(photo["alt"], terms["brand"]) == 1.0
            return photo, raw, "exact_product" if brand_hit and raw >= 0.8 else "product_type"
    if terms["category"]:
        photos = await cached_search(db, client, _query(terms["category"]), search)
        photo, raw = pick_photo(photos, terms["category"], excluded, await _photo_uses(db, photos))
        if photo and raw >= THRESHOLD_CATEGORY:
            return photo, round(raw * 0.8, 2), "subcategory"
    return None, 0.0, None


def _product_filter(product: dict) -> dict:
    # Never touch a product whose image was set manually in the meantime.
    base = {"id": product["id"]} if product.get("id") else {"_id": product.get("_id")}
    return {**base, "image_source": {"$ne": "manual"}}


async def assign_product_image(db, product: dict, client, search=_pixabay_search, download=_download) -> str:
    """Find, store and attach an image. Returns ok | no_match | error | manual | skipped."""
    if product.get("image_source") == "manual" and not is_missing_media(product.get("image")):
        return "manual"
    if not is_missing_media(product.get("image")) and not is_generated_placeholder(product.get("image")) \
            and product.get("image_status") not in ("pending", "broken"):
        return "skipped"
    attempts = int(product.get("image_attempts") or 0)
    try:
        photo, confidence, level = await find_best_image(
            db, client, product.get("name"), product.get("category"), product.get("description"),
            product.get("image_excluded") or (), search,
        )
        if photo:
            url = await _stored_photo_url(db, client, photo, download)
            update = {
                "image": url, "image_source": "auto", "image_status": "ok", "image_confidence": round(confidence, 2),
                "image_match_level": level, "image_photo_key": f"pixabay:{photo['id']}",
                "image_credit": {"provider": "Pixabay", "photographer": photo["photographer"], "url": photo["page"]},
                "image_attempts": 0, "image_updated_at": now_iso(), "image_checked_at": now_iso(),
            }
            status = "ok"
        else:
            update = {"image_status": "no_match", "image_attempts": attempts + 1, "image_updated_at": now_iso()}
            status = "no_match"
    except ProviderBusy:
        raise
    except (httpx.HTTPError, ImageError, OSError, KeyError, ValueError) as error:
        logger.warning("Image assignment failed for product %s: %s", product.get("id"), type(error).__name__)
        attempts += 1
        update = {
            "image_status": "failed" if attempts >= MAX_ATTEMPTS else "pending", "image_attempts": attempts,
            "image_next_attempt_at": (datetime.now(timezone.utc) + timedelta(minutes=10 * 2 ** attempts)).isoformat(),
            "image_updated_at": now_iso(),
        }
        status = "error"
    await db.products.update_one(_product_filter(product), {"$set": update})
    return status


def pending_query() -> dict:
    now = now_iso()
    return {"$and": [
        {"image_source": {"$ne": "manual"}},
        {"image_status": {"$nin": ["no_match", "failed"]}},
        {"$or": [
            {"image": {"$in": MISSING_VALUES}}, {"image": {"$regex": r"^\s*$"}},
            {"image": {"$regex": PLACEHOLDER_REGEX}}, {"image_status": {"$in": ["pending", "broken"]}},
        ]},
        {"$or": [{"image_next_attempt_at": {"$exists": False}}, {"image_next_attempt_at": {"$lte": now}}]},
    ]}


_PROJECTION = {
    "_id": 1, "id": 1, "name": 1, "category": 1, "description": 1, "image": 1, "image_source": 1,
    "image_status": 1, "image_attempts": 1, "image_excluded": 1,
}


async def process_pending_images(db, limit: int = 10) -> dict:
    """Assign images to products that have none (batched, idempotent). Safe to call repeatedly."""
    if not search_enabled():
        return {"processed": 0, "skipped": "PIXABAY_API_KEY is not configured"}
    products = await db.products.find(pending_query(), _PROJECTION).limit(limit).to_list(limit)
    counts = {"ok": 0, "no_match": 0, "error": 0}
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        for product in products:
            try:
                status = await assign_product_image(db, product, client)
            except ProviderBusy:
                counts["rate_limited"] = True
                break
            counts[status] = counts.get(status, 0) + 1
    return {"processed": len(products), **counts}


async def check_existing_images(db, limit: int = 20) -> int:
    """Flag products whose image URL no longer loads, and protect valid existing images as manual."""
    query = {
        "image_checked_at": {"$exists": False},
        "image": {"$nin": MISSING_VALUES, "$not": {"$regex": PLACEHOLDER_REGEX}},
    }
    products = await db.products.find(query, {"_id": 1, "id": 1, "image": 1, "image_source": 1}).limit(limit).to_list(limit)
    broken = 0
    async with httpx.AsyncClient(timeout=6, follow_redirects=False) as client:
        for product in products:
            valid = await check_image_url(client, product["image"])
            if valid is None:
                continue
            filt = {"id": product["id"]} if product.get("id") else {"_id": product["_id"]}
            if valid:
                update = {"image_checked_at": now_iso()}
                if not product.get("image_source"):
                    update.update(image_source="manual", image_status="ok")
            else:
                broken += 1
                update = {"image": "", "image_previous": product["image"][:500], "image_status": "pending",
                          "image_attempts": 0, "image_checked_at": now_iso()}
            await db.products.update_one(filt, {"$set": update})
    return broken


async def process_category_images(db, limit: int = 10) -> dict:
    if not search_enabled() or getattr(db, "categories", None) is None:
        return {"processed": 0}
    query = {"image_source": {"$ne": "manual"}, "image_status": {"$nin": ["no_match"]},
             "image": {"$in": [*MISSING_VALUES]}}
    rows = await db.categories.find(query, {"_id": 0, "id": 1, "name": 1}).limit(limit).to_list(limit)
    done = 0
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        for row in rows:
            try:
                photo, confidence, level = await find_best_image(db, client, "", row["name"])
                if not photo:
                    await db.categories.update_one({"id": row["id"]}, {"$set": {"image_status": "no_match"}})
                    continue
                url = await _stored_photo_url(db, client, photo)
                await db.categories.update_one({"id": row["id"], "image_source": {"$ne": "manual"}}, {"$set": {
                    "image": url, "image_source": "auto", "image_status": "ok", "image_confidence": round(confidence, 2),
                }})
                done += 1
            except ProviderBusy:
                break
            except (httpx.HTTPError, ImageError, OSError, KeyError):
                logger.warning("Category image failed for %s", row.get("name"))
    return {"processed": len(rows), "assigned": done}


_tasks: set = set()


def schedule(db, product_ids: list) -> None:
    """Fire-and-forget assignment for just-created products; never blocks or fails the request."""
    if not product_ids or not search_enabled():
        return
    product_ids = list(product_ids)[:50]  # the periodic backfill handles the rest

    async def run():
        try:
            products = await db.products.find({"id": {"$in": product_ids}}, _PROJECTION).to_list(len(product_ids))
            async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
                for product in products:
                    await assign_product_image(db, product, client)
        except ProviderBusy:
            logger.info("Image provider is rate limiting; the background backfill will retry")
        except Exception:
            logger.exception("Background image assignment failed")

    try:
        task = asyncio.get_running_loop().create_task(run())
    except RuntimeError:
        return
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def image_backfill_loop(db):
    interval = int(os.environ.get("IMAGE_BACKFILL_INTERVAL_SECONDS", "300"))
    batch = int(os.environ.get("IMAGE_BACKFILL_BATCH", "10"))
    await asyncio.sleep(20)
    while True:
        try:
            await check_existing_images(db, batch * 2)
            await process_pending_images(db, batch)
            await process_category_images(db, batch)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Image backfill cycle failed")
        await asyncio.sleep(interval)
