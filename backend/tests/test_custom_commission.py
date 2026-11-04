import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server

PLATFORM = {"fee_type": "percent", "fee_value": 5.0, "fee_payer": "supplier"}


def test_platform_default_without_custom_commission():
    resolved = server.resolve_commission(PLATFORM, {"id": "s"}, {"id": "d"})
    assert resolved["fee_source"] == "platform"
    assert server.compute_fee(200, resolved) == 10.0


def test_store_custom_commission_overrides_supplier_and_platform():
    store = {"customCommissionType": "fixed", "customCommissionValue": 3, "commissionPayer": "retailer"}
    supplier = {"customCommissionType": "percent", "customCommissionValue": 1}
    resolved = server.resolve_commission(PLATFORM, store, supplier)
    assert (resolved["fee_source"], resolved["fee_payer"]) == ("store", "retailer")
    assert server.compute_fee(200, resolved) == 3.0


def test_supplier_custom_commission_used_when_store_has_none():
    supplier = {"customCommissionType": "percent", "customCommissionValue": 2.5}
    resolved = server.resolve_commission(PLATFORM, {}, supplier)
    assert resolved["fee_source"] == "supplier"
    assert resolved["fee_payer"] == "supplier"
    assert server.compute_fee(200, resolved) == 5.0
