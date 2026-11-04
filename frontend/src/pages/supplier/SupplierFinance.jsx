import { useCallback, useEffect, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { useI18n } from "@/context/I18nContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Banknote, Loader2, Save, Wallet } from "lucide-react";
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

export default function SupplierFinance() {
  const { t, lang } = useI18n();
  const { user } = useAuth();
  const isSupplierOwner = user?.supplier_access_role !== "branch_manager";
  const [accounts, setAccounts] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [terms, setTerms] = useState({});
  const [savingTerms, setSavingTerms] = useState("");
  const [paymentOrder, setPaymentOrder] = useState(null);
  const [paymentForm, setPaymentForm] = useState({ amount: "", method: "cash", reference: "", note: "" });
  const [savingPayment, setSavingPayment] = useState(false);
  const [error, setError] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      const params = {};
      if (dateFrom) params.start_date = dateFrom;
      if (dateTo) params.end_date = dateTo;
      const { data } = await api.get("/supplier/credit-accounts", { params });
      setAccounts(data);
      setTerms(Object.fromEntries(data.map((account) => [account.retailer_id, {
        credit_limit: String(account.credit_limit || 0),
        payment_due_days: String(account.payment_due_days || 14),
      }])));
      setError("");
    } catch (requestError) {
      setError(formatApiError(requestError.response?.data?.detail));
      setAccounts([]);
    } finally {
      setRefreshing(false);
    }
  }, [dateFrom, dateTo]);

  useEffect(() => { load(); }, [load]);

  const updateTermField = (retailerId, field, value) => {
    setTerms((current) => ({
      ...current,
      [retailerId]: { ...current[retailerId], [field]: value },
    }));
  };

  const saveTerms = async (account) => {
    setSavingTerms(account.retailer_id);
    try {
      await api.put(`/supplier/stores/${encodeURIComponent(account.retailer_id)}/credit`, {
        credit_limit: Number(terms[account.retailer_id]?.credit_limit),
        payment_due_days: Number(terms[account.retailer_id]?.payment_due_days),
      });
      toast.success(t("finance.termsSaved"));
      await load();
    } catch (requestError) {
      toast.error(formatApiError(requestError.response?.data?.detail));
    } finally {
      setSavingTerms("");
    }
  };

  const openPayment = (order) => {
    setPaymentForm({ amount: Number(order.balance_due || 0).toFixed(2), method: "cash", reference: "", note: "" });
    setPaymentOrder(order);
  };

  const recordPayment = async (event) => {
    event.preventDefault();
    if (!paymentOrder) return;
    setSavingPayment(true);
    try {
      await api.post(`/supplier/orders/${encodeURIComponent(paymentOrder.id)}/payments`, {
        ...paymentForm,
        amount: Number(paymentForm.amount),
      });
      toast.success(t("finance.paymentSaved"));
      setPaymentOrder(null);
      await load();
    } catch (requestError) {
      toast.error(formatApiError(requestError.response?.data?.detail));
    } finally {
      setSavingPayment(false);
    }
  };

  const dateLabel = (value) => value
    ? new Date(value).toLocaleDateString(lang === "ka" ? "ka-GE" : lang === "ru" ? "ru-RU" : "en-GB")
    : "—";

  if (!accounts) return (
    <div className="space-y-5" data-testid="supplier-finance-skeleton" aria-busy="true">
      <Skeleton className="h-12 w-64" />
      <div className="grid gap-4 md:grid-cols-2">{[0, 1].map((item) => <Skeleton key={item} className="h-48" />)}</div>
      <Skeleton className="h-64 w-full" />
    </div>
  );

  return (
    <div className="space-y-6" data-testid="supplier-finance-page">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Wallet className="h-6 w-6 text-primary" />
            <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{t("finance.supplierTitle")}</h1>
            {refreshing && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-hidden="true" />}
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{t("finance.supplierSubtitle")}</p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="space-y-1 text-xs text-muted-foreground">
            <span>{t("finance.from")}</span>
            <Input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
          </label>
          <label className="space-y-1 text-xs text-muted-foreground">
            <span>{t("finance.to")}</span>
            <Input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
          </label>
          <FinanceExport dateFrom={dateFrom} dateTo={dateTo} />
        </div>
      </header>
      {error && <div role="alert" className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-500">{error}</div>}
      {accounts.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">{t("finance.noAccounts")}</div>
      ) : accounts.map((account) => (
        <section key={account.retailer_id} className="overflow-hidden rounded-xl border border-border bg-card" data-testid={`supplier-credit-account-${account.retailer_id}`}>
          <div className="grid gap-5 border-b border-border p-5 xl:grid-cols-[1fr_1.1fr]">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{t("finance.store")}</p>
              <h2 className="mt-1 text-lg font-semibold">{account.retailer_name}</h2>
              <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Metric label={t("finance.outstanding")} value={money(account.outstanding_balance)} tone="text-rose-500" />
                <Metric label={t("finance.creditLimit")} value={money(account.credit_limit)} />
                <Metric label={t("finance.availableCredit")} value={money(account.available_credit)} tone="text-primary" />
                <Metric label={t("finance.periodSales")} value={money(account.period_sales)} />
              </div>
            </div>
            {isSupplierOwner && <div className="rounded-lg border border-border bg-background/40 p-4">
              <h3 className="mb-3 text-sm font-semibold">{t("finance.creditTerms")}</h3>
              <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
                <label className="space-y-1 text-xs text-muted-foreground">
                  <span>{t("finance.creditLimit")} (₾)</span>
                  <Input type="number" min="0" step="0.01" value={terms[account.retailer_id]?.credit_limit ?? "0"} onChange={(event) => updateTermField(account.retailer_id, "credit_limit", event.target.value)} />
                </label>
                <label className="space-y-1 text-xs text-muted-foreground">
                  <span>{t("finance.paymentTerms")}</span>
                  <select className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm text-foreground" value={terms[account.retailer_id]?.payment_due_days ?? "14"} onChange={(event) => updateTermField(account.retailer_id, "payment_due_days", event.target.value)}>
                    {[7, 14, 30].map((days) => <option key={days} value={days}>{t("finance.termsDays").replace("{count}", String(days))}</option>)}
                  </select>
                </label>
                <Button size="sm" onClick={() => saveTerms(account)} disabled={savingTerms === account.retailer_id}>
                  {savingTerms === account.retailer_id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="mr-1.5 h-4 w-4" />}
                  {t("common.save")}
                </Button>
              </div>
            </div>}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[850px] text-sm">
              <thead className="bg-secondary/60 text-left text-xs uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="px-4 py-3">{t("finance.orderDate")}</th>
                  <th className="px-4 py-3">{t("finance.orderNumber")}</th>
                  <th className="px-4 py-3">{t("finance.dueDate")}</th>
                  <th className="px-4 py-3 text-right">{t("finance.orderTotal")}</th>
                  <th className="px-4 py-3 text-right">{t("finance.paid")}</th>
                  <th className="px-4 py-3 text-right">{t("finance.balance")}</th>
                  <th className="px-4 py-3">{t("common.status")}</th>
                  <th className="px-4 py-3 text-right">{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {account.orders.map((order) => (
                  <tr key={order.id} className="border-t border-border">
                    <td className="px-4 py-3 text-muted-foreground">{dateLabel(order.created_at)}</td>
                    <td className="px-4 py-3 font-mono font-semibold">{order.order_no}</td>
                    <td className="px-4 py-3 text-muted-foreground">{dateLabel(order.payment_due_date)}</td>
                    <td className="px-4 py-3 text-right">{money(order.total)}</td>
                    <td className="px-4 py-3 text-right text-emerald-500">{money(order.amount_paid)}</td>
                    <td className="px-4 py-3 text-right font-semibold">{money(order.balance_due)}</td>
                    <td className="px-4 py-3"><span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${paymentStatusStyle[order.payment_status] || ""}`}>{t(`finance.status.${order.payment_status}`)}</span></td>
                    <td className="px-4 py-3 text-right">
                      {order.balance_due > 0 && order.status !== "Cancelled" && (
                        <Button size="sm" variant="outline" onClick={() => openPayment(order)}>
                          <Banknote className="mr-1.5 h-4 w-4" />{t("finance.recordPayment")}
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
                {account.orders.length === 0 && <tr><td colSpan={8} className="px-4 py-10 text-center text-muted-foreground">{t("finance.noOrders")}</td></tr>}
              </tbody>
            </table>
          </div>
        </section>
      ))}

      <Dialog open={!!paymentOrder} onOpenChange={(open) => { if (!open) setPaymentOrder(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("finance.recordPayment")}</DialogTitle>
            <DialogDescription>{paymentOrder?.order_no} · {t("finance.remainingBalance")}: {money(paymentOrder?.balance_due)}</DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={recordPayment}>
            <label className="block space-y-1 text-sm">
              <span>{t("finance.paymentAmount")}</span>
              <Input type="number" min="0.01" max={paymentOrder?.balance_due} step="0.01" required value={paymentForm.amount} onChange={(event) => setPaymentForm((form) => ({ ...form, amount: event.target.value }))} />
            </label>
            <label className="block space-y-1 text-sm">
              <span>{t("finance.paymentMethod")}</span>
              <select className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground" value={paymentForm.method} onChange={(event) => setPaymentForm((form) => ({ ...form, method: event.target.value }))}>
                <option value="cash">{t("finance.method.cash")}</option>
                <option value="bank_transfer">{t("finance.method.bank_transfer")}</option>
              </select>
            </label>
            <label className="block space-y-1 text-sm">
              <span>{t("finance.reference")}</span>
              <Input maxLength={160} value={paymentForm.reference} onChange={(event) => setPaymentForm((form) => ({ ...form, reference: event.target.value }))} />
            </label>
            <label className="block space-y-1 text-sm">
              <span>{t("finance.note")}</span>
              <Input maxLength={500} value={paymentForm.note} onChange={(event) => setPaymentForm((form) => ({ ...form, note: event.target.value }))} />
            </label>
            <DialogFooter>
              <Button type="submit" disabled={savingPayment}>
                {savingPayment ? <Loader2 className="h-4 w-4 animate-spin" /> : t("finance.savePayment")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Metric({ label, value, tone = "" }) {
  return <div className="min-w-0 rounded-lg border border-border bg-background/50 p-2.5"><p className="truncate text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p><p className={`mt-1 truncate text-sm font-bold ${tone}`}>{value}</p></div>;
}
