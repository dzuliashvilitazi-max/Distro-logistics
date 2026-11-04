import { useEffect, useMemo, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { useI18n } from "@/context/I18nContext";
import { useStoreBranch } from "@/context/StoreBranchContext";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { CalendarDays, Download, FileText, Loader2, Wallet } from "lucide-react";
import { toast } from "sonner";
import FinanceExport from "@/components/FinanceExport";
import { Skeleton } from "@/components/ui/skeleton";

const money = (value) => `₾${Number(value || 0).toFixed(2)}`;
const paymentStatusStyle = {
  paid: "border-emerald-500/30 bg-emerald-500/10 text-emerald-500",
  unpaid: "border-amber-500/30 bg-amber-500/10 text-amber-500",
  partially_paid: "border-sky-500/30 bg-sky-500/10 text-sky-500",
  overdue: "border-rose-500/30 bg-rose-500/10 text-rose-500",
};

export default function StoreFinance() {
  const { t, lang } = useI18n();
  const { activeBranchId } = useStoreBranch();
  const [data, setData] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [supplierId, setSupplierId] = useState("all");
  const [status, setStatus] = useState("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [statementSupplier, setStatementSupplier] = useState(null);
  const [statement, setStatement] = useState(null);
  const [downloading, setDownloading] = useState("");

  useEffect(() => {
    let active = true;
    setRefreshing(true);
    const params = { payment_status: status };
    if (activeBranchId) params.branch_id = activeBranchId;
    if (supplierId !== "all") params.supplier_id = supplierId;
    if (dateFrom) params.start_date = dateFrom;
    if (dateTo) params.end_date = dateTo;
    api.get("/store/finance", { params })
      .then(({ data: result }) => {
        if (active) { setData(result); setError(""); }
      })
      .catch((requestError) => {
        if (!active) return;
        setError(formatApiError(requestError.response?.data?.detail));
        setData({ accounts: [], orders: [] });
      })
      .finally(() => { if (active) setRefreshing(false); });
    return () => { active = false; };
  }, [activeBranchId, supplierId, status, dateFrom, dateTo]);

  useEffect(() => {
    if (!statementSupplier) return undefined;
    let active = true;
    setStatement(null);
    api.get("/store/finance", { params: { supplier_id: statementSupplier.supplier_id, payment_status: "all", ...(activeBranchId ? { branch_id: activeBranchId } : {}) } })
      .then(({ data: result }) => { if (active) setStatement(result.orders || []); })
      .catch((requestError) => {
        if (active) {
          toast.error(formatApiError(requestError.response?.data?.detail));
          setStatement([]);
        }
      });
    return () => { active = false; };
  }, [statementSupplier, activeBranchId]);

  const accountSummary = useMemo(() => (data?.accounts || []).map((account) => ({
    ...account,
    dueWarning: account.next_due_date
      ? Math.ceil((new Date(account.next_due_date).getTime() - Date.now()) / 86400000)
      : null,
  })), [data]);

  const dateLabel = (value) => value
    ? new Date(value).toLocaleDateString(lang === "ka" ? "ka-GE" : lang === "ru" ? "ru-RU" : "en-GB")
    : "—";

  const downloadInvoice = async (order) => {
    setDownloading(order.id);
    try {
      const { data: file } = await api.get(`/orders/${encodeURIComponent(order.id)}/invoice.pdf`, { responseType: "blob" });
      const url = URL.createObjectURL(new Blob([file], { type: "application/pdf" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = `${order.order_no}-invoice.pdf`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch (requestError) {
      toast.error(formatApiError(requestError.response?.data?.detail));
    } finally {
      setDownloading("");
    }
  };

  const transactions = useMemo(() => {
    if (!statement) return [];
    const rows = statement.flatMap((order) => [
      {
        id: `order-${order.id}`,
        date: order.delivered_at || order.created_at,
        type: t("finance.orderCharge"),
        reference: order.order_no,
        amount: Number(order.total || 0),
        kind: "charge",
      },
      ...(order.payment_entries || []).map((entry) => ({
        id: entry.id,
        date: entry.recorded_at,
        type: t(`finance.method.${entry.method}`),
        reference: entry.reference || order.order_no,
        amount: -Number(entry.amount || 0),
        kind: "payment",
      })),
    ]).sort((a, b) => new Date(a.date || 0) - new Date(b.date || 0));
    let balanceCents = 0;
    return rows.map((row) => {
      balanceCents += Math.round(row.amount * 100);
      return { ...row, running_balance: balanceCents / 100 };
    });
  }, [statement, t]);

  if (!data) return (
    <div className="space-y-6" data-testid="store-finance-skeleton" aria-busy="true">
      <Skeleton className="h-12 w-64" />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map((item) => <Skeleton key={item} className="h-36" />)}</div>
      <Skeleton className="h-64 w-full" />
    </div>
  );

  return (
    <div className="space-y-6" data-testid="store-finance-page">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Wallet className="h-6 w-6 text-primary" />
            <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{t("finance.storeTitle")}</h1>
            {refreshing && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-hidden="true" />}
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{t("finance.storeSubtitle")}</p>
        </div>
        <FinanceExport dateFrom={dateFrom} dateTo={dateTo} />
      </header>

      {error && <div role="alert" className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-500">{error}</div>}

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3" aria-label={t("finance.accounts")}>
        {accountSummary.map((account) => (
          <article key={account.supplier_id} className="rounded-xl border border-border bg-card p-5" data-testid={`credit-account-${account.supplier_id}`}>
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{t("finance.distributor")}</p>
                <h2 className="mt-1 font-semibold">{account.supplier_name}</h2>
              </div>
              <Button size="sm" variant="outline" onClick={() => setStatementSupplier(account)}>
                <FileText className="mr-1.5 h-4 w-4" />{t("finance.statement")}
              </Button>
            </div>
            <div className="grid grid-cols-3 gap-2">
              <Metric label={t("finance.outstanding")} value={money(account.outstanding_balance)} tone="text-rose-500" />
              <Metric label={t("finance.creditLimit")} value={money(account.credit_limit)} />
              <Metric label={t("finance.availableCredit")} value={money(account.available_credit)} tone="text-primary" />
            </div>
            {account.dueWarning !== null && account.outstanding_balance > 0 && account.dueWarning <= 3 && (
              <div className={`mt-4 rounded-lg border px-3 py-2 text-xs font-semibold ${account.dueWarning < 0 ? paymentStatusStyle.overdue : paymentStatusStyle.unpaid}`}>
                {account.dueWarning < 0
                  ? t("finance.overdueDays").replace("{count}", String(Math.abs(account.dueWarning)))
                  : t("finance.dueInDays").replace("{count}", String(account.dueWarning))}
              </div>
            )}
            <p className="mt-3 text-xs text-muted-foreground">{t("finance.termsDays").replace("{count}", String(account.payment_due_days))}</p>
          </article>
        ))}
        {accountSummary.length === 0 && (
          <div className="rounded-xl border border-dashed border-border p-8 text-sm text-muted-foreground md:col-span-2 xl:col-span-3">
            {t("finance.noAccounts")}
          </div>
        )}
      </section>

      <section className="overflow-hidden rounded-md border border-border bg-card" data-testid="finance-due-calendar">
        <div className="flex items-center gap-2 border-b border-border p-4">
          <CalendarDays className="h-5 w-5 text-primary" />
          <h2 className="font-semibold">{t("finance.dueCalendar")}</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead className="bg-secondary/60 text-left text-xs uppercase text-muted-foreground">
              <tr>
                <th className="px-4 py-3">{t("finance.dueDate")}</th>
                <th className="px-4 py-3">{t("finance.distributor")}</th>
                <th className="px-4 py-3">{t("finance.orderNumber")}</th>
                <th className="px-4 py-3 text-right">{t("finance.balance")}</th>
                <th className="px-4 py-3">{t("common.status")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {(data.due_calendar || []).map((item) => (
                <tr key={item.order_id}>
                  <td className="whitespace-nowrap px-4 py-3">{dateLabel(item.due_at)}</td>
                  <td className="px-4 py-3">{item.supplier_name}</td>
                  <td className="px-4 py-3 font-mono">{item.order_no}</td>
                  <td className="px-4 py-3 text-right font-semibold">{money(item.amount_due)}</td>
                  <td className="px-4 py-3"><PaymentStatus status={item.payment_status} t={t} /></td>
                </tr>
              ))}
              {data.due_calendar?.length === 0 && (
                <tr><td colSpan={5} className="px-4 py-10 text-center text-muted-foreground">{t("finance.noDueItems")}</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-xl border border-border bg-card">
        <div className="flex flex-col gap-4 border-b border-border p-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h2 className="text-lg font-semibold">{t("finance.orderHistory")}</h2>
            <p className="text-sm text-muted-foreground">{t("finance.orderHistoryHint")}</p>
          </div>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            <label className="space-y-1 text-xs text-muted-foreground">
              <span>{t("finance.distributor")}</span>
              <select className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm text-foreground" value={supplierId} onChange={(event) => setSupplierId(event.target.value)}>
                <option value="all">{t("finance.allDistributors")}</option>
                {accountSummary.map((account) => <option key={account.supplier_id} value={account.supplier_id}>{account.supplier_name}</option>)}
              </select>
            </label>
            <label className="space-y-1 text-xs text-muted-foreground">
              <span>{t("finance.paymentStatus")}</span>
              <select className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm text-foreground" value={status} onChange={(event) => setStatus(event.target.value)}>
                <option value="all">{t("finance.allStatuses")}</option>
                {["paid", "unpaid", "partially_paid", "overdue"].map((value) => <option key={value} value={value}>{t(`finance.status.${value}`)}</option>)}
              </select>
            </label>
            <label className="space-y-1 text-xs text-muted-foreground">
              <span>{t("finance.from")}</span>
              <input type="date" className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm text-foreground" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
            </label>
            <label className="space-y-1 text-xs text-muted-foreground">
              <span>{t("finance.to")}</span>
              <input type="date" className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm text-foreground" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
            </label>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[850px] text-sm">
            <thead className="bg-secondary/60 text-left text-xs uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="px-4 py-3">{t("finance.orderDate")}</th>
                <th className="px-4 py-3">{t("finance.orderNumber")}</th>
                <th className="px-4 py-3">{t("finance.distributor")}</th>
                <th className="px-4 py-3 text-right">{t("finance.orderTotal")}</th>
                <th className="px-4 py-3 text-right">{t("finance.paid")}</th>
                <th className="px-4 py-3 text-right">{t("finance.balance")}</th>
                <th className="px-4 py-3">{t("finance.dueDate")}</th>
                <th className="px-4 py-3">{t("common.status")}</th>
                <th className="px-4 py-3 text-right">{t("common.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {(data.orders || []).map((order) => (
                <tr key={order.id} className="border-t border-border" data-testid={`finance-order-${order.id}`}>
                  <td className="px-4 py-3 text-muted-foreground">{dateLabel(order.created_at)}</td>
                  <td className="px-4 py-3 font-mono font-semibold">{order.order_no}</td>
                  <td className="px-4 py-3">{order.supplier_name}</td>
                  <td className="px-4 py-3 text-right">{money(order.total)}</td>
                  <td className="px-4 py-3 text-right text-emerald-500">{money(order.amount_paid)}</td>
                  <td className="px-4 py-3 text-right font-semibold">{money(order.balance_due)}</td>
                  <td className="px-4 py-3 text-muted-foreground">{dateLabel(order.payment_due_date)}</td>
                  <td className="px-4 py-3"><PaymentStatus status={order.payment_status} t={t} /></td>
                  <td className="px-4 py-3 text-right">
                    {["Processing", "In Transit", "Delivered"].includes(order.status) && (
                      <Button size="sm" variant="outline" onClick={() => downloadInvoice(order)} disabled={downloading === order.id}>
                        {downloading === order.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="mr-1.5 h-4 w-4" />}
                        {t("finance.downloadInvoice")}
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
              {data.orders?.length === 0 && <tr><td colSpan={9} className="px-4 py-12 text-center text-muted-foreground">{t("finance.noOrders")}</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <Dialog open={!!statementSupplier} onOpenChange={(open) => { if (!open) setStatementSupplier(null); }}>
        <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("finance.statementTitle")}</DialogTitle>
            <DialogDescription>{statementSupplier?.supplier_name}</DialogDescription>
          </DialogHeader>
          {statement === null ? <div className="h-32 animate-pulse rounded-lg bg-secondary" /> : (
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full min-w-[550px] text-sm">
                <thead className="bg-secondary/60 text-left text-xs uppercase tracking-wider text-muted-foreground">
                  <tr><th className="px-3 py-2">{t("finance.orderDate")}</th><th className="px-3 py-2">{t("finance.transaction")}</th><th className="px-3 py-2">{t("finance.reference")}</th><th className="px-3 py-2 text-right">{t("finance.amount")}</th><th className="px-3 py-2 text-right">{t("finance.balance")}</th></tr>
                </thead>
                <tbody>
                  {transactions.map((item) => (
                    <tr key={item.id} className="border-t border-border">
                      <td className="px-3 py-2 text-muted-foreground">{dateLabel(item.date)}</td>
                      <td className="px-3 py-2">{item.type}</td>
                      <td className="px-3 py-2 font-mono text-xs">{item.reference}</td>
                      <td className={`px-3 py-2 text-right font-semibold ${item.kind === "payment" ? "text-emerald-500" : ""}`}>{money(item.amount)}</td>
                      <td className="px-3 py-2 text-right font-semibold">{money(item.running_balance)}</td>
                    </tr>
                  ))}
                  {transactions.length === 0 && <tr><td colSpan={5} className="px-3 py-8 text-center text-muted-foreground">{t("finance.noTransactions")}</td></tr>}
                </tbody>
              </table>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Metric({ label, value, tone = "" }) {
  return <div className="min-w-0 rounded-lg border border-border bg-background/50 p-2.5"><p className="truncate text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p><p className={`mt-1 truncate text-sm font-bold ${tone}`}>{value}</p></div>;
}

function PaymentStatus({ status, t }) {
  return <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${paymentStatusStyle[status] || ""}`}>{t(`finance.status.${status}`)}</span>;
}
