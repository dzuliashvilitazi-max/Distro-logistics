import { useEffect, useMemo, useState } from "react";
import { api, tierPrice } from "@/lib/api";
import { LogoAvatar } from "@/components/BusinessLogo";
import ProductImage from "@/components/ProductImage";
import { useCart } from "@/context/CartContext";
import { useSearchParams } from "react-router-dom";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { categoryKey } from "@/lib/i18n";
import { normalizeEntityType, SECTOR_CATEGORY_MAPPING } from "@/lib/businessEntity";
import { filterAndSortProducts } from "@/lib/productFilters";
import { ArrowLeft, Search, Filter, Plus, Minus, Package, Layers } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import ProductFilterBar from "@/components/ProductFilterBar";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

// Custom categories outside the standard list are never hidden (mirrors backend _category_allowed).
const STANDARD_CATEGORIES = new Set(Object.values(SECTOR_CATEGORY_MAPPING).flat());
import { CityMultiSelect } from "@/components/CityMultiSelect";
import { isAllCities } from "@/lib/cities";
import SmartInventoryWidget from "@/components/SmartInventoryWidget";
import PromoCountdown from "@/components/PromoCountdown";

export default function Catalog() {
  const { t } = useI18n();
  const { user } = useAuth();
  const entityType = normalizeEntityType(user?.entityType || user?.businessType || user?.business_type || user?.entity_type || user?.establishment_type);
  const relevantCategories = SECTOR_CATEGORY_MAPPING[entityType];
  const [searchParams] = useSearchParams();
  const [products, setProducts] = useState([]);
  const [cats, setCats] = useState([]);
  const [distributors, setDistributors] = useState([]);
  const [globalDistributors, setGlobalDistributors] = useState([]);
  const [selectedCategory, setSelectedCategory] = useState(null);
  const [selectedDistributor, setSelectedDistributor] = useState(null);
  const [cityFilter, setCityFilter] = useState([]);
  const city = isAllCities(cityFilter) ? "" : cityFilter.join(",");
  const [search, setSearch] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [inStockOnly, setInStockOnly] = useState(false);
  const [priceSort, setPriceSort] = useState("default");
  const [packageType, setPackageType] = useState("");
  const [packageSize, setPackageSize] = useState("");
  const [selected, setSelected] = useState(null);
  const [negotiatingProduct, setNegotiatingProduct] = useState(null);
  const [loadingDistributors, setLoadingDistributors] = useState(false);
  const [loadingProducts, setLoadingProducts] = useState(false);
  const [pendingIds, setPendingIds] = useState([]);
  const [approvedIds, setApprovedIds] = useState([]);
  useEffect(() => {
    api.get("/connections/mine")
      .then(({ data }) => {
        setPendingIds(data.filter((c) => c.status === "PENDING").map((c) => c.distributor_id));
        setApprovedIds(data.filter((c) => c.status === "APPROVED").map((c) => c.distributor_id));
      })
      .catch(() => {});
  }, []);
  const { addItem } = useCart();

  useEffect(() => {
    setPriceSort("default");
    setPackageType("");
    setPackageSize("");
    setInStockOnly(false);
  }, [selectedCategory, selectedDistributor?.id]);

  useEffect(() => {
    const distributorId = searchParams.get("distributor_id");
    if (!distributorId) return;
    let active = true;
    api.get("/connections/mine")
      .then(({ data }) => {
        if (!active) return;
        const connection = data.find((item) => item.distributor_id === distributorId && item.status === "APPROVED");
        if (!connection) {
          toast.error("ამ დისტრიბუტორთან აქტიური კავშირი ვერ მოიძებნა");
          return;
        }
        const distributorSectors = connection.distributor?.servedSectors || connection.distributor?.business_sectors || [];
        if (entityType && !distributorSectors.some((sector) => normalizeEntityType(sector) === entityType)) {
          toast.error("ეს დისტრიბუტორი თქვენი ბიზნესის ტიპს არ ემსახურება");
          return;
        }
        setSelectedCategory("All Products");
        setSelectedDistributor({
          id: distributorId,
          business_name: connection.distributor?.business_name || connection.distributor?.name || "",
          logo_url: connection.distributor?.logo_url,
          servedSectors: distributorSectors,
        });
      })
      .catch((error) => toast.error(error?.response?.data?.detail || t("catalog.loadError")));
    return () => { active = false; };
  }, [searchParams, t, entityType]);

  useEffect(() => {
    const productId = searchParams.get("product_id");
    if (!productId || !products.some((product) => product.id === productId)) return;
    const timer = setTimeout(() => {
      document.querySelector(`[data-testid="product-card-${CSS.escape(productId)}"]`)?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    }, 50);
    return () => clearTimeout(timer);
  }, [products, searchParams]);

  useEffect(() => {
    let active = true;
    setCats([]);
    const params = city ? { city } : {};
    api.get("/products", { params })
      .then(({ data }) => {
        if (!active) return;
        const productCategories = Array.isArray(data)
          ? data.map((product) => {
            const raw = product.category ?? product.categoryId ?? product.category_id;
            const value = raw && typeof raw === "object" ? (raw.name ?? raw.id) : raw;
            return typeof value === "string" ? value.trim() : "";
          }).filter(Boolean)
          : [];
        setCats([...new Set(productCategories)]);
      })
      .catch(() => toast.error(t("catalog.loadError")));
    return () => { active = false; };
  }, [city, t]);

  useEffect(() => {
    const timer = setTimeout(() => setSearchQuery(search.trim()), 250);
    return () => clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    if (selectedCategory || !searchQuery) {
      setGlobalDistributors([]);
      return;
    }
    let active = true;
    const params = { search: searchQuery };
    if (city) params.city = city;
    api.get("/distributors", { params })
      .then((response) => {
        if (active) setGlobalDistributors(response.data.filter((distributor) =>
          !entityType || (distributor.servedSectors || []).some((sector) => normalizeEntityType(sector) === entityType)
        ));
      })
      .catch(() => toast.error(t("catalog.loadError")));
    return () => { active = false; };
  }, [selectedCategory, city, searchQuery, entityType, t]);

  useEffect(() => {
    if (!selectedCategory || selectedDistributor) return;
    let active = true;
    setLoadingDistributors(true);
    const params = {};
    if (selectedCategory !== "All Products") params.category = selectedCategory;
    if (city) params.city = city;
    if (searchQuery) params.search = searchQuery;
    api.get("/distributors", { params })
      .then((response) => {
        if (active) setDistributors(response.data.filter((distributor) =>
          !entityType || (distributor.servedSectors || []).some((sector) => normalizeEntityType(sector) === entityType)
        ));
      })
      .catch(() => toast.error(t("catalog.loadError")))
      .finally(() => { if (active) setLoadingDistributors(false); });
    return () => { active = false; };
  }, [selectedCategory, selectedDistributor, city, searchQuery, entityType, t]);

  useEffect(() => {
    if (!selectedDistributor) return;
    const distributorSectors = selectedDistributor.servedSectors || selectedDistributor.business_sectors || [];
    if (entityType && !distributorSectors.some((sector) => normalizeEntityType(sector) === entityType)) {
      setProducts([]);
      setLoadingProducts(false);
      return;
    }
    let active = true;
    setLoadingProducts(true);
    const params = { supplier_id: selectedDistributor.id };
    if (selectedCategory !== "All Products") params.category = selectedCategory;
    if (city) params.city = city;
    api.get("/products", { params })
      .then((response) => { if (active) setProducts(response.data); })
      .catch(() => toast.error(t("catalog.loadError")))
      .finally(() => { if (active) setLoadingProducts(false); });
    return () => { active = false; };
  }, [selectedDistributor, selectedCategory, city, entityType, t]);

  const visibleCategories = useMemo(() => [...new Set(["All Products", ...cats])].filter((item) =>
    (item === "All Products" || !relevantCategories || relevantCategories.includes(item) || !STANDARD_CATEGORIES.has(item))
    && (!searchQuery || t(categoryKey(item)).toLowerCase().includes(searchQuery.toLowerCase()))
  ), [cats, relevantCategories, searchQuery, t]);
  const filteredProducts = useMemo(() => filterAndSortProducts(products, {
    query: search,
    sortBy: priceSort,
    packageType,
    packageSize,
    inStockOnly,
  }), [products, search, priceSort, packageType, packageSize, inStockOnly]);
  const requestConnection = async (distributorId) => {
    try {
      await api.post("/connections/request", { distributor_id: distributorId });
      toast.success("მოთხოვნა გაგზავნილია დისტრიბუტორთან");
    } catch (error) {
      // 409 means a request already exists (pending/approved)
      if (error?.response?.status !== 409) {
        toast.error(error?.response?.data?.detail || t("catalog.loadError"));
        return;
      }
    }
    setPendingIds((ids) => [...ids, distributorId]);
  };
  const goBack = () => {
    if (selectedDistributor) setSelectedDistributor(null);
    else setSelectedCategory(null);
  };
  const openGlobalDistributor = (distributor) => {
    setSelectedCategory("All Products");
    setSelectedDistributor(distributor);
  };

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{t("catalog.title")}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{t("catalog.subtitle")}</p>
      </div>

      <div className="mb-6">
        <SmartInventoryWidget mode="retailer" />
      </div>

      <div className="mb-6 flex min-w-0 flex-col gap-3 lg:flex-row lg:items-center">
        {selectedDistributor ? (
          <ProductFilterBar
            products={products}
            query={search}
            onQueryChange={setSearch}
            sortBy={priceSort}
            onSortChange={setPriceSort}
            packageType={packageType}
            onPackageTypeChange={setPackageType}
            packageSize={packageSize}
            onPackageSizeChange={setPackageSize}
          />
        ) : (
          <div className="relative min-w-0 flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t("catalog.searchPlaceholder")} className="pl-9" data-testid="catalog-search" />
          </div>
        )}
        {selectedDistributor && <Button variant={inStockOnly ? "default" : "outline"} onClick={() => setInStockOnly((value) => !value)} data-testid="filter-instock">
          <Filter className="mr-1.5 h-4 w-4" /> {t("catalog.inStockOnly")}
        </Button>}
        {!user?.city && <CityMultiSelect value={cityFilter} onChange={(next) => { setCityFilter(next); setSelectedDistributor(null); }} idPrefix="city-filter" placeholder={t("catalog.allCities")} className="w-full lg:w-72" />}
      </div>

      {(selectedCategory || selectedDistributor) && <div className="mb-5 flex flex-wrap items-center gap-3">
        <Button variant="ghost" onClick={goBack}><ArrowLeft className="mr-2 h-4 w-4" />{selectedDistributor ? t("catalog.backToDistributors") : t("catalog.backToCategories")}</Button>
        <span className="text-sm text-muted-foreground">{selectedCategory && t(categoryKey(selectedCategory))}{selectedDistributor && ` / ${selectedDistributor.business_name}`}</span>
      </div>}

      {!selectedCategory && <section>
        <h2 className="mb-3 text-lg font-semibold">{t("catalog.categories")}</h2>
        {visibleCategories.length ? <div className="flex min-w-0 gap-2 overflow-x-auto pb-2" data-testid="catalog-category-quick-pick">
          {visibleCategories.map((item, index) => (
            <button key={`${item}-${index}`} type="button" onClick={() => setSelectedCategory(item)} data-testid={`category-${item.replace(/\s|&/g, "-")}`}
              className="flex min-h-14 min-w-36 shrink-0 items-center justify-between gap-4 rounded-lg border border-border bg-card px-4 py-3 text-left text-sm font-semibold transition-colors hover:border-primary/50 hover:bg-secondary/40">
              <span>{t(categoryKey(item))}</span><span aria-hidden="true">›</span>
            </button>
          ))}
        </div> : <p className="py-10 text-center text-sm text-muted-foreground">{t("catalog.noMatch")}</p>}
      </section>}

      {!selectedCategory && searchQuery && <section className="mt-7">
        <h2 className="mb-3 text-lg font-semibold">{t("catalog.distributors")}</h2>
        {globalDistributors.length ? <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {globalDistributors.map((distributor) => (
            <button key={distributor.id} type="button" onClick={() => openGlobalDistributor(distributor)}
              className="flex min-h-24 flex-col justify-between rounded-lg border border-border bg-card p-4 text-left transition-colors hover:border-primary/50 hover:bg-secondary/40">
              <span className="flex items-center gap-2.5"><LogoAvatar logo={distributor.logo_url} name={distributor.business_name} className="h-9 w-9 shrink-0 text-sm" /><span className="font-semibold">{distributor.business_name}</span></span>
              <span className="mt-2 text-xs text-muted-foreground">{distributor.cities?.some((value) => ["all", "ყველა"].includes(value.toLowerCase())) ? t("catalog.allCities") : distributor.cities?.join(", ") || distributor.city}</span>
              <span className="mt-2 font-mono text-[11px] text-muted-foreground">{distributor.product_count} {t("catalog.productsCount")}</span>
            </button>
          ))}
        </div> : <p className="py-5 text-sm text-muted-foreground">{t("catalog.noDistributors")}</p>}
      </section>}

      {selectedCategory && !selectedDistributor && <section>
        <h2 className="mb-3 text-lg font-semibold">{t("catalog.distributors")}</h2>
        {loadingDistributors ? <p className="py-10 text-center text-sm text-muted-foreground">{t("catalog.loading")}</p>
          : distributors.length ? <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {distributors.map((distributor) => {
              const servesEverywhere = distributor.cities?.some((value) => ["all", "ყველა"].includes(value.toLowerCase()));
              return <button key={distributor.id} type="button" onClick={() => setSelectedDistributor(distributor)}
                className="flex min-h-28 flex-col justify-between rounded-lg border border-border bg-card p-4 text-left transition-colors hover:border-primary/50 hover:bg-secondary/40">
                <span className="flex items-center gap-2.5"><LogoAvatar logo={distributor.logo_url} name={distributor.business_name} className="h-9 w-9 shrink-0 text-sm" /><span className="font-semibold">{distributor.business_name}</span></span>
                <span className="mt-2 text-xs text-muted-foreground">{servesEverywhere ? t("catalog.allCities") : distributor.cities?.join(", ") || distributor.city}</span>
                <span className="mt-2 font-mono text-[11px] text-muted-foreground">{distributor.product_count} {t("catalog.productsCount")}</span>
              </button>;
            })}
          </div> : <p className="py-10 text-center text-sm text-muted-foreground">{t("catalog.noDistributors")}</p>}
      </section>}

      {selectedDistributor && <section>
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <h2 className="text-lg font-semibold">{t("catalog.products")}: {selectedDistributor.business_name}</h2>
          {!approvedIds.includes(selectedDistributor.id) && (
            pendingIds.includes(selectedDistributor.id)
              ? <Button size="sm" variant="secondary" disabled data-testid="vendor-connection-pending">⏳ მოთხოვნა გაგზავნილია</Button>
              : <Button size="sm" onClick={() => requestConnection(selectedDistributor.id)} data-testid="vendor-connect">🔗 დისტრიბუტორთან დაკავშირება</Button>
          )}
        </div>
        {loadingProducts ? <p className="py-10 text-center text-sm text-muted-foreground">{t("catalog.loading")}</p>
          : filteredProducts.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border py-20 text-center">
              <Package className="h-10 w-10 text-muted-foreground" />
              <p className="mt-3 text-sm text-muted-foreground">{t("catalog.noMatch")}</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {filteredProducts.map((p) => {
                const canOrder = approvedIds.includes(p.supplier_id);
                const isPending = pendingIds.includes(p.supplier_id);
                return (
                  <div key={p.id} data-testid={`product-card-${p.id}`} className="group flex h-full min-w-0 flex-col justify-between overflow-hidden rounded-xl border border-border bg-card transition-all duration-200 hover:border-primary/40 hover:shadow-lg">
                    <div className="relative aspect-[4/3] overflow-hidden bg-secondary">
                      <ProductImage image={p.image} name={p.name} category={p.category} alt={p.name} className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105" />
                      <Badge className="absolute left-3 top-3 bg-background/90 text-foreground backdrop-blur">{t(categoryKey(p.category))}</Badge>
                      {p.is_promo && <Badge className="absolute bottom-3 left-3 bg-rose-600 text-white" data-testid={`promo-badge-${p.id}`}>აქციაშია</Badge>}
                      {p.stock <= 0 ? <Badge className="absolute right-3 top-3 bg-rose-500 text-white">{t("catalog.outOfStock")}</Badge>
                        : p.stock < 50 ? <Badge className="absolute right-3 top-3 bg-processing text-background">{t("catalog.low")}: {p.stock}</Badge> : null}
                    </div>
                    <div className="flex flex-1 flex-col p-4">
                      <p className="flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-wider text-muted-foreground"><LogoAvatar logo={p.supplier_logo} name={p.supplier_name} className="h-5 w-5 shrink-0 text-[10px]" />{p.supplier_name}</p>
                      <h3 className="mt-1 line-clamp-2 text-sm font-semibold leading-snug">{p.name}</h3>
                      <div className="mt-3 flex flex-wrap items-end justify-between gap-2">
                        <div className="min-w-0">
                          {p.is_promo && p.active_promotion ? (
                            <>
                              <p className="flex flex-wrap items-baseline gap-x-2">
                                <span className="text-sm text-muted-foreground line-through" data-testid={`promo-old-price-${p.id}`}>₾{Number(p.base_price).toFixed(2)}</span>
                                <span className="text-xl font-extrabold text-rose-600" data-testid={`promo-new-price-${p.id}`}>₾{Number(p.price_per_unit).toFixed(2)}</span>
                              </p>
                              <PromoCountdown endsAt={p.active_promotion.ends_at} />
                            </>
                          ) : <p className="text-xl font-extrabold">₾{Number(p.price_per_unit).toFixed(2)}</p>}
                          <p className="font-mono text-[11px] text-muted-foreground">{t("catalog.moq")} {p.moq}</p>
                        </div>
                        <span className="relative z-10 flex shrink-0 items-center gap-1 whitespace-nowrap rounded-md bg-primary/10 px-2 py-1 font-mono text-[10px] font-semibold text-primary"><Layers className="h-3 w-3" />{p.tier_pricing?.length || 1} {t("catalog.tiers")}</span>
                      </div>
                      <div className="mt-auto flex flex-col gap-2 pt-4">
                        <Button className="w-full" disabled={!canOrder || p.stock <= 0} onClick={() => setSelected(p)} data-testid={`order-product-${p.id}`}>
                          {canOrder ? t("catalog.addToCart") : isPending ? t("catalog.connectionPending") : t("catalog.requestConnection")}
                        </Button>
                        {!canOrder && <p className="text-center text-[11px] text-muted-foreground">{t("catalog.connectionRequired")}</p>}
                        {canOrder && (
                          <Button className="h-auto w-full whitespace-normal py-2 text-center text-xs" variant="outline" onClick={() => setNegotiatingProduct(p)} data-testid={`negotiate-price-${p.id}`}>
                            სპეციალური ფასის მოთხოვნა / შევაჭრება
                          </Button>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
      </section>}

      <OrderDialog product={selected} onClose={() => setSelected(null)} onAdd={(prod, qty) => { addItem(prod, qty); toast.success(`${qty} × ${prod.name} — ${t("catalog.addedToCart")}`); setSelected(null); }} />
      <PriceNegotiationDialog product={negotiatingProduct} onClose={() => setNegotiatingProduct(null)} />
    </div>
  );
}

function PriceNegotiationDialog({ product, onClose }) {
  const [quantity, setQuantity] = useState(1);
  const [proposedPrice, setProposedPrice] = useState("");
  const [comment, setComment] = useState("");
  const [sending, setSending] = useState(false);

  useEffect(() => {
    if (!product) return;
    setQuantity(product.moq || 1);
    setProposedPrice(String(product.price_per_unit ?? ""));
    setComment("");
  }, [product]);

  const submit = async () => {
    if (!product || !Number.isInteger(Number(quantity)) || Number(quantity) < 1
      || proposedPrice === "" || !Number.isFinite(Number(proposedPrice)) || Number(proposedPrice) < 0) {
      toast.error("მიუთითეთ სწორი რაოდენობა და შეთავაზებული ფასი");
      return;
    }
    setSending(true);
    try {
      await api.post("/price-negotiations", {
        product_id: product.id,
        quantity: Number(quantity),
        proposed_price: Number(proposedPrice),
        comment,
      });
      toast.success("სპეციალური ფასის მოთხოვნა გაიგზავნა");
      onClose();
    } catch (error) {
      toast.error(error?.response?.data?.detail || "მოთხოვნის გაგზავნა ვერ მოხერხდა");
    } finally {
      setSending(false);
    }
  };

  return (
    <Dialog open={!!product} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="bg-card sm:max-w-md">
        <DialogHeader>
          <DialogTitle>სპეციალური ფასის მოთხოვნა / შევაჭრება</DialogTitle>
          <DialogDescription>{product?.name} · მიმდინარე ფასი ₾{Number(product?.price_per_unit || 0).toFixed(2)}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <p className="mb-1 text-sm font-medium">სასურველი რაოდენობა</p>
            <Input type="number" min="1" step="1" value={quantity} onChange={(e) => setQuantity(e.target.value)} data-testid="negotiation-quantity" />
          </div>
          <div>
            <p className="mb-1 text-sm font-medium">თქვენი შეთავაზებული ერთეულის ფასი (₾)</p>
            <Input type="number" min="0" step="0.01" value={proposedPrice} onChange={(e) => setProposedPrice(e.target.value)} data-testid="negotiation-proposed-price" />
          </div>
          <div>
            <p className="mb-1 text-sm font-medium">კომენტარი (არასავალდებულო)</p>
            <Textarea value={comment} onChange={(e) => setComment(e.target.value)} maxLength={2000} data-testid="negotiation-comment" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>გაუქმება</Button>
          <Button disabled={sending} onClick={submit} data-testid="send-price-negotiation">{sending ? "იგზავნება..." : "მოთხოვნის გაგზავნა"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function OrderDialog({ product, onClose, onAdd }) {
  const { t } = useI18n();
  const [qty, setQty] = useState(10);
  useEffect(() => { if (product) setQty(product.moq); }, [product]);
  if (!product) return null;
  const unit = tierPrice(product, qty);
  const belowMoq = qty < product.moq;
  const tiers = [...(product.tier_pricing || [])].sort((a, b) => a.min_qty - b.min_qty);

  return (
    <Dialog open={!!product} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="bg-card sm:max-w-lg">
        <DialogHeader><DialogTitle className="pr-6 text-left">{product.name}</DialogTitle><DialogDescription className="text-left">{t("catalog.supplierLabel")}: {product.supplier_name}</DialogDescription></DialogHeader>
        <div className="space-y-4">
          <div className="flex gap-4">
            <ProductImage image={product.image} name={product.name} category={product.category} alt={product.name} className="h-24 w-24 rounded-lg border border-border object-cover" />
            <div className="text-sm text-muted-foreground">
              <p>{product.description}</p>
              <p className="mt-2 font-mono text-xs">{t("catalog.inStock")}: {product.stock} {t("common.units")}</p>
            </div>
          </div>

          <div className="rounded-lg border border-border p-3">
            <p className="mb-2 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">{t("catalog.volumeTierPricing")}</p>
            <div className="grid grid-cols-3 gap-2">
              {tiers.map((tier) => (
                <div key={tier.min_qty} className={cn("rounded-md border p-2 text-center", qty >= tier.min_qty ? "border-primary bg-primary/10" : "border-border")}>
                  <p className="font-mono text-[11px] text-muted-foreground">{tier.min_qty}+ {t("common.units")}</p>
                  <p className="text-sm font-bold">₾{tier.price.toFixed(2)}</p>
                </div>
              ))}
            </div>
          </div>

          <div>
            <p className="mb-2 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">{t("catalog.quantity")}</p>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="icon" onClick={() => setQty((q) => Math.max(1, q - 10))} data-testid="qty-minus"><Minus className="h-4 w-4" /></Button>
              <Input type="number" value={qty} onChange={(e) => setQty(Math.max(1, parseInt(e.target.value) || 1))} className="text-center font-bold" data-testid="qty-input" />
              <Button variant="outline" size="icon" onClick={() => setQty((q) => q + 10)} data-testid="qty-plus"><Plus className="h-4 w-4" /></Button>
              {[50, 100].map((n) => <Button key={n} variant="secondary" onClick={() => setQty((q) => q + n)} data-testid={`qty-add-${n}`}>+{n}</Button>)}
            </div>
            {belowMoq && <p className="mt-2 text-xs font-medium text-rose-500">{t("catalog.minOrderQty")} {product.moq} {t("common.units")}.</p>}
          </div>
        </div>
        <DialogFooter className="flex-row items-center justify-between gap-3 sm:justify-between">
          <div><p className="font-mono text-[11px] text-muted-foreground">{t("checkout.orderTotal")}</p><p className="text-2xl font-extrabold" data-testid="order-total">₾{(unit * qty).toFixed(2)}</p></div>
          <Button size="lg" disabled={belowMoq} onClick={() => onAdd(product, qty)} data-testid="confirm-add-cart">{t("catalog.addToCart")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
