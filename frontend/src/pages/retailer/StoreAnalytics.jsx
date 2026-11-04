import { useEffect, useMemo, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { useStoreBranch } from "@/context/StoreBranchContext";
import { useI18n } from "@/context/I18nContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { BarChart3, Loader2, Plus, TrendingDown, TrendingUp } from "lucide-react";
import { toast } from "sonner";

const money = (value) => `₾${Number(value || 0).toFixed(2)}`;
const toCents = (value) => Math.round(Number(value || 0) * 100);

export default function StoreAnalytics() {
  const { t } = useI18n();
  const { branches } = useStoreBranch();
  const [data, setData] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ branch_id: "", category: "rent", amount: "", expense_date: new Date().toISOString().slice(0, 10), note: "" });
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  useEffect(() => {
    if (branches.length && !form.branch_id) setForm((current) => ({ ...current, branch_id: branches[0].id }));
  }, [branches, form.branch_id]);

  const load = async () => {
    setRefreshing(true);
    try {
      const params = {};
      if (dateFrom) params.date_from = dateFrom;
      if (dateTo) params.date_to = dateTo;
      const { data: result } = await api.get("/store/analytics", { params });
      setData(result);
      setError("");
    } catch (requestError) {
      setError(formatApiError(requestError.response?.data?.detail));
      setData({ branches: [], leaderboard: [], demand_recommendations: [], market_benchmarks: {} });
    } finally {
      setRefreshing(false);
    }
  };
  useEffect(() => { load(); }, [dateFrom, dateTo]);

  const leaders = useMemo(() => {
    const profits = [...(data?.branches || [])].sort((a, b) => b.net_profit - a.net_profit);
    return { top: profits[0], bottom: profits.length > 1 ? profits[profits.length - 1] : null };
  }, [data]);
  const rankedBranches = useMemo(() => {
    const byId = new Map((data?.branches || []).map((branch) => [branch.id, branch]));
    const ranked = (data?.leaderboard || []).map((entry) => byId.get(entry.branch_id)).filter(Boolean);
    return ranked.length ? ranked : data?.branches || [];
  }, [data]);
  const consolidated = useMemo(() => {
    const cents = (data?.branches || []).reduce((result, branch) => ({
      revenue: result.revenue + toCents(branch.revenue),
      cost_of_goods: result.cost_of_goods + toCents(branch.cost_of_goods),
      operating_expenses: result.operating_expenses + toCents(branch.operating_expenses),
      net_profit: result.net_profit + toCents(branch.net_profit),
    }), { revenue: 0, cost_of_goods: 0, operating_expenses: 0, net_profit: 0 });
    const totals = Object.fromEntries(Object.entries(cents).map(([key, value]) => [key, value / 100]));
    return {
      ...totals,
      operating_margin: cents.revenue ? cents.net_profit / cents.revenue * 100 : 0,
    };
  }, [data]);
  const maxRevenue = Math.max(1, ...(data?.branches || []).map((branch) => branch.revenue));
  const createExpense = async (event) => {
    event.preventDefault();
    setSaving(true);
    try {
      await api.post("/store/branch-expenses", {
        ...form,
        amount: Number(form.amount),
        expense_date: new Date(`${form.expense_date}T12:00:00`).toISOString(),
      });
      toast.success(t("analytics.expenseSaved"));
      setDialogOpen(false);
      setForm((current) => ({ ...current, amount: "", note: "" }));
      await load();
    } catch (requestError) {
      toast.error(formatApiError(requestError.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  };

  if (!data) return <div className="h-72 animate-pulse rounded-xl bg-secondary" />;

  return (
    <div className="space-y-6" data-testid="store-analytics-page">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2"><BarChart3 className="h-6 w-6 text-primary" /><h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{t("analytics.title")}</h1>{refreshing && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-hidden="true" />}</div>
          <p className="mt-1 text-sm text-muted-foreground">{t("analytics.subtitle")}</p>
        </div>
        <Button onClick={() => setDialogOpen(true)} disabled={!branches.length}><Plus className="mr-1.5 h-4 w-4" />{t("analytics.addExpense")}</Button>
      </header>
      {error && <p role="alert" className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-500">{error}</p>}
      <div className="flex flex-wrap items-end gap-3 rounded-xl border border-border bg-card p-4">
        <label className="space-y-1 text-xs text-muted-foreground"><span>{t("finance.from")}</span><Input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} /></label>
        <label className="space-y-1 text-xs text-muted-foreground"><span>{t("finance.to")}</span><Input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} /></label>
        <p className="text-xs text-muted-foreground">{t("analytics.rangeHint")}</p>
      </div>

      <section className="space-y-3" aria-label={t("analytics.consolidatedTitle")}>
        <h2 className="font-semibold">{t("analytics.consolidatedTitle")}</h2>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <SummaryCard label={t("analytics.revenue")} value={money(consolidated.revenue)} />
          <SummaryCard label={t("analytics.costOfGoods")} value={money(consolidated.cost_of_goods)} />
          <SummaryCard label={t("analytics.expenses")} value={money(consolidated.operating_expenses)} />
          <SummaryCard label={t("analytics.netProfit")} value={money(consolidated.net_profit)} tone={consolidated.net_profit >= 0 ? "text-emerald-500" : "text-rose-500"} />
          <SummaryCard label={t("analytics.operatingMargin")} value={`${consolidated.operating_margin.toFixed(1)}%`} />
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <BranchHighlight title={t("analytics.topBranch")} branch={leaders.top} money={money} />
        <BranchHighlight title={t("analytics.needsAttention")} branch={leaders.bottom} money={money} negative />
      </section>

      <section className="overflow-hidden rounded-xl border border-border bg-card">
        <div className="border-b border-border p-4">
          <h2 className="font-semibold">{t("analytics.pnlTitle")}</h2>
          <p className="mt-1 text-xs text-muted-foreground">{t("analytics.pnlNote")}</p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[800px] text-sm">
            <thead className="bg-secondary/60 text-left text-xs uppercase tracking-wider text-muted-foreground">
              <tr><th className="px-4 py-3">{t("branch.name")}</th><th className="px-4 py-3 text-right">{t("analytics.revenue")}</th><th className="px-4 py-3 text-right">{t("analytics.costOfGoods")}</th><th className="px-4 py-3 text-right">{t("analytics.expenses")}</th><th className="px-4 py-3 text-right">{t("analytics.netProfit")}</th><th className="px-4 py-3 text-right">{t("analytics.operatingMargin")}</th></tr>
            </thead>
            <tbody>
              {rankedBranches.map((branch, index) => (
                <tr key={branch.id} className="border-t border-border">
                  <td className="px-4 py-3"><span className="mr-2 font-mono text-xs text-primary">#{index + 1}</span>{branch.name}</td>
                  <td className="px-4 py-3 text-right">{money(branch.revenue)}</td>
                  <td className="px-4 py-3 text-right">{money(branch.cost_of_goods)}</td>
                  <td className="px-4 py-3 text-right">{money(branch.operating_expenses)}</td>
                  <td className={`px-4 py-3 text-right font-semibold ${branch.net_profit >= 0 ? "text-emerald-500" : "text-rose-500"}`}>{money(branch.net_profit)}</td>
                  <td className="px-4 py-3 text-right">{Number(branch.operating_margin || 0).toFixed(1)}%</td>
                </tr>
              ))}
              {data.branches.length === 0 && <tr><td colSpan={6} className="px-4 py-10 text-center text-muted-foreground">{t("branch.empty")}</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-2">
        <div className="space-y-3 rounded-xl border border-border bg-card p-5">
          <h2 className="font-semibold">{t("analytics.comparison")}</h2>
          {data.branches.map((branch) => (
            <div key={branch.id} className="space-y-1.5" data-testid={`analytics-branch-${branch.id}`}>
              <div className="flex justify-between gap-3 text-sm"><span className="truncate">{branch.name}</span><span className="font-mono">{money(branch.revenue)}</span></div>
              <div className="h-2 overflow-hidden rounded-full bg-secondary"><div className="h-full rounded-full bg-primary" style={{ width: `${Math.min(100, branch.revenue / maxRevenue * 100)}%` }} /></div>
            </div>
          ))}
          {data.branches.length === 0 && <p className="text-sm text-muted-foreground">{t("analytics.noSales")}</p>}
        </div>
        <div className="space-y-3 rounded-xl border border-border bg-card p-5">
          <h2 className="font-semibold">{t("analytics.demandTitle")}</h2>
          {data.demand_recommendations.map((recommendation, index) => (
            <div key={`${recommendation.branch_id}-${recommendation.product_id}-${index}`} className="flex items-start gap-3 rounded-lg border border-border p-3">
              {recommendation.recommendation === "higher_demand" ? <TrendingUp className="mt-0.5 h-4 w-4 text-emerald-500" /> : <TrendingDown className="mt-0.5 h-4 w-4 text-amber-500" />}
              <p className="text-sm"><span className="font-semibold">{recommendation.product_name}</span> · {recommendation.branch_name}<span className="block text-xs text-muted-foreground">{t(`analytics.recommendation.${recommendation.recommendation}`)}</span></p>
            </div>
          ))}
          {data.demand_recommendations.length === 0 && <p className="text-sm text-muted-foreground">{t("analytics.demandEmpty")}</p>}
        </div>
      </section>

      <section className="space-y-4">
        <h2 className="text-lg font-semibold">{t("analytics.productSales")}</h2>
        <div className="grid gap-4 xl:grid-cols-2">
          {data.branches.map((branch) => (
            <article key={branch.id} className="rounded-xl border border-border bg-card p-5">
              <h3 className="font-semibold">{branch.name}</h3>
              <div className="mt-3 space-y-3">
                {branch.top_products.map((product) => {
                  const maxUnits = Math.max(1, ...branch.top_products.map((item) => item.quantity_sold));
                  const benchmark = data.market_benchmarks?.[product.product_id];
                  return (
                    <div key={product.product_id || product.product_name} className="space-y-1">
                      <div className="flex justify-between gap-3 text-sm"><span className="truncate">{product.product_name}</span><span className="font-mono">{Number(product.quantity_sold).toLocaleString()} {t("analytics.units")}</span></div>
                      <div className="h-1.5 rounded-full bg-secondary"><div className="h-full rounded-full bg-sky-500" style={{ width: `${Math.min(100, product.quantity_sold / maxUnits * 100)}%` }} /></div>
                      <p className="text-xs text-muted-foreground">{t("analytics.salesRevenue")}: {money(product.revenue)} · {t("analytics.productProfitBeforeExpenses")}: {money(product.net_profit)}{benchmark ? ` · ${t("analytics.marketMedian")}: ${money(benchmark.median_retail_price)}` : ""}</p>
                    </div>
                  );
                })}
                {branch.top_products.length === 0 && <p className="text-sm text-muted-foreground">{t("analytics.noSales")}</p>}
              </div>
            </article>
          ))}
        </div>
      </section>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>{t("analytics.addExpense")}</DialogTitle><DialogDescription>{t("analytics.expenseDescription")}</DialogDescription></DialogHeader>
          <form className="space-y-4" onSubmit={createExpense}>
            <label className="block space-y-1 text-sm"><span>{t("branch.name")}</span><select className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground" value={form.branch_id} onChange={(event) => setForm({ ...form, branch_id: event.target.value })}>{branches.map((branch) => <option key={branch.id} value={branch.id}>{branch.name}</option>)}</select></label>
            <label className="block space-y-1 text-sm"><span>{t("analytics.expenseCategory")}</span><select className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground" value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value })}>{["rent", "wages", "utilities", "transport", "other"].map((category) => <option key={category} value={category}>{t(`analytics.expenseCategory.${category}`)}</option>)}</select></label>
            <label className="block space-y-1 text-sm"><span>{t("analytics.expenseAmount")}</span><Input type="number" required min="0.01" step="0.01" value={form.amount} onChange={(event) => setForm({ ...form, amount: event.target.value })} /></label>
            <label className="block space-y-1 text-sm"><span>{t("analytics.expenseDate")}</span><Input type="date" required value={form.expense_date} onChange={(event) => setForm({ ...form, expense_date: event.target.value })} /></label>
            <label className="block space-y-1 text-sm"><span>{t("finance.note")}</span><Input maxLength={500} value={form.note} onChange={(event) => setForm({ ...form, note: event.target.value })} /></label>
            <DialogFooter><Button type="submit" disabled={saving}>{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : t("common.save")}</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function SummaryCard({ label, value, tone = "" }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`mt-1 text-xl font-bold ${tone}`}>{value}</p>
    </div>
  );
}

function BranchHighlight({ title, branch, money, negative = false }) {
  const { t } = useI18n();
  const Icon = negative ? TrendingDown : TrendingUp;
  return (
    <div className={`rounded-xl border p-5 ${branch ? (negative ? "border-amber-500/30 bg-amber-500/5" : "border-emerald-500/30 bg-emerald-500/5") : "border-border bg-card"}`}>
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground"><Icon className="h-4 w-4" />{title}</div>
      <p className="mt-2 text-lg font-semibold">{branch?.name || t("analytics.noBranches")}</p>
      {branch && <p className="mt-1 text-sm text-muted-foreground">{t("analytics.netProfit")}: <span className="font-semibold text-foreground">{money(branch.net_profit)}</span> · {t("analytics.operatingMargin")}: {Number(branch.operating_margin).toFixed(1)}%</p>}
    </div>
  );
}
