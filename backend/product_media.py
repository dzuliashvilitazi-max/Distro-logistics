import hashlib
from urllib.parse import quote


_NAME_MATCHES = (
    (("snickers", "სნიკერს", "chocolate", "შოკოლად", "candy", "კანფეტ"), "chocolate"),
    (("pelmeni", "dumpling", "пельмен", "პილმენ", "ხინკალ"), "dumplings"),
    (("coca-cola", "coca cola", "coke", "კოკა-კოლა", "კოკაკოლა", "კოლა"), "cola"),
    (("orange juice", "juice", "წვენი", "წვენ"), "juice"),
    (("milk", "yogurt", "cheese", "რძე", "იოგურტ", "ყველი"), "dairy"),
    (("bread", "bakery", "პური", "პურეულ"), "bread"),
    (("meat", "chicken", "beef", "ხორცი", "ქათამ"), "meat"),
    (("fruit", "apple", "banana", "ხილი", "ვაშლი", "ბანანი"), "fruit"),
    (("vegetable", "tomato", "potato", "ბოსტნეულ", "პომიდორ", "კარტოფილ"), "vegetables"),
    (("coffee", "ყავა"), "coffee"),
    (("tea", "ჩაი"), "tea"),
    (("pasta", "macaroni", "მაკარონ", "პასტა"), "pasta"),
    (("rice", "ბრინჯ"), "rice"),
    (("water", "წყალი"), "water"),
    (("snack", "chips", "სნექ", "ჩიფს"), "snacks"),
    (("drink", "beverage", "სასმელ"), "soft-drink"),
)

_CATEGORY_MATCHES = (
    (("beverage", "drink", "სასმელ"), "soft-drink"),
    (("juice", "წვენ"), "juice"),
    (("dairy", "milk", "რძის", "რძე"), "dairy"),
    (("bakery", "bread", "პურ"), "bread"),
    (("meat", "ხორც"), "meat"),
    (("fruit", "produce", "ხილ"), "fruit"),
    (("vegetable", "ბოსტნეულ"), "vegetables"),
    (("frozen", "dumpling", "pelmeni", "გაყინულ", "პილმენ", "ხინკალ"), "dumplings"),
    (("snack", "სნექ", "ჩიფს"), "snacks"),
    (("sweet", "candy", "ტკბილ", "კანფეტ", "შოკოლად"), "chocolate"),
    (("coffee", "ყავა"), "coffee"),
    (("tea", "ჩაი"), "tea"),
    (("pasta", "macaroni", "მაკარონ"), "pasta"),
    (("rice", "ბრინჯ"), "rice"),
    (("water", "წყალი"), "water"),
)

_LEGACY_IMAGE_IDS = (
    "photo-1554866585-cd94860890b7", "photo-1549007994-cb92caebd54b",
    "photo-1563245372-f21724e3856d", "photo-1540420773420-3366772f4999",
    "photo-1550583724-b2692b85b150", "photo-1509440159596-0249088772ff",
    "photo-1607623814075-e51df1bdc82f", "photo-1542838132-92c53300491e",
)


def _text(value) -> str:
    return " ".join(str(value or "").casefold().replace("_", " ").split())


def is_missing_media(value) -> bool:
    return not str(value or "").strip() or str(value).strip().casefold() in {"null", "none", "undefined"}


def is_legacy_fallback_image(value) -> bool:
    value = str(value or "")
    return "images.unsplash.com/" in value and any(photo_id in value for photo_id in _LEGACY_IMAGE_IDS)


def _image_keyword(name, category) -> str:
    product_name = _text(name)
    category_text = _text(category)
    for keywords, group in _NAME_MATCHES:
        if any(keyword in product_name for keyword in keywords):
            return group
    for keywords, group in _CATEGORY_MATCHES:
        if any(keyword in category_text for keyword in keywords):
            return group
    ascii_words = [word for word in product_name.split() if word.isascii() and word.isalpha()]
    if ascii_words:
        return ascii_words[0]
    return "groceries"


def fallback_product_image(name, category="") -> str:
    keyword = _image_keyword(name, category)
    seed = int.from_bytes(hashlib.sha256(f"{_text(name)}|{_text(category)}".encode("utf-8")).digest()[:4], "big")
    return f"https://loremflickr.com/800/600/{quote(keyword, safe=',-')}?lock={seed}"


def fallback_product_description(name, category="") -> str:
    product_name = " ".join(str(name or "პროდუქტი").split())
    product_category = " ".join(str(category or "სასურსათო").split())
    return (
        f"{product_name} — ხარისხიანი პროდუქტი {product_category} კატეგორიიდან, "
        "ყოველდღიური მარაგისა და საბითუმო მომარაგებისთვის."
    )[:300]


def complete_product_media(product, existing=None) -> dict:
    existing = existing or {}
    name = product.get("name") or existing.get("name") or "პროდუქტი"
    category = product.get("category") or existing.get("category") or "სასურსათო"
    image = product.get("image")
    if is_missing_media(image) or is_legacy_fallback_image(image):
        image = existing.get("image")
    if is_missing_media(image) or is_legacy_fallback_image(image):
        image = fallback_product_image(name, category)

    description = product.get("description")
    if is_missing_media(description):
        description = existing.get("description")
    if is_missing_media(description):
        description = fallback_product_description(name, category)
    return {"image": image, "description": description}
