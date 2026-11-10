"""Find and attach Pixabay images to products that have none.

Usage (from the backend folder):
    python scripts/backfill_product_images.py --dry-run      # only count, change nothing
    python scripts/backfill_product_images.py                # process everything, in batches
    python scripts/backfill_product_images.py --limit 50 --batch 10 --pause 3

Safe to repeat: products with a manual or already assigned image are skipped, and products whose search found
no confident match are not retried automatically (use the admin panel to retry them).
Images are stored in PRODUCT_IMAGE_DIR, so run this on the server that serves them (or with that folder mounted).
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND / ".env")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

import product_images as pi  # noqa: E402
import security as safeguards  # noqa: E402
from migrations.product_media import upgrade  # noqa: E402

NO_IMAGE = {"$and": [
    {"image_source": {"$ne": "manual"}},
    {"$or": [
        {"image": {"$in": pi.MISSING_VALUES}}, {"image": {"$regex": r"^\s*$"}}, {"image": {"$regex": pi.PLACEHOLDER_REGEX}},
    ]},
]}


async def summary(db) -> dict:
    return {
        "total_products": await db.products.count_documents({}),
        "without_image": await db.products.count_documents(NO_IMAGE),
        "waiting_for_search": await db.products.count_documents(pi.pending_query()),
        "no_confident_match": await db.products.count_documents({**NO_IMAGE, "image_status": "no_match"}),
        "failed_permanently": await db.products.count_documents({**NO_IMAGE, "image_status": "failed"}),
        "auto_assigned": await db.products.count_documents({"image_source": "auto"}),
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="count only; nothing is written")
    parser.add_argument("--batch", type=int, default=10, help="products per round (default 10)")
    parser.add_argument("--limit", type=int, default=0, help="stop after this many products (0 = all)")
    parser.add_argument("--pause", type=float, default=2.0, help="seconds between rounds to respect rate limits")
    args = parser.parse_args()

    url = os.environ["MONGO_URL"]
    client = AsyncIOMotorClient(url, **safeguards.mongo_client_options(url, os.environ))
    db = client[os.environ["DB_NAME"]]
    print(f"Database: {os.environ['DB_NAME']}   image folder: {pi.IMAGE_DIR}")
    print("Before:", await summary(db))
    if args.dry_run:
        return 0
    if not pi.search_enabled():
        print("PIXABAY_API_KEY is not configured; nothing to do.")
        return 1

    await upgrade(db)  # marks products without a usable image as pending (idempotent)
    handled = assigned = 0
    while not args.limit or handled < args.limit:
        size = min(args.batch, args.limit - handled) if args.limit else args.batch
        result = await pi.process_pending_images(db, size)
        handled += result.get("processed", 0)
        assigned += result.get("ok", 0)
        print(f"  round: {result}")
        if result.get("rate_limited"):
            print("Pixabay rate limit reached; run the script again later to continue.")
            break
        if not result.get("processed"):
            break
        await asyncio.sleep(args.pause)
    print(f"Processed {handled} products, assigned {assigned} images.")
    print("After: ", await summary(db))
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
