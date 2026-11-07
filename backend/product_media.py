from urllib.parse import quote


_IMAGE_IDS = {
    "beverages": "photo-1554866585-cd94860890b7",
    "chocolate": "photo-1549007994-cb92caebd54b",
    "dumplings": "photo-1563245372-f21724e3856d",
    "produce": "photo-1540420773420-3366772f4999",
    "dairy": "photo-1550583724-b2692b85b150",
    "bakery": "photo-1509440159596-0249088772ff",
    "meat": "photo-1607623814075-e51df1bdc82f",
    "groceries": "photo-1542838132-92c53300491e",
}

_NAME_MATCHES = (
    (("snickers", "სნიკერს", "chocolate", "შოკოლად"), "chocolate"),
    (("pelmeni", "dumpling", "пельмен", "პილმენ", "ხინკალ"), "dumplings"),
    (("coca-cola", "coca cola", "coke", "კოკა-კოლა", "კოკაკოლა"), "beverages"),
    (("milk", "yogurt", "cheese", "რძე", "იოგურტ", "ყველი"), "dairy"),
    (("bread", "bakery", "პური", "პურეულ"), "bakery"),
    (("meat", "chicken", "beef", "ხორცი", "ქათამ"), "meat"),
    (("fruit", "vegetable", "produce", "ხილი", "ბოსტნეულ"), "produce"),
    (("drink", "beverage", "juice", "water", "სასმელ", "წვენი", "წყალი"), "beverages"),
)

_CATEGORY_MATCHES = (
    (("beverage", "drink", "სასმელ"), "beverages"),
    (("dairy", "milk", "რძის", "რძე"), "dairy"),
    (("bakery", "bread", "პურ"), "bakery"),
    (("meat", "ხორც"), "meat"),
    (("fruit", "produce", "vegetable", "ხილ", "ბოსტნეულ"), "produce"),
    (("frozen", "dumpling", "pelmeni", "გაყინულ", "პილმენ", "ხინკალ"), "dumplings"),
    (("snack", "sweets", "candy", "ტკბილ", "სნექ"), "chocolate"),
)


def _text(value) -> str:
    return " ".join(str(value or "").casefold().replace("_", " ").split())


def is_missing_media(value) -> bool:
    return not str(value or "").strip() or str(value).strip().casefold() in {"null", "none", "undefined"}


def _image_group(name, category) -> str:
    product_name = _text(name)
    category_text = _text(category)
    for keywords, group in _NAME_MATCHES:
        if any(keyword in product_name for keyword in keywords):
            return group
    for keywords, group in _CATEGORY_MATCHES:
        if any(keyword in category_text for keyword in keywords):
            return group
    return "groceries"


def fallback_product_image(name, category="") -> str:
    photo_id = _IMAGE_IDS[_image_group(name, category)]
    return f"https://images.unsplash.com/{quote(photo_id)}?auto=format&fit=crop&w=800&q=85"


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
    if is_missing_media(image):
        image = existing.get("image")
    if is_missing_media(image):
        image = fallback_product_image(name, category)

    description = product.get("description")
    if is_missing_media(description):
        description = existing.get("description")
    if is_missing_media(description):
        description = fallback_product_description(name, category)
    return {"image": image, "description": description}
