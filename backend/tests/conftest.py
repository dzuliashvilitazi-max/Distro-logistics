import os

import pytest

# server.py refuses to import without an explicit APP_ENV.
os.environ.setdefault("APP_ENV", "test")


@pytest.fixture(autouse=True)
def _no_real_image_uploads(monkeypatch):
    # backend/.env is loaded on import; tests must never upload to a real Cloudinary account.
    for name in ("CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET"):
        monkeypatch.delenv(name, raising=False)
