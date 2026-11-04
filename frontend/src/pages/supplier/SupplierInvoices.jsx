import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, formatApiError } from "@/lib/api";
import { useI18n } from "@/context/I18nContext";
import { StatusBadge } from "@/components/StatusBadge";
import { CardForm } from "@/components/CardForm";
import { FileText, Download, AlertTriangle, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "sonner";

const money = (v) => `\u20be${Number(v || 0).toFixed(2)}`;

export default function SupplierInvoices() {
  const { t } = useI18n();
  const [invoices, setInvoices] = useState(null);
  const [filter, setFilter] = useState("all");
  const [downloading, setDownloading] = useState("");
  const [searchParams] = useSearchParams();
  const requestedInvoiceId = searchParams.get("invoice");

  const load = () => api.get("/invoices").then((r) => setInvoices(r.data)).catch(() => setInvoices([]));
  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (!requestedInvoiceId || !invoices?.some((invoice) => invoice.id === requestedInvoiceId)) return undefined;
    const timer = setTimeout(() => {
      document.getElementById(`invoice-${requestedInvoiceId}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 0);
    return () => clearTimeout(timer);
  }, [invoices, requestedInvoiceId]);

  const frozen = (invoices || []).some((i) => i.effective_status === "overdue");
  const visibleInvoices = (invoices || []).filter((invoice) => filter === "all" || invoice.effective_status === filter);

  const downloadPdf = async (inv) => {
    setDownloading(inv.id);
    try {
      const res = await api.get(`/invoices/${inv.id}/pdf`, { responseType: "blob" });
      const url = URL.createObjectURL(new Blob([res.data], { type: "application/pdf" }));
      window.open(url, "_blank");
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    } finally {
      setDownloading("");
    }
  };

  if (invoices === null) return (
    <div className="space-y-5" data-testid="supplier-invoices-skeleton" aria-busy="true">
      <Skeleton className="h-12 w-64" />
      <Skeleton className="h-10 w-full" />
      <Skeleton className="h-64 w-full" />
    </div>
  );

  return (
    <div className="space-y-6" data-testid="supplier-invoices-page">
      <div>
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{t("bill.invoicesTitle")}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{t("bill.subtitle")}</p>
      </div>

      {frozen && (
        <div data-testid="frozen-banner" className="flex items-start gap-3 rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-500">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
          <p className="font-medium">{t("bill.frozenBanner")}</p>
        </div>
      )}

      <CardForm note={t("card.autoDebitNote")} />

      <div className="flex flex-wrap gap-2" role="group" aria-label={t("bill.filter.all")} data-testid="supplier-invoice-status-filters">
        {["all", "pending", "overdue", "paid"].map((value) => (
          <Button
            key={value} type="button" size="sm" variant={filter === value ? "default" : "outline"}
            aria-pressed={filter === value} onClick={() => setFilter(value)}
            data-testid={`supplier-invoice-filter-${value}`}
          >
            {t(`bill.filter.${value}`)}
          </Button>
        ))}
      </div>

      {visibleInvoices.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border py-16 text-center text-muted-foreground" data-testid="no-invoices">
          <FileText className="mx-auto mb-3 h-10 w-10 opacity-40" />
          {invoices.length === 0 ? t("bill.noInvoices") : t("bill.noInvoicesFiltered")}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-sm">
            <thead className="bg-secondary/60 text-left text-xs uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="px-4 py-3">{t("bill.invoiceNo")}</th>
                <th className="px-4 py-3">{t("bill.paymentReference")}</th>
                <th className="px-4 py-3">{t("bill.period")}</th>
                <th className="px-4 py-3">{t("bill.issued")}</th>
                <th className="px-4 py-3">{t("bill.due")}</th>
                <th className="px-4 py-3 text-right">{t("bill.amount")}</th>
                <th className="px-4 py-3">{t("common.status")}</th>
                <th className="px-4 py-3 text-right">{t("common.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {visibleInvoices.map((inv) => (
                <tr key={inv.id} id={`invoice-${inv.id}`} className="border-t border-border" data-testid={`invoice-row-${inv.invoice_no}`}>
                  <td className="px-4 py-3 font-mono font-semibold">{inv.invoice_no}</td>
                  <td className="px-4 py-3 font-mono text-xs">{inv.payment_reference || "—"}</td>
                  <td className="px-4 py-3">{inv.period_label}</td>
                  <td className="px-4 py-3 text-muted-foreground">{inv.issue_label}</td>
                  <td className="px-4 py-3 text-muted-foreground">{inv.due_label}</td>
                  <td className="px-4 py-3 text-right font-semibold">{money(inv.amount)}</td>
                  <td className="px-4 py-3"><StatusBadge status={inv.effective_status} testid={`invoice-status-${inv.invoice_no}`} /></td>
                  <td className="px-4 py-3 text-right">
                    <Button size="sm" variant="outline" onClick={() => downloadPdf(inv)} data-testid={`download-invoice-${inv.invoice_no}`}>
                      {downloading === inv.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="mr-1.5 h-4 w-4" />}
                      {t("bill.download")}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
