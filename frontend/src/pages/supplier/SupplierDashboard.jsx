import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useI18n } from "@/context/I18nContext";
import { AlertTriangle, Loader2 } from "lucide-react";
import { AreaChart, Area, XAxis, YAxis, ResponsiveContainer, Tooltip, BarChart, Bar } from "recharts";
import { cn } from "@/lib/utils";
import { MainDashboardLayout } from "@/components/MainDashboardLayout";
import { toast } from "sonner";
import { Link } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { ApiIntegrations } from "@/components/ApiIntegrations";
import SmartInventoryWidget from "@/components/SmartInventoryWidget";
import LiveDriverMap from "@/components/LiveDriverMap";

function ExternalSaleDialog({ open, onOpenChange, ownerId, onSaved, canManageSync }) {
  const { t } = useI18n();
  const [products, setProducts] = useState([]);
  const [client, setClient] = useState("");
  const [productId, setProductId] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState("manual");

  useEffect(() => {
    if (!open || !ownerId) return;
    api.get(`/products?supplier_id=${ownerId}`).then(({ data }) => setProducts(data)).catch(() => toast.error(t("sup.loadError")));
  }, [open, ownerId, t]);

  const reset = () => { setClient(""); setProductId(""); setQuantity("1"); };
  const qty = parseInt(quantity, 10);
  const valid = client.trim() && productId && Number.isInteger(qty) && qty >= 1;

  const submit = async (event) => {
    event.preventDefault();
    if (!valid || busy) return;
    setBusy(true);
    try {
      await api.post("/orders/external", {
        external_ref: `manual-${crypto.randomUUID()}`,
        source_system: "manual",
        customer_name: client.trim(),
        items: [{ product_id: productId, quantity: qty }],
      });
      toast.success(t("sup.externalSaleSaved"));
      reset();
      onOpenChange(false);
      onSaved();
    } catch (error) {
      toast.error(error?.response?.status === 409 ? t("sup.insufficientStock") : t("sup.externalSaleFailed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(value) => { if (!busy) onOpenChange(value); }}>
      <DialogContent className="max-h-[90vh] overflow-y-auto bg-card sm:max-w-lg" data-testid="external-sale-dialog">
        <DialogHeader>
          <DialogTitle>{t("sup.externalSaleTitle")}</DialogTitle>
          <DialogDescription>{t("sup.externalSaleDesc")}</DialogDescription>
        </DialogHeader>
        <div className="mt-2">
          {canManageSync && (
            <div role="tablist" className="grid w-full grid-cols-2 gap-1 rounded-lg bg-muted p-1">
              {[["manual", "tab-manual", "sup.tabManual"], ["auto", "tab-auto-sync", "sup.tabAuto"]].map(([value, testid, label]) => (
                <button
                  key={value} type="button" role="tab" aria-selected={tab === value} data-testid={testid}
                  onClick={() => setTab(value)}
                  className={cn("rounded-md px-3 py-1.5 text-sm font-medium transition-colors", tab === value ? "bg-background text-foreground shadow" : "text-muted-foreground hover:text-foreground")}
                >
                  {t(label)}
                </button>
              ))}
            </div>
          )}
          {(tab === "manual" || !canManageSync) && (
            <form onSubmit={submit} className="mt-4 space-y-4">
              <div>
                <Label htmlFor="ext-client">{t("sup.clientName")}</Label>
                <Input id="ext-client" value={client} maxLength={160} onChange={(e) => setClient(e.target.value)} className="mt-1" required />
              </div>
              <div>
                <Label htmlFor="ext-product">{t("sup.product")}</Label>
                <select id="ext-product" value={productId} onChange={(e) => setProductId(e.target.value)} required className="mt-1 h-10 w-full rounded-md border border-input bg-background px-2 text-sm">
                  <option value="">{t("sup.selectProduct")}</option>
                  {products.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.stock ?? 0} {t("sup.available")})</option>)}
                </select>
              </div>
              <div>
                <Label htmlFor="ext-qty">{t("sup.quantity")}</Label>
                <Input id="ext-qty" type="number" min={1} step={1} value={quantity} onChange={(e) => setQuantity(e.target.value)} className="mt-1" required />
              </div>
              <DialogFooter>
                <Button type="button" variant="outline" disabled={busy} onClick={() => onOpenChange(false)}>{t("common.cancel")}</Button>
                <Button type="submit" disabled={!valid || busy}>{busy ? t("common.saving") : t("sup.submitSale")}</Button>
              </DialogFooter>
            </form>
          )}
          {canManageSync && tab === "auto" && (
            <div className="mt-4"><ApiIntegrations compact /></div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

export default function SupplierDashboard() {
  const { t } = useI18n();
  const { user } = useAuth();
  const ibanMissing = !!user && !(user.iban || "").trim() && (user.supplier_access_role || "global_admin") === "global_admin";
  const [a, setA] = useState(null);
  const [loadError, setLoadError] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [retry, setRetry] = useState(0);
  const [saleOpen, setSaleOpen] = useState(false);
  const [granularity, setGranularity] = useState("daily");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  useEffect(() => {
    let active = true;
    setRefreshing(true);
    const params = { granularity };
    if (dateFrom) params.start_date = dateFrom;
    if (dateTo) params.end_date = dateTo;
    api.get("/analytics/supplier", { params }).then(({ data }) => {
      if (active) {
        setA(data);
        setLoadError(false);
      }
    }).catch((error) => {
      if (!active) return;
      console.error("Could not load supplier dashboard analytics:", error);
      setLoadError(true);
      toast.error(t("sup.loadError"));
    }).finally(() => { if (active) setRefreshing(false); });
    return () => { active = false; };
  }, [retry, t, granularity, dateFrom, dateTo]);

  if (!a && !loadError) return <div className="h-64 animate-pulse rounded-lg bg-secondary" />;
  if (!a) {
    return (
      <div className="rounded-lg border border-border bg-card p-6 text-center">
        <p className="text-sm text-muted-foreground">{t("sup.loadError")}</p>
        <button type="button" onClick={() => setRetry((value) => value + 1)} className="mt-4 rounded-md border border-border px-4 py-2 text-sm font-medium transition-colors hover:border-highlight">
          {t("common.retry")}
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {ibanMissing && (
        <div role="alert" data-testid="iban-missing-banner" className="flex flex-wrap items-center gap-3 rounded-lg border border-processing/40 bg-processing/10 p-4 text-sm">
          <AlertTriangle className="h-5 w-5 shrink-0 text-processing" />
          <div className="min-w-0 flex-1">
            <p className="font-semibold text-processing">{t("sup.ibanMissingTitle")}</p>
            <p className="text-muted-foreground">{t("sup.ibanMissingBody")}</p>
          </div>
          <Link to="/profile" className="rounded-md border border-border px-3 py-1.5 font-medium hover:border-highlight">{t("sup.ibanMissingAction")}</Link>
        </div>
      )}
      {refreshing && a && <p className="flex items-center gap-2 text-xs text-muted-foreground" role="status"><Loader2 className="h-3.5 w-3.5 animate-spin" />{t("sup.refreshingAnalytics")}</p>}
      <MainDashboardLayout analytics={a} />
      <LiveDriverMap />
      <div className="flex justify-end">
        <Button type="button" onClick={() => setSaleOpen(true)} data-testid="add-external-sale-btn" className="font-semibold">
          {t("sup.addExternalSale")}
        </Button>
      </div>
      <section className="grid gap-4 md:grid-cols-3" data-testid="sales-source-breakdown">
        <div className="rounded-lg border border-border bg-card p-5" data-testid="total-inventory-card">
          <p className="text-sm text-muted-foreground">{t("sup.totalInventory")}</p>
          <p className="mt-2 text-3xl font-bold">{a.total_inventory ?? 0}</p>
          <p className="mt-1 text-xs text-muted-foreground">{t("sup.unitsAcross").replace("{n}", a.product_count ?? 0)}</p>
        </div>
        <div className="rounded-lg border border-primary/40 bg-primary/5 p-5" data-testid="app-sales-card">
          <p className="text-sm text-muted-foreground">{t("sup.appSales")}</p>
          <p className="mt-2 text-3xl font-bold">₾{(a.app_sales?.revenue ?? 0).toFixed(2)}</p>
          <p className="mt-1 text-xs text-muted-foreground">{t("sup.ordersCount").replace("{n}", a.app_sales?.orders ?? 0)} · {t("sup.commission")} ₾{(a.app_sales?.commission ?? 0).toFixed(2)}</p>
        </div>
        <div className="rounded-lg border border-border bg-card p-5" data-testid="external-sales-card">
          <p className="text-sm text-muted-foreground">{t("sup.externalSales")}</p>
          <p className="mt-2 text-3xl font-bold">₾{(a.external_sales?.revenue ?? 0).toFixed(2)}</p>
          <p className="mt-1 text-xs text-muted-foreground">{t("sup.ordersCount").replace("{n}", a.external_sales?.orders ?? 0)} · {t("sup.combined")} ₾{(a.revenue ?? 0).toFixed(2)}</p>
        </div>
      </section>
      <ExternalSaleDialog open={saleOpen} onOpenChange={setSaleOpen} ownerId={user?.supplier_id || user?.id} canManageSync={(user?.supplier_access_role || "global_admin") === "global_admin"} onSaved={() => setRetry((value) => value + 1)} />
      <div id="analytics" className="grid scroll-mt-6 gap-6 lg:grid-cols-12">
        <section className="rounded-lg border border-border bg-card p-5 transition-colors duration-200 hover:border-highlight/50 lg:col-span-7">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <h2 className="text-lg font-semibold">{t("sup.salesDynamics")}</h2>
            <div className="flex flex-wrap items-end gap-2">
              <label className="space-y-1 text-[11px] text-muted-foreground">
                <span>{t("finance.from")}</span>
                <Input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
              </label>
              <label className="space-y-1 text-[11px] text-muted-foreground">
                <span>{t("finance.to")}</span>
                <Input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
              </label>
              <select
                aria-label={t("sup.salesDynamics")}
                className="h-9 rounded-md border border-input bg-background px-2 text-sm text-foreground"
                value={granularity}
                onChange={(event) => setGranularity(event.target.value)}
              >
                <option value="daily">{t("sup.daily")}</option>
                <option value="monthly">{t("sup.monthly")}</option>
              </select>
            </div>
          </div>
          <div className="mt-4 w-full min-w-0" style={{ height: 250, minHeight: 250 }}>
            <ResponsiveContainer width="100%" height={250} minWidth={1}>
              <AreaChart data={a.series}>
                <defs><linearGradient id="supplier-sales-gradient" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="hsl(var(--primary))" stopOpacity={0.4} /><stop offset="95%" stopColor="hsl(var(--primary))" stopOpacity={0} /></linearGradient></defs>
                <XAxis dataKey="day" stroke="hsl(var(--muted-foreground))" fontSize={11} />
                <YAxis stroke="hsl(var(--muted-foreground))" fontSize={11} />
                <Tooltip contentStyle={{ background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", borderRadius: 8, color: "hsl(var(--foreground))" }} />
                <Area type="monotone" stackId="s" dataKey="app_sales" name={t("sup.appSalesShort")} stroke="hsl(var(--primary))" strokeWidth={2} fill="url(#supplier-sales-gradient)" />
                <Area type="monotone" stackId="s" dataKey="external_sales" name={t("sup.externalSalesShort")} stroke="hsl(var(--muted-foreground))" strokeWidth={2} strokeDasharray="4 3" fill="hsl(var(--muted-foreground))" fillOpacity={0.15} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </section>

        <section className="rounded-lg border border-border bg-card p-5 transition-colors duration-200 hover:border-highlight/50 lg:col-span-5">
          <h2 className="text-lg font-semibold">{t("sup.popularItems")}</h2>
          <div className="mt-4 w-full min-w-0" style={{ height: 192, minHeight: 192 }}>
            {a.popular.length === 0 ? <p className="py-10 text-center text-sm text-muted-foreground">{t("sup.noSalesYet")}</p> : (
              <ResponsiveContainer width="100%" height={192} minWidth={1}>
                <BarChart data={a.popular} layout="vertical" margin={{ left: 0 }}>
                  <XAxis type="number" hide /><YAxis type="category" dataKey="name" width={0} hide />
                  <Tooltip contentStyle={{ background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", borderRadius: 8 }} />
                  <Bar dataKey="qty" fill="hsl(var(--primary))" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
          <div className="space-y-1.5">
            {a.popular.slice(0, 3).map((product, index) => (
              <div key={product.name} className="flex items-center justify-between text-sm">
                <span className="truncate"><span className="font-mono text-muted-foreground">#{index + 1}</span> {product.name}</span>
                <span className="font-semibold">{product.qty}</span>
              </div>
            ))}
          </div>
        </section>
      </div>

      <SmartInventoryWidget mode="supplier" supplierProducts={a.low_stock} />
    </div>
  );
}
