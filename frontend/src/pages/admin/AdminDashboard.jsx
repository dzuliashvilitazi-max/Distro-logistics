import { useCallback, useEffect, useState } from "react";
import { api, requestErrorMessage } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/context/I18nContext";
import { DollarSign, ShoppingBag, CheckCircle2, Percent, Store, Warehouse, Clock } from "lucide-react";
import { cn } from "@/lib/utils";

function Metric({ icon: Icon, label, value, accent, testid }) {
  return (
    <div data-testid={testid} className="rounded-xl border border-border bg-card p-5">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">{label}</span>
        <div className={cn("flex h-9 w-9 items-center justify-center rounded-lg", accent)}><Icon className="h-4.5 w-4.5" style={{ width: 18, height: 18 }} /></div>
      </div>
      <p className="mt-3 text-2xl font-extrabold lg:text-3xl">{value}</p>
    </div>
  );
}

export default function AdminDashboard() {
  const { t } = useI18n();
  const [a, setA] = useState(null);
  const [settings, setSettings] = useState(null);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    setError("");
    api.get("/analytics/admin").then((r) => setA(r.data)).catch((err) => setError(requestErrorMessage(err)));
    api.get("/settings").then((r) => setSettings(r.data)).catch(() => setSettings(null));
  }, []);
  useEffect(() => { load(); }, [load]);
  if (error && !a) {
    return (
      <div className="rounded-xl border border-border bg-card p-8 text-center" data-testid="admin-dashboard-error">
        <p className="text-sm text-muted-foreground">{error}</p>
        <Button className="mt-4" variant="outline" onClick={load}>{t("common.retry")}</Button>
      </div>
    );
  }
  if (!a) return <div className="h-64 animate-pulse rounded-xl bg-secondary" />;

  const feeValue = Number(settings?.fee_value);
  const feeSuffix = !settings || Number.isNaN(feeValue) ? ""
    : ` (${settings.fee_type === "fixed" ? `₾${feeValue}` : `${feeValue}%`})`;

  return (
    <div>
      <h1 className="mb-6 text-2xl font-bold tracking-tight sm:text-3xl">{t("adm.title")}</h1>
      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Metric icon={DollarSign} label={t("adm.totalGMV")} value={`₾${a.gmv.toLocaleString()}`} accent="bg-delivered/15 text-delivered" testid="admin-gmv" />
        <Metric icon={ShoppingBag} label={t("adm.totalOrders")} value={a.total_orders} accent="bg-primary/15 text-primary" testid="admin-orders" />
        <Metric icon={CheckCircle2} label={t("adm.fulfillmentRate")} value={`${a.fulfillment_rate}%`} accent="bg-delivered/15 text-delivered" testid="admin-fulfillment" />
        <Metric icon={Percent} label={`${t("adm.platformFees")}${feeSuffix}`} value={`₾${a.fee_revenue.toLocaleString()}`} accent="bg-processing/15 text-processing" testid="admin-fees" />
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Metric icon={Store} label={t("adm.retailers")} value={a.retailers} accent="bg-info/15 text-info" testid="admin-retailers" />
        <Metric icon={Warehouse} label={t("adm.suppliers")} value={a.suppliers} accent="bg-info/15 text-info" testid="admin-suppliers" />
        <Metric icon={Clock} label={t("adm.pendingApprovals")} value={a.pending_suppliers} accent="bg-processing/15 text-processing" testid="admin-pending" />
      </div>
    </div>
  );
}
