import re

_PLACEHOLDER_RE = re.compile(
    r"loremflickr\.com|images\.unsplash\.com/photo-(1554866585|1549007994|1563245372|1540420773|"
    r"1550583724|1509440159|1607623814|1542838132)",
)


def is_missing_media(value) -> bool:
    return not str(value or "").strip() or str(value).strip().casefold() in {"null", "none", "undefined"}


def is_generated_placeholder(value) -> bool:
    """Images the system itself used to generate (random keyword photos); safe to replace."""
    return bool(_PLACEHOLDER_RE.search(str(value or "")))


is_legacy_fallback_image = is_generated_placeholder


def fallback_product_description(name, category="") -> str:
    product_name = " ".join(str(name or "პროდუქტი").split())
    product_category = " ".join(str(category or "სასურსათო").split())
    return (
        f"{product_name} — ხარისხიანი პროდუქტი {product_category} კატეგორიიდან, "
        "ყოველდღიური მარაგისა და საბითუმო მომარაგებისთვის."
    )[:300]


def _usable(image) -> bool:
    return not is_missing_media(image) and not is_generated_placeholder(image)


def complete_product_media(product, existing=None) -> dict:
    """Description fallback and image bookkeeping. A missing image is left empty and marked pending so the
    background job can find a matching photo; a supplied image is recorded as manual and never replaced."""
    existing = existing or {}
    name = product.get("name") or existing.get("name") or "პროდუქტი"
    category = product.get("category") or existing.get("category") or "სასურსათო"
    image = product.get("image")
    if not _usable(image):
        image = existing.get("image")
    if _usable(image):
        unchanged = image == existing.get("image") and existing.get("image_source")
        media = {"image": image, "image_source": existing["image_source"] if unchanged else "manual"}
        if not unchanged:
            media["image_status"] = "ok"
    else:
        media = {"image": "", "image_source": None, "image_status": "pending", "image_attempts": 0}

    description = product.get("description")
    if is_missing_media(description):
        description = existing.get("description")
    if is_missing_media(description):
        description = fallback_product_description(name, category)
    return {**media, "description": description}
