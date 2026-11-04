import asyncio
import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
server = importlib.import_module("server")


def test_zoo_sees_pet_and_custom_but_not_beverages():
    allowed = asyncio.run(server._allowed_categories_for_user(
        {"id": "r1", "role": "retailer", "establishment_type": "zoo"}))
    assert server._category_allowed("Pet Supplies", allowed)
    assert server._category_allowed("My Custom Category", allowed)
    assert not server._category_allowed("Beverages", allowed)


def test_other_type_and_non_retailers_are_unrestricted():
    assert asyncio.run(server._allowed_categories_for_user(
        {"id": "r1", "role": "retailer", "establishment_type": "other"})) is None
    assert asyncio.run(server._allowed_categories_for_user({"id": "s1", "role": "supplier"})) is None
    assert asyncio.run(server._allowed_categories_for_user(None)) is None


def test_restaurant_categories_exclude_pet_supplies():
    allowed = asyncio.run(server._allowed_categories_for_user(
        {"id": "r1", "role": "retailer", "entityType": "restaurant_cafe_bar"}))
    assert allowed == {"Beverages", "Groceries", "Dry Goods", "Household Chemicals", "Hygiene", "Packaging"}


def test_hotel_and_pet_shop_categories():
    hotel = asyncio.run(server._allowed_categories_for_user(
        {"id": "r1", "role": "retailer", "businessType": "hotel_hostel"}))
    assert hotel == {"Household Chemicals", "Hygiene", "Packaging", "Beverages", "Dry Goods"}

    pet_shop = asyncio.run(server._allowed_categories_for_user(
        {"id": "r1", "role": "retailer", "establishment_type": "pet_shop"}))
    assert pet_shop == {"Pet Supplies", "Household Chemicals"}


def test_supplier_sector_matching_supports_zoo_alias():
    assert server._supplier_serves_entity(
        {"business_sectors": ["zoo", "restaurant_cafe_bar"]}, "pet_shop")


def test_georgian_entity_labels_normalize_to_catalog_sectors():
    assert server._normalize_business_sector("სასურსათო მაღაზია") == "grocery"
    assert server._normalize_business_sector("რესტორანი / კაფე / ბარი") == "restaurant_cafe_bar"
    assert server._normalize_business_sector("ოფისი / კომპანია") == "office_company"


def test_entity_group_assignment():
    for t in ("grocery", "zoo", "household", "ზოო მაღაზია"):
        assert server._entity_group_for_type(t) == "RETAIL"
    for t in ("restaurant_cafe_bar", "hotel_hostel", "laundry", "office_company", "other", ""):
        assert server._entity_group_for_type(t) == "SERVICE"


def test_city_matching_with_aliases_and_all_cities():
    assert server._supplier_serves_city({"cities": ["Tbilisi"]}, "თბილისი")
    assert not server._supplier_serves_city({"cities": ["ბათუმი"]}, "თბილისი")
    assert server._supplier_serves_city({"cities": ["ყველა ქალაქი"]}, "ფოთი")
    assert server._normalize_service_cities(["Batumi", "ქუთაისი"]) == ["ბათუმი", "ქუთაისი"]


def test_service_types_have_sector_specific_category_sets():
    laundry = asyncio.run(server._allowed_categories_for_user(
        {"id": "r1", "role": "retailer", "establishment_type": "laundry"}))
    assert laundry == {"Household Chemicals", "Hygiene", "Packaging"}

    office = asyncio.run(server._allowed_categories_for_user(
        {"id": "r1", "role": "retailer", "establishment_type": "office_company"}))
    assert office == {"Household Chemicals", "Hygiene", "Packaging", "Beverages", "Dry Goods"}
