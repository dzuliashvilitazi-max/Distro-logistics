import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from invoices import build_order_invoice_pdf


ORDER = {
    "id": "o1", "order_no": "ORD-1", "total": 8.0, "service_fee": 0.24, "fee_type": "percent",
    "fee_value": 3, "fee_payer": "supplier", "supplier_payout": 7.76, "platform_split": {"x": 1},
    "items": [{"product_id": "p", "name": "Tea", "quantity": 2, "unit_price": 4.0, "list_price": 5.0}],
}


def test_store_view_has_no_commission_fields():
    view = server.hide_commission_from_store(ORDER)
    assert not set(server.COMMISSION_ORDER_FIELDS) & set(view)
    assert view["total"] == 8.0


def test_distributor_breakdown():
    breakdown = server.commission_breakdown(ORDER)
    assert (breakdown["base_amount"], breakdown["commission"], breakdown["distributor_net"]) == (8.0, 0.24, 7.76)


def test_invoice_pdf_renders_with_discounts():
    pdf = build_order_invoice_pdf(ORDER, supplier={"business_name": "S"}, buyer={"business_name": "B"})
    assert pdf.startswith(b"%PDF")
