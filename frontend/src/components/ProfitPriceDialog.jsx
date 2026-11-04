import { useEffect, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { useI18n } from "@/context/I18nContext";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Loader2, Sparkles } from "lucide-react";

const money = (value) => `₾${Number(value || 0).toFixed(2)}`;

export function ProfitPriceDialog({ item, orderId, isOpen, onClose }) {
  const { t } = useI18n();
  const [price, setPrice] = useState("");
  const [advice, setAdvice] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setPrice("");
    setAdvice(null);
    setError("");
  }, [isOpen, item?.product_id, orderId]);

  useEffect(() => {
    if (!isOpen || !item || !orderId) return undefined;
    let active = true;
    const timer = setTimeout(async () => {
      setLoading(true);
      setError("");
      try {
        const { data } = await api.post("/store/pricing/advisor", {
          order_id: orderId,
          product_id: item.product_id,
          planned_retail_price: price === "" ? null : Number(price),
        });
        if (active) {
          setAdvice(data);
          if (price === "") setPrice(Number(data.recommended_retail_price || 0).toFixed(2));
        }
      } catch (requestError) {
        if (active) setError(formatApiError(requestError.response?.data?.detail));
      } finally {
        if (active) setLoading(false);
      }
    }, 200);
    return () => { active = false; clearTimeout(timer); };
  }, [isOpen, item?.product_id, orderId, price]);

  const unitCost = Number(advice?.unit_cost || 0);
  const profit = Number(advice?.net_profit_per_unit || 0);
  const margin = Number(advice?.profit_margin_percent || 0);
  const markup = Number(advice?.markup_percent || 0);

  return (
    <Dialog open={isOpen} onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="max-h-[90vh] w-[calc(100%-2rem)] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("pricing.calculatorTitle")}</DialogTitle>
          <DialogDescription>{item?.name} · {t("pricing.beforeExpenses")}</DialogDescription>
        </DialogHeader>
        {error && <p role="alert" className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-500">{error}</p>}
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <ValueCard label={t("pricing.purchaseCost")} value={advice ? money(unitCost) : "—"} />
            <label className="space-y-1 text-xs text-muted-foreground">
              <span>{t("pricing.recommendedPrice")}</span>
              <Input type="number" min="0" step="0.01" value={price} onChange={(event) => setPrice(event.target.value)} />
            </label>
          </div>
          {loading ? <div className="flex justify-center py-5"><Loader2 className="h-5 w-5 animate-spin text-primary" /></div> : advice && (
            <>
              <div className="grid grid-cols-2 gap-3">
                <ValueCard label={t("pricing.profitPerUnit")} value={money(profit)} tone={profit >= 0 ? "text-emerald-500" : "text-rose-500"} />
                <ValueCard label={t("pricing.marginPercent")} value={`${margin.toFixed(2)}%`} tone="text-primary" />
                <ValueCard label={t("pricing.markupPercent")} value={`${markup.toFixed(2)}%`} />
              </div>
              <div className="rounded-lg border border-border bg-secondary/30 p-3 text-sm">
                <p className="flex items-center gap-2 font-semibold"><Sparkles className="h-4 w-4 text-primary" />{t("pricing.advisorTitle")}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {advice.recommendation_basis === "market_benchmark"
                    ? t("pricing.smartRule")
                    : t("pricing.targetMarginBasis")}
                </p>
                {advice.internal_market_median_retail_price !== null && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t("pricing.internalMedian")}: {money(advice.internal_market_median_retail_price)} · {advice.internal_market_sample_retailers} {t("pricing.retailerCount")}
                  </p>
                )}
                {advice.external_market_median_retail_price !== null && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t("pricing.externalMedian")}: {money(advice.external_market_median_retail_price)} · {advice.external_market_sample_sources} {t("pricing.sourceCount")}
                  </p>
                )}
                {advice.market_reference_price !== null && (
                  <p className="mt-1 text-xs text-muted-foreground">{t("pricing.marketReference")}: {money(advice.market_reference_price)}</p>
                )}
                <p className="mt-1 text-xs text-muted-foreground">{t("pricing.marginFloor")}: {money(advice.target_margin_floor)}</p>
              </div>
            </>
          )}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>{t("common.close")}</Button>
          <Button type="button" onClick={onClose}>{t("common.save")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default ProfitPriceDialog;

function ValueCard({ label, value, tone = "" }) {
  return <div className="rounded-lg border border-border bg-background/50 p-3"><p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p><p className={`mt-1 text-lg font-bold ${tone}`}>{value}</p></div>;
}
