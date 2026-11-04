import copy
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class MemoryCollection:
    def __init__(self, rows):
        self.rows = copy.deepcopy(rows)

    async def find_one(self, query, projection=None):
        return next((copy.deepcopy(row) for row in self.rows if all(row.get(key) == value for key, value in query.items())), None)


def test_supplier_can_download_printable_georgian_waybill():
    order = {
        "id": "order-waybill-1", "order_no": "ORD-12345678", "supplier_id": "supplier-1",
        "retailer_id": "retailer-1", "status": "Processing", "supplier_name": "Seller LLC",
        "retailer_name": "Buyer LLC", "delivery_address": "Tbilisi", "total": 25,
        "items": [{"name": "ქართული ჩაი", "quantity": 2, "unit_price": 12.5}],
    }
    users = [
        {"id": "supplier-1", "role": "supplier", "business_name": "Seller LLC", "identification_number": "123456789", "address": "Seller address", "phone": "555111111"},
        {"id": "retailer-1", "role": "retailer", "business_name": "Buyer LLC", "identification_number": "987654321", "address": "Buyer address", "phone": "555222222"},
    ]
    original_db = server.db
    original_overrides = dict(server.app.dependency_overrides)
    server.db = type("MemoryDB", (), {"orders": MemoryCollection([order]), "users": MemoryCollection(users)})()
    server.app.dependency_overrides[server.get_current_user] = lambda: {"id": "supplier-1", "role": "supplier"}
    try:
        response = TestClient(server.app).post("/api/orders/order-waybill-1/waybill", json={
            "driver_name": "Driver Example", "driver_id": "01010101010",
            "vehicle_plate": "AA-123-AA", "transport_type": "სატვირთო ავტომობილი",
        })
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert response.headers["content-disposition"].endswith('.html"')
        assert "სასაქონლო ზედნადები" in response.text
        assert "ORD-12345678" in response.text
        assert "ქართული ჩაი" in response.text
        assert "არ არის შემოსავლების სამსახურში რეგისტრირებული" in response.text
    finally:
        server.db = original_db
        server.app.dependency_overrides.clear()
        server.app.dependency_overrides.update(original_overrides)


def test_waybill_rejected_for_unaccepted_order():
    order = {"id": "pending-order", "supplier_id": "supplier-1", "status": "Pending"}
    original_db = server.db
    original_overrides = dict(server.app.dependency_overrides)
    server.db = type("MemoryDB", (), {"orders": MemoryCollection([order]), "users": MemoryCollection([])})()
    server.app.dependency_overrides[server.get_current_user] = lambda: {"id": "supplier-1", "role": "supplier"}
    try:
        response = TestClient(server.app).post("/api/orders/pending-order/waybill", json={
            "driver_name": "Driver", "vehicle_plate": "AA-123-AA",
        })
        assert response.status_code == 409
    finally:
        server.db = original_db
        server.app.dependency_overrides.clear()
        server.app.dependency_overrides.update(original_overrides)