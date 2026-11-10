import pytest
import asyncio
import io
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import product_images as pi


def jpeg_bytes():
    out = io.BytesIO()
    Image.new("RGB", (1600, 1200), (200, 30, 30)).save(out, format="JPEG")
    return out.getvalue()


class Collection:
    def __init__(self, rows=()):
        self.rows = [dict(r) for r in rows]

    def _match(self, row, query):
        for key, cond in query.items():
            value = row.get(key)
            if isinstance(cond, dict):
                if "$ne" in cond and value == cond["$ne"]:
                    return False
                if "$in" in cond and value not in cond["$in"]:
                    return False
            elif value != cond:
                return False
        return True

    def find(self, query, _projection=None):
        rows = [dict(r) for r in self.rows if self._match(r, query)]

        class Cursor:
            async def to_list(self, _limit):
                return rows

        return Cursor()

    async def find_one(self, query, _projection=None):
        return next((dict(r) for r in self.rows if self._match(r, query)), None)

    async def update_one(self, query, update, upsert=False):
        row = next((r for r in self.rows if self._match(r, query)), None)
        if row is None and upsert:
            row = {k: v for k, v in query.items() if not isinstance(v, dict)}
            self.rows.append(row)
        if row is None:
            return
        row.update(update.get("$set", {}))
        for key, amount in update.get("$inc", {}).items():
            row[key] = row.get(key, 0) + amount


class Db:
    def __init__(self, products):
        self.products = Collection(products)
        self.product_image_assets = Collection()
        self.image_search_cache = Collection()


def photo(photo_id, alt):
    return {"id": photo_id, "alt": alt, "url": f"https://cdn.pixabay.com/{photo_id}.jpg", "photographer": "P", "page": "u"}


def run_assign(db, product, photos, monkeypatch, tmp_path):
    monkeypatch.setattr(pi, "IMAGE_DIR", tmp_path)
    calls = []

    async def search(_client, query):
        calls.append(query)
        return photos

    async def download(_client, _photo):
        return jpeg_bytes()

    status = asyncio.run(pi.assign_product_image(db, product, None, search=search, download=download))
    return status, calls


def test_terms_separate_brand_type_and_category():
    terms = pi.build_terms("Snickers 50g", "Sweets")
    assert "snickers" in terms["brand"]
    assert pi.build_terms("ცემენტი", "სამშენებლო")["type"][:2] == ["cement", "bag"]
    assert "cleaning" in pi.build_terms("ფხვნილი", "Household Chemicals")["category"]


def test_scoring_prefers_description_match_and_rejects_unrelated():
    photos = [photo("1", "A mountain landscape"), photo("2", "Snickers chocolate bar wrapper")]
    best, raw = pi.pick_photo(photos, ["snickers", "chocolate", "bar"])
    assert best["id"] == "2" and raw == 1.0
    assert pi.pick_photo([photo("1", "A mountain landscape")], ["snickers"])[0] is None


def test_assigns_matching_image_stores_resized_file_and_reuses_asset(monkeypatch, tmp_path):
    db = Db([{"id": "p1", "name": "Snickers", "category": "Sweets", "image": "", "image_status": "pending"},
             {"id": "p2", "name": "Snickers Max", "category": "Sweets", "image": "", "image_status": "pending"}])
    photos = [photo("2", "Snickers chocolate bar")]
    status, _ = run_assign(db, db.products.rows[0], photos, monkeypatch, tmp_path)
    assert status == "ok"
    row = db.products.rows[0]
    assert row["image_source"] == "auto" and row["image"].startswith("/product-images/")
    stored = tmp_path / row["image"].rsplit("/", 1)[1]
    assert Image.open(stored).size[0] <= 800
    run_assign(db, db.products.rows[1], photos, monkeypatch, tmp_path)
    assert db.products.rows[1]["image"] == row["image"]
    assert db.product_image_assets.rows[0]["uses"] == 2


def test_low_confidence_is_not_assigned(monkeypatch, tmp_path):
    db = Db([{"id": "p1", "name": "Snickers", "category": "Sweets", "image": "", "image_status": "pending"}])
    status, _ = run_assign(db, db.products.rows[0], [photo("9", "Mountain lake at sunrise")], monkeypatch, tmp_path)
    assert status == "no_match"
    assert db.products.rows[0]["image"] == "" and db.products.rows[0]["image_status"] == "no_match"


def test_manual_images_are_never_replaced(monkeypatch, tmp_path):
    db = Db([{"id": "p1", "name": "Snickers", "category": "Sweets", "image": "https://x.test/a.jpg", "image_source": "manual"}])
    status, calls = run_assign(db, db.products.rows[0], [photo("2", "Snickers")], monkeypatch, tmp_path)
    assert status == "manual" and calls == []
    assert db.products.rows[0]["image"] == "https://x.test/a.jpg"
    # a manual image set while the search was running must win over the automatic result
    racing = Db([{"id": "p2", "name": "Snickers", "category": "Sweets", "image": "", "image_source": "manual"}])
    stale = {"id": "p2", "name": "Snickers", "category": "Sweets", "image": "", "image_status": "pending"}
    run_assign(racing, stale, [photo("2", "Snickers chocolate")], monkeypatch, tmp_path)
    assert racing.products.rows[0]["image"] == ""


def test_process_image_rejects_non_images():
    try:
        pi.process_image(b"not an image")
    except pi.ImageError:
        return
    raise AssertionError("expected ImageError")


def _pixabay_client(handler):
    import httpx
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_pixabay_search_builds_expected_request_and_maps_hits(monkeypatch):
    monkeypatch.setenv("PIXABAY_API_KEY", "test-key")
    seen = {}

    def handler(request):
        import httpx
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"hits": [{
            "id": 7, "tags": "snickers, chocolate, bar", "largeImageURL": "https://pixabay.com/get/x_1280.jpg",
            "webformatURL": "https://pixabay.com/get/x_640.jpg", "user": "someone", "pageURL": "https://pixabay.com/p/7",
        }]})

    async def run():
        async with _pixabay_client(handler) as client:
            return await pi._pixabay_search(client, "snickers chocolate")

    photos = asyncio.run(run())
    assert seen["params"]["q"] == "snickers chocolate" and seen["params"]["safesearch"] == "true"
    assert seen["params"]["image_type"] == "photo" and seen["params"]["key"] == "test-key"
    assert photos == [{"id": "7", "alt": "snickers, chocolate, bar", "url": "https://pixabay.com/get/x_1280.jpg",
                       "photographer": "someone", "page": "https://pixabay.com/p/7"}]


def test_pixabay_rate_limit_and_empty_results_degrade_gracefully(monkeypatch, tmp_path):
    import httpx
    monkeypatch.setenv("PIXABAY_API_KEY", "test-key")

    async def run(status, body):
        async with _pixabay_client(lambda request: httpx.Response(status, json=body)) as client:
            return await pi._pixabay_search(client, "x")

    assert asyncio.run(run(200, {"hits": []})) == []
    with pytest.raises(pi.ProviderBusy):
        asyncio.run(run(429, {}))
    db = Db([{"id": "p1", "name": "Snickers", "category": "Sweets", "image": "", "image_status": "pending"}])
    status, _ = run_assign(db, db.products.rows[0], [], monkeypatch, tmp_path)
    assert status == "no_match" and db.products.rows[0]["image"] == ""


def test_search_requires_pixabay_key(monkeypatch):
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    monkeypatch.setenv("PEXELS_API_KEY", "old")
    assert pi.search_enabled() is False
    monkeypatch.setenv("PIXABAY_API_KEY", "k")
    assert pi.search_enabled() is True

