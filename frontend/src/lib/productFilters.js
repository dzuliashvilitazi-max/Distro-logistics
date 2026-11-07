const PACKAGE_SIZE_PATTERN = /\b\d+(?:[.,]\d+)?\s?(?:ml|l|cl|g|kg|mg|oz|lb|მლ|ლ|გ|გრ|კგ|მგ|ცალი|შტ)/i;

export function productPackageType(product) {
  return String(
    product?.packaging_type || product?.packagingType || product?.package_type || product?.packaging || product?.unit || "",
  ).trim();
}

export function productPackageSize(product) {
  const explicit = product?.package_size || product?.package_volume || product?.volume
    || product?.net_weight || product?.unit_size;
  if (explicit) return String(explicit).trim();
  const searchableText = [product?.unit, product?.name, product?.description].filter(Boolean).join(" ");
  return searchableText.match(PACKAGE_SIZE_PATTERN)?.[0]?.replace(/\s+/g, "") || "";
}

export function productFilterOptions(products) {
  return {
    packageTypes: [...new Set(products.map(productPackageType).filter(Boolean))].sort((a, b) => a.localeCompare(b)),
    packageSizes: [...new Set(products.map(productPackageSize).filter(Boolean))].sort((a, b) => a.localeCompare(b, undefined, { numeric: true })),
  };
}

export function filterAndSortProducts(products, { query = "", sortBy = "default", packageType = "", packageSize = "", inStockOnly = false } = {}) {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const filtered = products.filter((product) => (
    (!normalizedQuery || String(product.name || "").toLocaleLowerCase().includes(normalizedQuery))
    && (!packageType || productPackageType(product) === packageType)
    && (!packageSize || productPackageSize(product) === packageSize)
    && (!inStockOnly || Number(product.stock) > 0)
  ));
  if (sortBy === "price_asc") filtered.sort((left, right) => Number(left.price_per_unit || 0) - Number(right.price_per_unit || 0));
  else if (sortBy === "price_desc") filtered.sort((left, right) => Number(right.price_per_unit || 0) - Number(left.price_per_unit || 0));
  return filtered;
}