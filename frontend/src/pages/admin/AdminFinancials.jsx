import { useEffect, useRef, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { useI18n } from "@/context/I18nContext";
import { StatusBadge } from "@/components/StatusBadge";
import { Wallet, RefreshCw, Download, BadgeCheck, BellRing, Snowflake, Loader2, ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

const money = (v) => `\u20be${Number(v || 0).toFixed(2)}`;
const auditPageSize = 25;
const auditStatusLabels = { all: "ყველა", success: "წარმატებული", pending: "მოლოდინში", error: "შეცდომა" };
const auditActionLabels = {
  payment_recorded: "გადახდა აღირიცხა",
  invoice_marked_paid: "ინვოისი გადახდილად მოინიშნა",
  bank_payment_pending: "ბანკის გადახდა დაიწყო",
  bank_payment_checkout: "საბანკო გადახდის მცდელობა",
  bank_payment_succeeded: "გადახდა წარმატებით დასრულდა",
  bank_payment_failed: "გადახდა ვერ შესრულდა",
  bank_payment_expired: "გადახდის ვადა ამოიწურა",
  branch_delete_blocked: "ფილიალის წაშლა დაიბლოკა",
  warehouse_delete_blocked: "საწყობის წაშლა დაიბლოკა",
};

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
  const [filter, setFilter] = useState("all");
  const [rules, setRules] = useState(null);
  const [auditStatus, setAuditStatus] = useState("all");
  const [auditPage, setAuditPage] = useState(1);
  const [auditData, setAuditData] = useState(null);
  const [auditLoading, setAuditLoading] = useState(false);

  const loadRules = () => api.get("/settings").then((r) => setRules(r.data)).catch(() => {});
  useEffect(() => { loadRules(); }, []);

  const saveRules = async () => {
    setBusy("rules");
    try {
      await api.put("/admin/settings", {
        fee_type: rules.fee_type, fee_value: rules.fee_value, fee_payer: rules.fee_payer,
        billing_overdue_limit: Number(rules.billing_overdue_limit || 0),
        billing_overdue_days: Number(rules.billing_overdue_days || 0),
        billing_reminder_days: Number(rules.billing_reminder_days ?? 2),
      });
      toast.success(t("bill.rulesSaved"));
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(""); }
  };

  const exportXlsx = async () => {
    setBusy("export");
    try {
      const res = await api.get("/export-financials", {
        params: { status: filter },
        responseType: "blob",
        headers: { Accept: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" },
      });
      const url = URL.createObjectURL(new Blob([res.data], { type: res.headers["content-type"] || "application/octet-stream" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = `financial-report-${filter}.xlsx`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      let detail = "";
      try { detail = JSON.parse(await e.response?.data?.text?.())?.detail || ""; } catch { /* non-JSON error body */ }
      toast.error(formatApiError(detail) || t("bill.exportError"));
    } finally { setBusy(""); }
  };

  const matchesFilter = (inv) => filter === "all"
    || (filter === "unpaid" ? inv.effective_status !== "paid" : inv.effective_status === filter);
  const loading = useRef(false);
  const load = async () => {
    if (loading.current) return;
    loading.current = true;
    try { setData((await api.get("/admin/financials")).data); }
    catch { /* keep last data; next poll retries */ }
    finally { loading.current = false; }
  };
  useEffect(() => {
    load();
    const timer = setInterval(load, 15000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setAuditLoading(true);
    api.get("/admin/financials/audit-log", {
      params: { status: auditStatus, page: auditPage, page_size: auditPageSize },
    }).then((res) => {
      if (!cancelled) setAuditData(res.data);
    }).catch(() => {
      if (!cancelled) toast.error("აუდიტის ისტორიის ჩატვირთვა ვერ მოხერხდა.");
    }).finally(() => {
      if (!cancelled) setAuditLoading(false);
    });
    return () => { cancelled = true; };
  }, [auditStatus, auditPage]);

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
        <div className="flex gap-2">
          <Button variant="outline" onClick={exportXlsx} disabled={busy === "export"} data-testid="export-financials-btn">
            {busy === "export" ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Download className="mr-1.5 h-4 w-4" />}
            {t("bill.exportXlsx")}
          </Button>
          <Button onClick={generate} disabled={busy === "generate"} data-testid="generate-invoices-btn">
            {busy === "generate" ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-1.5 h-4 w-4" />}
            {t("bill.generate")}
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap gap-2" data-testid="financial-filters">
        {["all", "overdue", "unpaid", "paid"].map((key) => (
          <button
            key={key}
            type="button"
            onClick={() => setFilter(key)}
            data-testid={`fin-filter-${key}`}
            className={cn("rounded-full border px-3 py-1 text-xs font-medium",
              filter === key ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card text-muted-foreground")}
          >
            {t(`bill.filter.${key}`)}
          </button>
        ))}
      </div>

      {rules && (
        <div className="rounded-xl border border-border bg-card p-4" data-testid="billing-rules">
          <p className="text-sm font-semibold">{t("bill.rulesTitle")}</p>
          <p className="mt-1 text-xs text-muted-foreground">{t("bill.rulesHint")}</p>
          <div className="mt-3 grid gap-3 sm:grid-cols-4">
            {[["billing_overdue_limit", "bill.ruleLimit"], ["billing_overdue_days", "bill.ruleDays"], ["billing_reminder_days", "bill.ruleReminder"]].map(([key, label]) => (
              <label key={key} className="space-y-1 text-xs font-medium text-muted-foreground">
                <span>{t(label)}</span>
                <input
                  type="number" min="0" value={rules[key] ?? (key === "billing_reminder_days" ? 2 : 0)}
                  onChange={(e) => setRules((r) => ({ ...r, [key]: e.target.value }))}
                  className="h-9 w-full rounded-lg border border-border bg-background px-3 text-sm text-foreground"
                />
              </label>
            ))}
            <div className="flex items-end">
              <Button size="sm" onClick={saveRules} disabled={busy === "rules"}>{t("common.save")}</Button>
            </div>
          </div>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label={t("bill.totalOutstanding")} value={money(data.totals.outstanding)} tone="text-rose-500" />
        <Stat label={t("bill.totalAccrued")} value={money(data.totals.accrued)} tone="text-processing" />
        <Stat label={t("bill.totalCollected")} value={money(data.totals.collected)} tone="text-delivered" />
      </div>

      {data.suppliers.length === 0 && (
        <div className="rounded-xl border border-dashed border-border py-12 text-center text-muted-foreground">{t("bill.noSuppliers")}</div>
      )}

      <div className="space-y-4">
        {data.suppliers.filter((s) => filter === "all" || s.invoices.some(matchesFilter)).map((s) => (
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
                : <Badge className="bg-delivered/10 text-delivered border border-delivered/30">{t("bill.active")}</Badge>}
            </div>

            <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div><p className="text-xs text-muted-foreground">{t("bill.monthSales")}</p><p className="font-semibold">{money(s.month_sales)}</p></div>
              <div><p className="text-xs text-muted-foreground">{t("bill.accrued")}</p><p className="font-semibold text-processing">{money(s.accrued_commission)}</p></div>
              <div><p className="text-xs text-muted-foreground">{t("bill.outstanding")}</p><p className="font-semibold text-rose-500">{money(s.outstanding)}</p></div>
              <div><p className="text-xs text-muted-foreground">{t("bill.collected")}</p><p className="font-semibold text-delivered">{money(s.collected)}</p></div>
            </div>

            {s.checkout_collected > 0 && (
              <p className="mt-2 text-xs text-muted-foreground" data-testid={`checkout-collected-${s.supplier_id}`}>
                {t("bill.checkoutCollected")}: <span className="font-semibold text-delivered">{money(s.checkout_collected)}</span>
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
                    {s.invoices.filter(matchesFilter).map((inv) => (
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

      <section className="space-y-3" data-testid="financial-audit-log">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">ტრანზაქციების ისტორია</h2>
            <p className="text-xs text-muted-foreground">ფინანსური მოქმედებების უცვლელი ჟურნალი</p>
          </div>
          {auditLoading && <Loader2 className="h-4 w-4 animate-spin" aria-label="იტვირთება" />}
        </div>

        <div className="flex flex-wrap gap-2" role="group" aria-label="აუდიტის სტატუსის ფილტრი" data-testid="audit-status-filters">
          {Object.entries(auditStatusLabels).map(([status, label]) => (
            <button
              key={status}
              type="button"
              onClick={() => { setAuditStatus(status); setAuditPage(1); }}
              aria-pressed={auditStatus === status}
              data-testid={`audit-filter-${status}`}
              className={cn("rounded-md border px-3 py-1.5 text-xs font-medium",
                auditStatus === status ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card text-muted-foreground")}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="bg-secondary/50 text-left text-xs uppercase text-muted-foreground">
              <tr>
                <th className="px-3 py-2">თარიღი</th>
                <th className="px-3 py-2">მოქმედება</th>
                <th className="px-3 py-2">მომხმარებელი</th>
                <th className="px-3 py-2">რეფერენსი</th>
                <th className="px-3 py-2 text-right">თანხა</th>
                <th className="px-3 py-2">სტატუსი</th>
              </tr>
            </thead>
            <tbody>
              {(auditData?.events || []).map((event) => (
                <tr key={event.id} className="border-t border-border" data-testid={`audit-event-${event.id}`}>
                  <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                    {event.at ? new Date(event.at).toLocaleString("ka-GE") : "—"}
                  </td>
                  <td className="px-3 py-2">
                    {auditActionLabels[event.action] || (event.action || "").replaceAll("_", " ")}
                  </td>
                  <td className="px-3 py-2">
                    {event.actor_name || (event.entity === "bank_payment" && event.actor_id
                      ? `მაღაზია (${event.actor_id})`
                      : event.actor_id || "სისტემა")}
                  </td>
                  <td className="max-w-48 truncate px-3 py-2 font-mono text-xs" title={`${event.entity || ""}: ${event.entity_id || ""}`}>
                    {event.entity_id || event.id || "—"}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-right font-medium">
                    {event.amount == null ? "—" : money(event.amount)}
                  </td>
                  <td className="px-3 py-2">
                    <Badge className={cn("border", {
                      "border-delivered/30 bg-delivered/10 text-delivered": event.status === "success",
                      "border-processing/30 bg-processing/10 text-processing": event.status === "pending",
                      "border-rose-500/30 bg-rose-500/10 text-rose-500": event.status === "error",
                    })}>
                      {auditStatusLabels[event.status] || event.status}
                    </Badge>
                  </td>
                </tr>
              ))}
              {auditData && auditData.events.length === 0 && (
                <tr><td colSpan={6} className="px-3 py-10 text-center text-muted-foreground">ჩანაწერები არ მოიძებნა.</td></tr>
              )}
            </tbody>
          </table>
        </div>

        {auditData && (
          <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
            <span>{auditData.total} ჩანაწერი · გვერდი {auditPage} / {Math.max(1, Math.ceil(auditData.total / auditPageSize))}</span>
            <div className="flex gap-1">
              <Button
                size="icon" variant="outline" aria-label="წინა გვერდი"
                disabled={auditPage <= 1 || auditLoading}
                onClick={() => setAuditPage((page) => page - 1)}
              ><ChevronLeft className="h-4 w-4" /></Button>
              <Button
                size="icon" variant="outline" aria-label="შემდეგი გვერდი"
                disabled={auditLoading || auditPage >= Math.ceil(auditData.total / auditPageSize)}
                onClick={() => setAuditPage((page) => page + 1)}
              ><ChevronRight className="h-4 w-4" /></Button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
