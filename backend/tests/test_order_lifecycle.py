import server


def test_lifecycle_labels_map_internal_statuses():
    assert server.lifecycle_status({"status": "Pending"}) == "NEW"
    assert server.lifecycle_status({"status": "Processing"}) == "APPROVED"
    assert server.lifecycle_status({"status": "In Transit"}) == "IN_TRANSIT"
    assert server.lifecycle_status({"status": "Delivered"}) == "DELIVERED"
    assert server.lifecycle_status({"status": "Cancelled"}) == "CANCELLED"
    assert server.lifecycle_status({"status": "Cancelled", "rejected": True}) == "REJECTED"


def test_payment_fields_cover_unpaid_partial_and_paid():
    unpaid = server.order_payment_fields({"total": 100, "amount_paid": 0})
    assert unpaid == {"paymentStatus": "UNPAID", "paidAmount": 0.0, "totalAmount": 100.0, "balance": 100.0}
    partial = server.order_payment_fields({"total": 100, "amount_paid": 40})
    assert partial["paymentStatus"] == "PARTIAL" and partial["balance"] == 60.0
    paid = server.order_payment_fields({"total": 100, "amount_paid": 100})
    assert paid["paymentStatus"] == "PAID" and paid["balance"] == 0.0
    online = server.order_payment_fields({"total": 50, "paid_at_checkout": True})
    assert online["paymentStatus"] == "PAID"
