export const GEORGIAN_BANKS = [
  "საქართველოს ბანკი",
  "თიბისი ბანკი",
  "ლიბერთი ბანკი",
  "პროკრედიტ ბანკი",
  "ტერაბანკი",
  "ბაზისბანკი",
  "კრედო ბანკი",
  "ხალიკ ბანკი",
  "ვითიბი ბანკი",
];

export const normalizeIban = (v) => (v || "").replace(/\s+/g, "").toUpperCase();
export const isValidGeIban = (v) => !v || /^GE\d{2}[A-Z]{2}\d{16}$/.test(normalizeIban(v));
