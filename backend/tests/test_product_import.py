import asyncio
import copy
import json
import sys
import uuid
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


def _upload(filename, content):
    return UploadFile(filename=filename, file=BytesIO(content))


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self, length):
        return copy.deepcopy(self.rows if length is None else self.rows[:length])


class _Products:
    def __init__(self):
        self.rows = []

    def find(self, query=None, projection=None):
        query = query or {}
        return _Cursor([row for row in self.rows if all(row.get(key) == value for key, value in query.items())])

    async def find_one(self, query, projection=None):
        return next((copy.deepcopy(row) for row in self.rows if all(row.get(key) == value for key, value in query.items())), None)

    async def insert_one(self, doc):
        self.rows.append(copy.deepcopy(doc))

    async def update_one(self, query, update):
        row = next((item for item in self.rows if all(item.get(key) == value for key, value in query.items())), None)
        if row:
            row.update(copy.deepcopy(update.get("$set", {})))

    async def delete_one(self, query):
        row = next((item for item in self.rows if all(item.get(key) == value for key, value in query.items())), None)
        if row:
            self.rows.remove(row)
            return type("Result", (), {"deleted_count": 1})()
        return type("Result", (), {"deleted_count": 0})()

    async def bulk_write(self, operations, ordered=True, session=None):
        for operation in operations:
            query = operation._filter
            row = next((item for item in self.rows if all(item.get(key) == value for key, value in query.items())), None)
            update = operation._doc
            if row:
                row.update(copy.deepcopy(update.get("$set", {})))
            elif operation._upsert:
                self.rows.append(copy.deepcopy(update["$setOnInsert"]))


class _Categories:
    def __init__(self):
        self.rows = []

    def find(self, query=None, projection=None):
        query = query or {}
        return _Cursor([row for row in self.rows if all(row.get(key) == value for key, value in query.items())])

    async def insert_one(self, doc):
        self.rows.append(copy.deepcopy(doc))


class _MemoryDB:
    def __init__(self):
        self.products = _Products()
        self.categories = _Categories()


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def start_transaction(self):
        return self


class _MongoClient:
    async def start_session(self):
        return _Session()


@contextmanager
def _client_with_supplier():
    original_db, original_client = server.db, server.client
    original_overrides = dict(server.app.dependency_overrides)
    memory_db = _MemoryDB()
    client = TestClient(server.app)
    server.db = memory_db
    server.client = _MongoClient()
    server.app.dependency_overrides[server.get_current_user] = lambda: {
        "id": "supplier-import-test", "role": "supplier", "business_name": "Test Supplier", "city": "Tbilisi",
    }
    try:
        yield client, memory_db
    finally:
        server.db, server.client = original_db, original_client
        server.app.dependency_overrides.clear()
        server.app.dependency_overrides.update(original_overrides)


def _csv_bytes(rows, headers=("Product Name", "Price", "Quantity", "Minimum Quantity")):
    return (",".join(headers) + "\n" + "\n".join(",".join(map(str, row)) for row in rows) + "\n").encode("utf-8-sig")


def _xlsx_bytes():
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Product Name", "Price", "Quantity", "Minimum Quantity"])
    sheet.append(["ქართული ჩაი", 12.5, 30, 2])
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_upload_post_routes_are_registered():
    paths = server.app.openapi()["paths"]
    assert "post" in paths["/api/products/upload-excel"]
    assert "post" in paths["/api/products/import-preview"]


def test_upload_url_accepts_post_and_rejects_get():
    client = TestClient(server.app)
    response = client.post(
        "/api/products/upload-excel",
        files={"file": ("products.csv", b"name,category,price\nTea,Beverages,1")},
    )

    assert response.status_code == 401
    assert client.get("/api/products/upload-excel").status_code == 405


def test_georgian_utf8_bom_csv_is_parsed():
    data = "პროდუქტის დასახელება,კატეგორია,ფასი,მარაგი,მინიმალური რაოდენობა,SKU,შტრიხკოდი,ერთეული\nქართული ჩაი,სასმელები,12.5,30,2,TEA-1,4860000000001,კგ\n".encode("utf-8-sig")
    rows, errors, metadata = asyncio.run(server._read_import_file(_upload("products.csv", data)))

    assert not errors
    assert rows[0]["name"] == "ქართული ჩაი"
    assert rows[0]["category"] == "სასმელები"
    assert rows[0]["price_per_unit"] == 12.5
    assert rows[0]["stock"] == 30
    assert rows[0]["moq"] == 2
    assert rows[0]["sku"] == "TEA-1"
    assert rows[0]["unit"] == "კგ"
    assert metadata["mapping"]["name"] == "პროდუქტის დასახელება"


def test_supplier_city_coverage_supports_all_and_legacy_city():
    assert server._supplier_serves_city({"cities": ["Tbilisi", "Batumi"]}, "Batumi")
    assert not server._supplier_serves_city({"cities": ["Batumi"]}, "Tbilisi")
    assert server._supplier_serves_city({"cities": ["All"]}, "Tbilisi")
    assert server._supplier_serves_city({"cities": ["ყველა"]}, "Tbilisi")
    assert server._supplier_serves_city({"city": "Tbilisi"}, "Tbilisi")


def test_txt_headers_are_normalized_and_new_product_numbers_default():
    data = "  Product   Name  ,Price Per Unit\nქართული ჩაი,\n".encode("utf-8")
    rows, errors, _ = asyncio.run(server._read_import_file(_upload("products.txt", data)))

    assert not errors
    plan, errors, _ = server._plan_product_import(rows, [])
    assert not errors
    assert plan[0]["row"]["price_per_unit"] == 0
    assert plan[0]["row"]["stock"] == 0
    assert plan[0]["row"]["moq"] == 1


def test_custom_column_mapping_parses_nonstandard_headers():
    data = "სათაური,განყოფილება,ღირებულება,დარჩენილი,მინ_მარაგი\nქართული ჩაი,სასმელები,12.5,30,2\n".encode("utf-8")
    mapping = json.dumps({
        "name": "სათაური", "category": "განყოფილება",
        "price_per_unit": "ღირებულება", "stock": "დარჩენილი", "moq": "მინ_მარაგი",
    })
    rows, errors, _ = asyncio.run(server._read_import_file(_upload("products.csv", data), mapping))

    assert not errors
    assert rows[0]["name"] == "ქართული ჩაი"
    assert rows[0]["stock"] == 30
    assert rows[0]["moq"] == 2


def test_valid_xlsx_file_parses_four_required_fields():
    rows, errors, _ = asyncio.run(server._read_import_file(_upload("products.xlsx", _xlsx_bytes())))

    assert not errors
    assert rows[0]["name"] == "ქართული ჩაი"
    assert rows[0]["price_per_unit"] == 12.5
    assert rows[0]["stock"] == 30
    assert rows[0]["moq"] == 2


def test_valid_xls_file_uses_excel_reader(monkeypatch=None):
    import pandas as pd
    from unittest.mock import patch

    frame = pd.DataFrame([{
        "Product Name": "ქართული ჩაი", "Price": 12.5,
        "Quantity": 30, "Minimum Quantity": 2,
    }])
    with patch.object(server.pd, "read_excel", return_value=frame) as reader:
        rows, errors, _ = asyncio.run(server._read_import_file(_upload("products.xls", b"BIFF workbook")))

    assert not errors
    assert rows[0]["name"] == "ქართული ჩაი"
    reader.assert_called_once()


def test_invalid_values_missing_name_and_empty_file_are_rejected():
    cases = [
        ("negative price", [["Tea", -1, 5, 1]]),
        ("negative quantity", [["Tea", 1, -5, 1]]),
        ("invalid minimum quantity", [["Tea", 1, 5, 0]]),
        ("missing name", [["", 1, 5, 1]]),
    ]
    for _, rows in cases:
        parsed, errors, _ = asyncio.run(server._read_import_file(_upload("products.csv", _csv_bytes(rows))))
        assert not parsed
        assert errors

    try:
        asyncio.run(server._read_import_file(_upload("empty.csv", b"")))
    except server.HTTPException as error:
        assert error.status_code == 400
    else:
        raise AssertionError("empty file should be rejected")


def test_external_product_id_and_sku_match_existing_product():
    existing = [{
        "id": "stable-product-id", "supplier_id": "supplier-1",
        "name": "ქართული ჩაი", "category": "სასმელები", "sku": "TEA-1",
        "price_per_unit": 10, "stock": 5,
    }]
    rows = [{"_row": 2, "external_id": "stable-product-id", "stock": 30}]
    plan, errors, duplicates = server._plan_product_import(rows, existing)

    assert not errors
    assert duplicates == 0
    assert plan[0]["match"]["id"] == "stable-product-id"
    assert plan[0]["row"]["stock"] == 30


def test_conflicting_duplicate_sku_blocks_import_plan():
    rows = [
        {"_row": 2, "sku": "TEA-1", "name": "ქართული ჩაი", "category": "სასმელები", "price_per_unit": 10, "stock": 5, "moq": 1},
        {"_row": 3, "sku": "TEA-1", "name": "ქართული ჩაი", "category": "სასმელები", "price_per_unit": 12, "stock": 5, "moq": 1},
    ]
    plan, errors, _ = server._plan_product_import(rows, [])

    assert plan
    assert any("ეწინააღმდეგება" in error["message"] for error in errors)


def test_identical_duplicate_rows_are_collapsed():
    row = {"_row": 2, "sku": "TEA-1", "name": "ქართული ჩაი", "category": "სასმელები", "price_per_unit": 10, "stock": 5, "moq": 1}
    duplicate = {**row, "_row": 3}
    plan, errors, duplicates = server._plan_product_import([row, duplicate], [])

    assert not errors
    assert len(plan) == 1
    assert duplicates == 1


def test_upload_persists_refreshes_updates_and_preserves_unrelated_products():
    with _client_with_supplier() as (client, database):
        unrelated = {
            "name": "Unrelated item", "category": "Groceries", "price_per_unit": 4,
            "stock": 10, "moq": 1,
        }
        created = client.post("/api/products", json=unrelated)
        assert created.status_code == 200
        unrelated_id = created.json()["id"]

        file_bytes = _csv_bytes([["ქართული ჩაი", 12.5, 30, 2, "TEA-1"]],
                                ("Product Name", "Price", "Quantity", "Minimum Quantity", "SKU"))
        imported = client.post("/api/products/upload-excel", files={"file": ("items.csv", file_bytes)})
        assert imported.status_code == 200, imported.text
        assert imported.json()["added"] == 1

        refreshed = client.get("/api/products", params={"supplier_id": "supplier-import-test"})
        assert refreshed.status_code == 200
        assert len(refreshed.json()) == 2
        imported_product = next(item for item in refreshed.json() if item["sku"] == "TEA-1")
        assert imported_product["stock"] == 30
        assert imported_product["moq"] == 2
        assert imported_product["image"].startswith("https://images.unsplash.com/")
        assert "ქართული ჩაი" in imported_product["description"]

        changed_bytes = _csv_bytes([["ქართული ჩაი", 14, 45, 3, "TEA-1"]],
                                   ("Product Name", "Price", "Quantity", "Minimum Quantity", "SKU"))
        updated = client.post("/api/products/upload-excel", files={"file": ("items.csv", changed_bytes)})
        assert updated.status_code == 200, updated.text
        assert updated.json()["added"] == 0
        assert updated.json()["updated"] == 1

        refreshed_again = client.get("/api/products", params={"supplier_id": "supplier-import-test"}).json()
        assert len(refreshed_again) == 2
        imported_product = next(item for item in refreshed_again if item["sku"] == "TEA-1")
        assert imported_product["price_per_unit"] == 14
        assert imported_product["stock"] == 45
        assert imported_product["category_id"]
        assert any(item["id"] == unrelated_id for item in refreshed_again)

        rejected = client.post(
            "/api/products/upload-excel",
            files={"file": ("bad.csv", _csv_bytes([["ქართული ჩაი", -1, 45, 3, "TEA-1"]],
                                                    ("Product Name", "Price", "Quantity", "Minimum Quantity", "SKU")))},
        )
        assert rejected.status_code == 422
        assert len(database.products.rows) == 2


def test_import_auto_assigns_and_persists_business_category_id():
    with _client_with_supplier() as (client, database):
        database.categories.rows.append({
            "id": "existing-beverages",
            "name": "სასმელი",
            "business_id": "supplier-import-test",
        })
        file_bytes = _csv_bytes([["Apple juice", 4, 12, 1]],
                                ("Product Name", "Price", "Quantity", "Minimum Quantity"))

        imported = client.post("/api/products/upload-excel", files={"file": ("items.csv", file_bytes)})

        assert imported.status_code == 200, imported.text
        product = database.products.rows[0]
        assert product["category"] == "სასმელი"
        assert product["category_id"] == "existing-beverages"
        assert len(database.categories.rows) == 1


def test_import_creates_business_category_for_category_map_synonym():
    with _client_with_supplier() as (client, database):
        file_bytes = _csv_bytes([["Milk", 4, 12, 1]],
                                ("Product Name", "Price", "Quantity", "Minimum Quantity"))

        imported = client.post("/api/products/upload-excel", files={"file": ("items.csv", file_bytes)})

        assert imported.status_code == 200, imported.text
        product = database.products.rows[0]
        assert product["category"] == "მშრალი პროდუქტები"
        category = database.categories.rows[0]
        assert category["name"] == product["category"]
        assert category["business_id"] == "supplier-import-test"
        assert product["category_id"] == category["id"]


def test_import_persists_category_id_for_explicit_category():
    with _client_with_supplier() as (client, database):
        file_bytes = _csv_bytes([["Coffee", "Groceries", 4, 12, 1]],
                                ("Product Name", "Category", "Price", "Quantity", "Minimum Quantity"))

        imported = client.post("/api/products/upload-excel", files={"file": ("items.csv", file_bytes)})

        assert imported.status_code == 200, imported.text
        product = database.products.rows[0]
        assert product["category"] == "სურსათი"
        assert product["category_id"] == database.categories.rows[0]["id"]
        assert database.categories.rows[0]["business_id"] == "supplier-import-test"


def test_import_update_assigns_category_id_to_existing_uncategorized_product():
    with _client_with_supplier() as (client, database):
        database.products.rows.append({
            "id": "uncategorized-product",
            "supplier_id": "supplier-import-test",
            "name": "Apple juice",
            "sku": "JUICE-1",
            "price_per_unit": 3,
            "stock": 4,
        })
        file_bytes = _csv_bytes([["Apple juice", 4, 20, 1, "JUICE-1"]],
                                ("Product Name", "Price", "Quantity", "Minimum Quantity", "SKU"))

        updated = client.post("/api/products/upload-excel", files={"file": ("items.csv", file_bytes)})

        assert updated.status_code == 200, updated.text
        product = database.products.rows[0]
        assert product["category"] == "სასმელები"
        assert product["category_id"] == database.categories.rows[0]["id"]
        assert product["stock"] == 20


def test_import_unknown_product_name_uses_business_other_category():
    with _client_with_supplier() as (client, database):
        file_bytes = _csv_bytes([["Novel widget", 4, 20, 1]],
                                ("Product Name", "Price", "Quantity", "Minimum Quantity"))

        imported = client.post("/api/products/upload-excel", files={"file": ("items.csv", file_bytes)})

        assert imported.status_code == 200, imported.text
        product = database.products.rows[0]
        assert product["category"] == "Other"
        assert product["category_id"]
        assert database.categories.rows[0]["name"] == "Other"
        assert database.categories.rows[0]["business_id"] == "supplier-import-test"


def test_manual_product_crud_persists_and_checks_supplier_ownership():
    with _client_with_supplier() as (client, database):
        product = {
            "name": "Manual tea", "category": "Groceries", "price_per_unit": 5,
            "stock": 8, "moq": 2, "sku": "MANUAL-1",
        }
        created = client.post("/api/products", json=product)
        assert created.status_code == 200
        product_id = created.json()["id"]
        assert created.json()["category_id"] == database.categories.rows[0]["id"]
        assert created.json()["image"].startswith("https://images.unsplash.com/")
        assert "Manual tea" in created.json()["description"]

        loaded = client.get("/api/products", params={"supplier_id": "supplier-import-test"})
        assert any(item["id"] == product_id for item in loaded.json())

        edited = {**product, "name": "Edited tea", "price_per_unit": 6, "stock": 9, "moq": 3}
        updated = client.put(f"/api/products/{product_id}", json=edited)
        assert updated.status_code == 200
        assert updated.json()["price_per_unit"] == 6
        assert updated.json()["stock"] == 9
        assert updated.json()["moq"] == 3
        assert updated.json()["category_id"] == created.json()["category_id"]
        assert updated.json()["image"] == created.json()["image"]

        server.app.dependency_overrides[server.get_current_user] = lambda: {
            "id": "different-supplier", "role": "supplier", "business_name": "Other",
        }
        assert client.delete(f"/api/products/{product_id}").status_code == 404

        server.app.dependency_overrides[server.get_current_user] = lambda: {
            "id": "supplier-import-test", "role": "supplier", "business_name": "Test Supplier",
        }
        deleted = client.delete(f"/api/products/{product_id}")
        assert deleted.status_code == 200
        assert not any(item["id"] == product_id for item in client.get("/api/products").json())


def test_supplier_role_is_required_for_import_and_product_creation():
    with _client_with_supplier() as (client, _):
        server.app.dependency_overrides[server.get_current_user] = lambda: {
            "id": "retailer-1", "role": "retailer", "business_name": "Retailer",
        }
        body = _csv_bytes([["Tea", 1, 5, 1]])
        assert client.post("/api/products/upload-excel", files={"file": ("items.csv", body)}).status_code == 403
        assert client.post("/api/products", json={
            "name": "Tea", "category": "Groceries", "price_per_unit": 1,
        }).status_code == 403


def test_real_mongodb_import_refresh_reimport_and_preserve_other_products():
    async def run():
        await server.client.admin.command("ping")
        supplier_id = f"import-test-{uuid.uuid4().hex}"
        sku = f"IMPORT-{uuid.uuid4().hex}"
        user = {"id": supplier_id, "role": "supplier", "business_name": "Import Test", "city": "Tbilisi"}
        server.app.dependency_overrides[server.get_current_user] = lambda: user
        transport = ASGITransport(app=server.app)
        try:
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                manual = await client.post("/api/products", json={
                    "name": "Manual CRUD", "category": "Groceries", "price_per_unit": 1,
                    "stock": 4, "moq": 1, "sku": f"CRUD-{uuid.uuid4().hex}",
                })
                assert manual.status_code == 200, manual.text
                manual_id = manual.json()["id"]
                edited = await client.put(f"/api/products/{manual_id}", json={
                    **manual.json(), "price_per_unit": 2, "stock": 6, "moq": 2,
                })
                assert edited.status_code == 200
                assert edited.json()["price_per_unit"] == 2
                assert edited.json()["stock"] == 6
                assert edited.json()["moq"] == 2
                deleted = await client.delete(f"/api/products/{manual_id}")
                assert deleted.status_code == 200

                unrelated = await client.post("/api/products", json={
                    "name": "Unrelated", "category": "Groceries", "price_per_unit": 4,
                    "stock": 8, "moq": 1, "sku": f"OTHER-{uuid.uuid4().hex}",
                })
                assert unrelated.status_code == 200, unrelated.text
                unrelated_id = unrelated.json()["id"]

                headers = ("Product Name", "Price", "Quantity", "Minimum Quantity", "SKU")
                first_data = _csv_bytes([["ქართული პროდუქტი", 2.5, 12, 2, sku]], headers)
                uploaded = await client.post(
                    "/api/products/upload-excel", files={"file": ("products.csv", first_data)},
                )
                assert uploaded.status_code == 200, uploaded.text
                assert uploaded.json()["added"] == 1

                refreshed = await client.get("/api/products", params={"supplier_id": supplier_id})
                assert refreshed.status_code == 200
                products = refreshed.json()
                assert len(products) == 2
                imported = next(product for product in products if product["sku"] == sku)
                assert imported["price_per_unit"] == 2.5
                assert imported["stock"] == 12
                assert imported["moq"] == 2

                second_data = _csv_bytes([["ქართული პროდუქტი", 3.5, 18, 3, sku]], headers)
                reimported = await client.post(
                    "/api/products/upload-excel", files={"file": ("products.csv", second_data)},
                )
                assert reimported.status_code == 200, reimported.text
                assert reimported.json()["added"] == 0
                assert reimported.json()["updated"] == 1

                final_products = (await client.get(
                    "/api/products", params={"supplier_id": supplier_id},
                )).json()
                assert len(final_products) == 2
                imported = next(product for product in final_products if product["sku"] == sku)
                assert imported["price_per_unit"] == 3.5
                assert imported["stock"] == 18
                assert any(product["id"] == unrelated_id for product in final_products)
        finally:
            await server.db.products.delete_many({"supplier_id": supplier_id})
            server.app.dependency_overrides.pop(server.get_current_user, None)

    asyncio.run(run())