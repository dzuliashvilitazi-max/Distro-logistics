import { useEffect, useState } from "react";
import { Building2, Loader2, MapPin, Search, Send, Store } from "lucide-react";
import { api, requestErrorMessage } from "@/lib/api";
import { GEORGIAN_CITIES } from "@/lib/cities";
import { normalizeEntityType } from "@/lib/businessEntity";
import { useI18n } from "@/context/I18nContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";

const SECTORS = ["grocery", "zoo", "household", "laundry", "restaurant_cafe_bar", "hotel_hostel", "office_company", "other"];

export default function StoreDiscovery() {
  const { t } = useI18n();
  const [filters, setFilters] = useState({ city: "", sector: "", business_type: "", search: "" });
  const [stores, setStores] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [retryToken, setRetryToken] = useState(0);
  const [busyStoreId, setBusyStoreId] = useState("");

  useEffect(() => {
    let active = true;
    const timer = window.setTimeout(async () => {
      setLoading(true);
      setLoadError(false);
      try {
        const params = Object.fromEntries(Object.entries(filters).filter(([, value]) => value.trim()));
        const { data } = await api.get("/connections/discover-stores", { params });
        if (active) setStores(data);
      } catch (error) {
        if (!active) return;
        console.error("Could not load store discovery results:", error);
        setLoadError(true);
        toast.error(requestErrorMessage(error));
      } finally {
        if (active) setLoading(false);
      }
    }, filters.search ? 250 : 0);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [filters, retryToken]);

  const invite = async (store) => {
    if (busyStoreId) return;
    setBusyStoreId(store.id);
    try {
      await api.post("/connections/invite", { store_id: store.id });
      setStores((current) => current.map((item) => item.id === store.id
        ? { ...item, connection_status: "PENDING", requested_by_role: "supplier" }
        : item));
      toast.success(t("discovery.invitationSent"));
    } catch (error) {
      toast.error(requestErrorMessage(error));
    } finally {
      setBusyStoreId("");
    }
  };

  const storeName = (store) => store.business_name || store.name || store.id;
  const sectorLabel = (store) => store.sector === "other"
    ? store.establishment_type_other || t("est.other")
    : t(`est.${normalizeEntityType(store.establishment_type)}`);

  return (
    <div className="space-y-5" data-testid="store-discovery-page">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.16em] text-highlight">{t("discovery.eyebrow")}</p>
          <h1 className="mt-1 text-2xl font-bold tracking-tight sm:text-3xl">{t("discovery.title")}</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{t("discovery.subtitle")}</p>
        </div>
        <span className="w-fit rounded-md border border-border bg-secondary/60 px-3 py-2 font-mono text-xs text-muted-foreground">
          {loading ? "..." : t("discovery.resultsCount").replace("{count}", String(stores.length))}
        </span>
      </header>

      <section className="grid gap-3 rounded-lg border border-border bg-card p-4 sm:grid-cols-2 xl:grid-cols-4" aria-label={t("discovery.filters")}>
        <label className="relative block">
          <span className="mb-1.5 block text-xs font-medium text-muted-foreground">{t("discovery.search")}</span>
          <Search className="absolute left-3 top-[2.4rem] h-4 w-4 text-muted-foreground" />
          <Input value={filters.search} onChange={(event) => setFilters((value) => ({ ...value, search: event.target.value }))} placeholder={t("discovery.searchPlaceholder")} className="pl-9" />
        </label>
        <label className="block space-y-1.5 text-xs font-medium text-muted-foreground">
          <span>{t("discovery.city")}</span>
          <select value={filters.city} onChange={(event) => setFilters((value) => ({ ...value, city: event.target.value }))} className="w-full rounded-md border border-input bg-background px-3 text-sm text-foreground">
            <option value="">{t("discovery.anyCity")}</option>
            {GEORGIAN_CITIES.map((city) => <option key={city} value={city}>{city}</option>)}
          </select>
        </label>
        <label className="block space-y-1.5 text-xs font-medium text-muted-foreground">
          <span>{t("discovery.sector")}</span>
          <select value={filters.sector} onChange={(event) => setFilters((value) => ({ ...value, sector: event.target.value }))} className="w-full rounded-md border border-input bg-background px-3 text-sm text-foreground">
            <option value="">{t("discovery.anySector")}</option>
            {SECTORS.map((sector) => <option key={sector} value={sector}>{t(`est.${sector}`)}</option>)}
          </select>
        </label>
        <label className="block space-y-1.5 text-xs font-medium text-muted-foreground">
          <span>{t("discovery.businessType")}</span>
          <select value={filters.business_type} onChange={(event) => setFilters((value) => ({ ...value, business_type: event.target.value }))} className="w-full rounded-md border border-input bg-background px-3 text-sm text-foreground">
            <option value="">{t("discovery.anyType")}</option>
            <option value="RETAIL">{t("discovery.retailType")}</option>
            <option value="SERVICE">{t("discovery.serviceType")}</option>
          </select>
        </label>
      </section>

      {loading ? (
        <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />{t("discovery.loading")}</div>
      ) : loadError ? (
        <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-8 text-center">
          <p className="text-sm text-muted-foreground">{t("discovery.loadError")}</p>
          <Button type="button" variant="outline" className="mt-3" onClick={() => setRetryToken((token) => token + 1)}>{t("common.retry")}</Button>
        </div>
      ) : stores.length ? (
        <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" aria-label={t("discovery.results")}>
          {stores.map((store) => {
            const status = store.connection_status;
            const alreadyConnected = status === "APPROVED";
            const pending = status === "PENDING";
            return (
              <article key={store.id} className="flex min-h-40 flex-col justify-between rounded-lg border border-border bg-card p-4 transition-colors hover:border-highlight/40" data-testid={`discovery-store-${store.id}`}>
                <div className="flex items-start gap-3">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-highlight/25 bg-highlight/10 text-highlight">
                    {store.business_type === "SERVICE" ? <Building2 className="h-5 w-5" /> : <Store className="h-5 w-5" />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <h2 className="truncate text-sm font-semibold">{storeName(store)}</h2>
                    <p className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground"><MapPin className="h-3.5 w-3.5 shrink-0" />{store.city || t("discovery.cityUnknown")}</p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      <span className="rounded border border-border px-2 py-0.5 text-[10px] text-muted-foreground">{sectorLabel(store)}</span>
                      <span className="rounded border border-border px-2 py-0.5 text-[10px] text-muted-foreground">{store.business_type === "RETAIL" ? t("discovery.retailType") : t("discovery.serviceType")}</span>
                    </div>
                  </div>
                </div>
                <div className="mt-4">
                  {alreadyConnected ? (
                    <Button type="button" disabled variant="secondary" className="w-full">{t("discovery.connected")}</Button>
                  ) : pending ? (
                    <Button type="button" disabled variant="outline" className="w-full">{t("discovery.pending")}</Button>
                  ) : (
                    <Button type="button" disabled={!!busyStoreId} onClick={() => invite(store)} className="w-full">
                      {busyStoreId === store.id ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Send className="mr-2 h-4 w-4" />}
                      {t("discovery.invite")}
                    </Button>
                  )}
                </div>
              </article>
            );
          })}
        </section>
      ) : (
        <div className="rounded-lg border border-dashed border-border px-4 py-16 text-center text-sm text-muted-foreground">{t("discovery.empty")}</div>
      )}
    </div>
  );
}