export const normalizeEntityType = (value) => {
  const type = String(value || "").trim().toLowerCase();
  const aliases = {
    "სასურსათო მაღაზია": "grocery",
    "ზოო მაღაზია": "pet_shop",
    zoo: "pet_shop",
    "საყოფაცხოვრებო საქონლის მაღაზია": "household",
    "რესტორანი / კაფე / ბარი": "restaurant_cafe_bar",
    "სასტუმრო / ჰოსტელი": "hotel_hostel",
    "სამრეცხაო": "laundry",
    "ოფისი / კომპანია": "office_company",
  };
  return aliases[type] || type.replace(/[\s/-]+/g, "_");
};

export const SECTOR_CATEGORY_MAPPING = {
  grocery: ["Beverages", "Groceries", "Snacks & Sweets", "Dry Goods", "Household Chemicals", "Packaging", "Hygiene"],
  pet_shop: ["Pet Supplies", "Household Chemicals"],
  household: ["Household Chemicals", "Hygiene", "Packaging"],
  laundry: ["Household Chemicals", "Hygiene", "Packaging"],
  restaurant_cafe_bar: ["Beverages", "Groceries", "Dry Goods", "Household Chemicals", "Hygiene", "Packaging"],
  hotel_hostel: ["Household Chemicals", "Hygiene", "Packaging", "Beverages", "Dry Goods"],
  office_company: ["Household Chemicals", "Hygiene", "Packaging", "Beverages", "Dry Goods"],
};
