import { useEffect, useMemo, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { useStoreBranch } from "@/context/StoreBranchContext";
import { useI18n } from "@/context/I18nContext";
import { ProfitPriceDialog } from "@/components/ProfitPriceDialog";
import { Button } from "@/components/ui/button";
import { Calculator, Loader2 } from "lucide-react";

export default function StorePricing() {
  const { t } = useI18n();
  const { activeBranchId } = useStoreBranch();
  const [orders, setOrders] = useState(null);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!activeBranchId) return undefined;
    let active = true;
    api.get("/orders", { params: { branch_id: activeBranchId } })
      .then(({ data }) => { if (active) { setOrders(data); setError(""); } })
      .catch((requestError) => { if (active) { setError(formatApiError(requestError.response?.data?.detail)); setOrders([]); } });
    return () => { active = false; };
  }, [activeBranchId]);

  const purchases = useMemo(() => (orders || [])
    .filter((order) => order.status === "Delivered" && !order.external_order)
    .flatMap((order) => (order.items || []).map((item) => ({ order, item }))), [orders]);

  if (!orders) return <div className="h-72 animate-pulse rounded-xl bg-secondary" />;
  return (
    <div className="space-y-6" data-testid="store-pricing-page">
      <header>
        <div className="flex items-center gap-2"><Calculator className="h-6 w-6 text-primary" /><h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{t("pricing.title")}</h1></div>
        <p className="mt-1 text-sm text-muted-foreground">{t("pricing.subtitle")}</p>
      </header>
      {error && <p role="alert" className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-500">{error}</p>}
      <div className="overflow-x-auto rounded-xl border border-border bg-card">
        <table className="w-full min-w-[650px] text-sm">
          <thead className="bg-secondary/60 text-left text-xs uppercase tracking-wider text-muted-foreground">
            <tr><th className="px-4 py-3">{t("orders.order")}</th><th className="px-4 py-3">{t("common.product")}</th><th className="px-4 py-3">{t("pricing.purchaseCost")}</th><th className="px-4 py-3">{t("pricing.quantity")}</th><th className="px-4 py-3 text-right">{t("common.actions")}</th></tr>
          </thead>
          <tbody>
            {purchases.map(({ order, item }, index) => (
              <tr key={`${order.id}-${item.product_id}-${index}`} className="border-t border-border">
                <td className="px-4 py-3 font-mono">{order.order_no}</td>
                <td className="px-4 py-3 font-medium">{item.name}</td>
                <td className="px-4 py-3">₾{Number(item.unit_price || 0).toFixed(2)}</td>
                <td className="px-4 py-3">{item.quantity}</td>
                <td className="px-4 py-3 text-right"><Button size="sm" variant="outline" onClick={() => setSelected({ orderId: order.id, item })}><Calculator className="mr-1.5 h-4 w-4" />{t("pricing.calculate")}</Button></td>
              </tr>
            ))}
            {purchases.length === 0 && <tr><td colSpan={5} className="px-4 py-12 text-center text-muted-foreground"><Loader2 className="mx-auto mb-2 h-5 w-5" />{t("pricing.noPurchases")}</td></tr>}
          </tbody>
        </table>
      </div>
      <ProfitPriceDialog item={selected?.item} orderId={selected?.orderId} isOpen={!!selected} onClose={() => setSelected(null)} />
    </div>
  );
}
