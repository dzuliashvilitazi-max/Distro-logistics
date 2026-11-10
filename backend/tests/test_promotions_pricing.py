import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from test_product_offers import Collection, SUPPLIER, STORE, SimpleNamespace


def run_pricing(monkeypatch, custom_price, promo_price):
    database = SimpleNamespace(
        store_distributor_connections=Collection([{
            "store_id": STORE["id"], "distributor_id": SUPPLIER["id"],
            "status": "APPROVED", "discount_percent": 0,
        }]),
        custom_prices=Collection(
            [{"store_id": STORE["id"], "distributor_id": SUPPLIER["id"], "product_id": "p1", "custom_price": custom_price}]
            if custom_price is not None else []
        ),
    )
    monkeypatch.setattr(server, "db", database)

    async def promos(_ids):
        return {"p1": {"promo_price": promo_price, "starts_at": "s", "ends_at": "e"}}

    monkeypatch.setattr(server, "_active_promotions", promos)
    product = {"id": "p1", "supplier_id": SUPPLIER["id"], "price_per_unit": 10.0, "tier_pricing": []}
    return asyncio.run(server._apply_partner_pricing([product], STORE["id"]))[0]


def test_lower_individual_price_is_kept(monkeypatch):
    product = run_pricing(monkeypatch, 6.0, 8.0)
    assert float(product["price"]) == 6.0
    assert product["is_promo"] is True


def test_higher_individual_price_gets_promo(monkeypatch):
    assert float(run_pricing(monkeypatch, 9.0, 8.0)["price"]) == 8.0


def test_no_individual_price_gets_promo(monkeypatch):
    assert float(run_pricing(monkeypatch, None, 8.0)["price"]) == 8.0
