import asyncio
import base64

import pytest

import product_images as pi
from test_product_images import Db, jpeg_bytes, photo, run_assign


def _cloudinary_env(monkeypatch):
    monkeypatch.setenv("CLOUDINARY_CLOUD_NAME", "demo")
    monkeypatch.setenv("CLOUDINARY_API_KEY", "key")
    monkeypatch.setenv("CLOUDINARY_API_SECRET", "secret")


def test_cloudinary_upload_returns_secure_url_and_writes_nothing_locally(monkeypatch, tmp_path):
    import cloudinary.uploader
    _cloudinary_env(monkeypatch)
    monkeypatch.setattr(pi, "IMAGE_DIR", tmp_path)
    calls = []

    def fake_upload(file, **options):
        calls.append(options)
        return {"secure_url": f"https://res.cloudinary.com/demo/image/upload/{options['folder']}/{options['public_id']}.jpg"}

    monkeypatch.setattr(cloudinary.uploader, "upload", fake_upload)
    url = asyncio.run(pi.store_image(jpeg_bytes()))
    assert url.startswith("https://res.cloudinary.com/demo/image/upload/distro/products/")
    assert calls[0]["overwrite"] is False and calls[0]["cloud_name"] == "demo"
    assert list(tmp_path.iterdir()) == []


def test_assigned_product_image_is_saved_as_cloudinary_link_only(monkeypatch, tmp_path):
    import cloudinary.uploader
    _cloudinary_env(monkeypatch)
    monkeypatch.setattr(cloudinary.uploader, "upload", lambda file, **o: {"secure_url": "https://res.cloudinary.com/demo/x.jpg"})
    db = Db([{"id": "p1", "name": "Snickers", "category": "Sweets", "image": "", "image_status": "pending"}])
    status, _ = run_assign(db, db.products.rows[0], [photo("2", "Snickers chocolate bar")], monkeypatch, tmp_path)
    assert status == "ok" and db.products.rows[0]["image"] == "https://res.cloudinary.com/demo/x.jpg"
    assert db.product_image_assets.rows[0]["url"] == "https://res.cloudinary.com/demo/x.jpg"
    assert list(tmp_path.iterdir()) == []


def test_supplier_data_url_is_replaced_by_secure_url(monkeypatch):
    import cloudinary.uploader
    _cloudinary_env(monkeypatch)
    monkeypatch.setattr(cloudinary.uploader, "upload", lambda file, **o: {"secure_url": "https://res.cloudinary.com/demo/up.jpg"})
    data_url = "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes()).decode()
    assert asyncio.run(pi.externalize_data_url(data_url)) == "https://res.cloudinary.com/demo/up.jpg"
    assert asyncio.run(pi.externalize_data_url("https://example.com/a.jpg")) == "https://example.com/a.jpg"


def test_cloudinary_failure_keeps_supplier_image_and_reports_error(monkeypatch):
    import cloudinary.uploader
    _cloudinary_env(monkeypatch)

    def boom(file, **options):
        raise RuntimeError("network down")

    monkeypatch.setattr(cloudinary.uploader, "upload", boom)
    data_url = "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes()).decode()
    assert asyncio.run(pi.externalize_data_url(data_url)) == data_url
    with pytest.raises(pi.ImageError):
        asyncio.run(pi.store_image(jpeg_bytes()))


def test_without_cloudinary_settings_local_fallback_is_used(monkeypatch, tmp_path):
    for name in ("CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(pi, "IMAGE_DIR", tmp_path)
    assert asyncio.run(pi.store_image(jpeg_bytes())).startswith("/product-images/")
    assert asyncio.run(pi.externalize_data_url("data:image/jpeg;base64,AAAA")) == "data:image/jpeg;base64,AAAA"
