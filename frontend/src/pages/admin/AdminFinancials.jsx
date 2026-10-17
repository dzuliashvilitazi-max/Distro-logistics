import { useEffect, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { useI18n } from "@/context/I18nContext";
import { StatusBadge } from "@/components/StatusBadge";
import { Wallet, RefreshCw, Download, BadgeCheck, BellRing, Snowflake, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

const money = (v) => `\u20be${Number(v || 0).toFixed(2)}`;

function Stat({ label, value, tone }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <p className="text-xs uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className={cn("mt-1 text-2xl font-bold tracking-tight", tone)}>{value}</p>
    </div>
  );
}

export default function AdminFinancials() {
  const { t } = useI18n();
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState("");

  const load = () => api.get("/admin/financials").then((r) => setData(r.data)).catch(() => {});
  useEffect(() => { load(); }, []);

  const generate = async () => {
    setBusy("generate");
    try {
      const { data: res } = await api.post("/admin/invoices/generate");
      toast.success(res.count ? `${res.count} ${t("bill.generated")}` : t("bill.generateNone"));
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(""); }
  };

  const markPaid = async (inv) => {
    if (!window.confirm(t("bill.confirmPaid"))) return;
    setBusy(inv.id);
    try { await api.put(`/admin/invoices/${inv.id}/paid`); toast.success(t("bill.markedPaid")); load(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(""); }
  };

  const remind = async (inv) => {
    setBusy(inv.id + "-r");
    try { await api.post(`/admin/invoices/${inv.id}/remind`); toast.success(t("bill.reminderSent")); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(""); }
  };

  const downloadPdf = async (inv) => {
    try {
      const res = await api.get(`/invoices/${inv.id}/pdf`, { responseType: "blob" });
      const url = URL.createObjectURL(new Blob([res.data], { type: "application/pdf" }));
      window.open(url, "_blank");
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  if (!data) return <div className="h-64 animate-pulse rounded-xl bg-secondary" />;

  return (
    <div className="space-y-6" data-testid="admin-financials-page">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{t("bill.financialsTitle")}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{t("bill.finSubtitle")} · {data.period_label}</p>
        </div>
        <Button onClick={generate} disabled={busy === "generate"} data-testid="generate-invoices-btn">
          {busy === "generate" ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-1.5 h-4 w-4" />}
          {t("bill.generate")}
        </Button>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label={t("bill.totalOutstanding")} value={money(data.totals.outstanding)} tone="text-rose-500" />
        <Stat label={t("bill.totalAccrued")} value={money(data.totals.accrued)} tone="text-amber-500" />
        <Stat label={t("bill.totalCollected")} value={money(data.totals.collected)} tone="text-emerald-500" />
      </div>

      {data.suppliers.length === 0 && (
        <div className="rounded-xl border border-dashed border-border py-12 text-center text-muted-foreground">{t("bill.noSuppliers")}</div>
      )}

      <div className="space-y-4">
        {data.suppliers.map((s) => (
          <div key={s.supplier_id} className="rounded-xl border border-border bg-card p-5" data-testid={`financials-supplier-${s.supplier_id}`}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <Wallet className="h-5 w-5 text-primary" />
                <div>
                  <p className="font-semibold">{s.supplier_name}</p>
                  <p className="font-mono text-xs text-muted-foreground">{t("orders.taxId")}: {s.tax_id || "—"} · {s.email}</p>
                </div>
              </div>
              {s.frozen
                ? <Badge className="gap-1 bg-rose-500/10 text-rose-500 border border-rose-500/30" data-testid={`frozen-badge-${s.supplier_id}`}><Snowflake className="h-3 w-3" /> {t("bill.frozen")}</Badge>
                : <Badge className="bg-emerald-500/10 text-emerald-500 border border-emerald-500/30">{t("bill.active")}</Badge>}
            </div>

            <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div><p className="text-xs text-muted-foreground">{t("bill.monthSales")}</p><p className="font-semibold">{money(s.month_sales)}</p></div>
              <div><p className="text-xs text-muted-foreground">{t("bill.accrued")}</p><p className="font-semibold text-amber-500">{money(s.accrued_commission)}</p></div>
              <div><p className="text-xs text-muted-foreground">{t("bill.outstanding")}</p><p className="font-semibold text-rose-500">{money(s.outstanding)}</p></div>
              <div><p className="text-xs text-muted-foreground">{t("bill.collected")}</p><p className="font-semibold text-emerald-500">{money(s.collected)}</p></div>
            </div>

            {s.checkout_collected > 0 && (
              <p className="mt-2 text-xs text-muted-foreground" data-testid={`checkout-collected-${s.supplier_id}`}>
                {t("bill.checkoutCollected")}: <span className="font-semibold text-emerald-500">{money(s.checkout_collected)}</span>
              </p>
            )}

            {s.invoices.length > 0 && (
              <div className="mt-4 overflow-x-auto rounded-lg border border-border">
                <table className="w-full text-sm">
                  <thead className="bg-secondary/50 text-left text-xs uppercase tracking-wider text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2">{t("bill.invoiceNo")}</th>
                      <th className="px-3 py-2">{t("bill.period")}</th>
                      <th className="px-3 py-2">{t("bill.due")}</th>
                      <th className="px-3 py-2 text-right">{t("bill.amount")}</th>
                      <th className="px-3 py-2">{t("common.status")}</th>
                      <th className="px-3 py-2 text-right">{t("common.actions")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {s.invoices.map((inv) => (
                      <tr key={inv.id} className="border-t border-border" data-testid={`fin-invoice-${inv.invoice_no}`}>
                        <td className="px-3 py-2 font-mono font-semibold">{inv.invoice_no}</td>
                        <td className="px-3 py-2">{inv.period_label}</td>
                        <td className="px-3 py-2 text-muted-foreground">{inv.due_label}</td>
                        <td className="px-3 py-2 text-right font-semibold">{money(inv.amount)}</td>
                        <td className="px-3 py-2"><StatusBadge status={inv.effective_status} testid={`fin-status-${inv.invoice_no}`} /></td>
                        <td className="px-3 py-2">
                          <div className="flex justify-end gap-1.5">
                            <Button size="sm" variant="ghost" onClick={() => downloadPdf(inv)} data-testid={`fin-download-${inv.invoice_no}`}><Download className="h-4 w-4" /></Button>
                            {inv.effective_status !== "paid" && (
                              <>
                                <Button size="sm" variant="outline" onClick={() => remind(inv)} disabled={busy === inv.id + "-r"} data-testid={`fin-remind-${inv.invoice_no}`}>
                                  {busy === inv.id + "-r" ? <Loader2 className="h-4 w-4 animate-spin" /> : <BellRing className="mr-1 h-3.5 w-3.5" />}{t("bill.remind")}
                                </Button>
                                <Button size="sm" onClick={() => markPaid(inv)} disabled={busy === inv.id} data-testid={`fin-markpaid-${inv.invoice_no}`}>
                                  {busy === inv.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <BadgeCheck className="mr-1 h-3.5 w-3.5" />}{t("bill.markPaid")}
                                </Button>
                              </>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
