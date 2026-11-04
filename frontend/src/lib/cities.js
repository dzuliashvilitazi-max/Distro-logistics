// Keep in sync with GEORGIAN_CITIES in backend/server.py (server validates against it).
export const GEORGIAN_CITIES = [
  "თბილისი", "ბათუმი", "ქუთაისი", "რუსთავი", "გორი", "ზუგდიდი", "ფოთი", "ხაშური", "სამტრედია",
  "სენაკი", "ზესტაფონი", "მარნეული", "თელავი", "ახალციხე", "ქობულეთი", "ოზურგეთი", "კასპი",
  "ჭიათურა", "წყალტუბო", "საგარეჯო", "გარდაბანი", "ბორჯომი", "თერჯოლა", "ახალქალაქი", "ქარელი",
  "ლანჩხუთი", "დუშეთი", "მცხეთა", "საჩხერე", "დედოფლისწყარო", "ლაგოდეხი", "ახმეტა", "ყვარელი",
  "გურჯაარი", "სიღნაღი", "წნორი", "თიანეთი", "ბოლნისი", "დმანისი", "წალკა", "თეთრიწყარო",
  "ახალგორი", "ბაღდათი", "ვანი", "ტყიბული", "ხონი", "წალენჯიხა", "ხობი", "აბაშა", "მარტვილი",
  "ჩოხატაური", "ხელვაჩაური", "ქედა", "შუახევი", "ხულო", "კარელი", "ადიგენი", "ასპინძა",
  "ამბროლაური", "ონი", "ცაგერი", "ლენტეხი", "მესტია", "ნინოწმინდა", "ბაკურიანი", "გუდაური",
  "ყაზბეგი", "ჯავა",
];

export const ALL_CITIES = "All";

const LATIN_ALIASES = {
  tbilisi: "თბილისი", batumi: "ბათუმი", kutaisi: "ქუთაისი", rustavi: "რუსთავი", gori: "გორი",
  khashuri: "ხაშური", zugdidi: "ზუგდიდი", poti: "ფოთი", senaki: "სენაკი", telavi: "თელავი",
  akhaltsikhe: "ახალციხე", kobuleti: "ქობულეთი", ozurgeti: "ოზურგეთი", marneuli: "მარნეული",
};

const LATIN_BY_CITY = Object.fromEntries(Object.entries(LATIN_ALIASES).map(([latin, city]) => [city, latin]));

export const canonCity = (value) => {
  const clean = String(value || "").trim();
  return LATIN_ALIASES[clean.toLowerCase()] || clean;
};

export const isAllCities = (values = []) =>
  values.some((value) => ["all", "all cities", "ყველა", "ყველა ქალაქი"].includes(String(value).trim().toLowerCase()));

// Matches Georgian names and their Latin spellings, case-insensitively.
export const searchCities = (query = "") => {
  const q = String(query).trim().toLowerCase();
  if (!q) return GEORGIAN_CITIES;
  return GEORGIAN_CITIES.filter((city) =>
    city.toLowerCase().includes(q) || (LATIN_BY_CITY[city] || "").includes(q));
};
