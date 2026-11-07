import { Search, SlidersHorizontal } from "lucide-react";
import { Input } from "@/components/ui/input";
import { useI18n } from "@/context/I18nContext";
import { productFilterOptions } from "@/lib/productFilters";

export default function ProductFilterBar({
  products, query, onQueryChange, sortBy, onSortChange,
  packageType, onPackageTypeChange, packageSize, onPackageSizeChange,
}) {
  const { t } = useI18n();
  const { packageTypes, packageSizes } = productFilterOptions(products);
  const selectClass = "h-11 min-w-0 w-full rounded-md border border-border bg-background px-3 text-sm text-foreground";

  return (
    <div className="grid min-w-0 flex-1 grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4" data-testid="product-filter-bar">
      <div className="relative min-w-0">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder={t("catalog.productSearch")}
          className="h-11 pl-9"
          data-testid="product-live-search"
        />
      </div>
      <label className="relative min-w-0">
        <span className="sr-only">{t("catalog.priceSort")}</span>
        <SlidersHorizontal className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <select value={sortBy} onChange={(event) => onSortChange(event.target.value)} className={`${selectClass} pl-9`} data-testid="product-price-sort">
          <option value="default">{t("catalog.sortDefault")}</option>
          <option value="price_asc">{t("catalog.priceLowHigh")}</option>
          <option value="price_desc">{t("catalog.priceHighLow")}</option>
        </select>
      </label>
      {packageTypes.length > 0 && (
        <label className="min-w-0">
          <span className="sr-only">{t("catalog.packageType")}</span>
          <select value={packageType} onChange={(event) => onPackageTypeChange(event.target.value)} className={selectClass} data-testid="product-package-type-filter">
            <option value="">{t("catalog.allPackageTypes")}</option>
            {packageTypes.map((option) => <option key={option} value={option}>{option}</option>)}
          </select>
        </label>
      )}
      {packageSizes.length > 0 && (
        <label className="min-w-0">
          <span className="sr-only">{t("catalog.packageSize")}</span>
          <select value={packageSize} onChange={(event) => onPackageSizeChange(event.target.value)} className={selectClass} data-testid="product-package-size-filter">
            <option value="">{t("catalog.allPackageSizes")}</option>
            {packageSizes.map((option) => <option key={option} value={option}>{option}</option>)}
          </select>
        </label>
      )}
    </div>
  );
}