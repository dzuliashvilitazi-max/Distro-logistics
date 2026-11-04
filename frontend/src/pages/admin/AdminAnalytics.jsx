import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useI18n } from "@/context/I18nContext";
import { Loader2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ChartCard, SummaryCard, RevenueChart, UserGrowthChart, OrdersChart, money,
} from "@/components/analytics/AnalyticsCharts";

const thisYear = new Date().getFullYear();
const PERIODS = [
  { value: "m6", label: "ბოლო 6 თვე", params: { months: 6 } },
  { value: "m12", label: "ბოლო 12 თვე", params: { months: 12 } },
  { value: `y${thisYear}`, label: `${thisYear} წელი`, params: { year: thisYear } },
  { value: `y${thisYear - 1}`, label: `${thisYear - 1} წელი`, params: { year: thisYear - 1 } },
];
const DAY_PERIODS = [
  { value: 7, label: "ბოლო 7 დღე" },
  { value: 30, label: "ბოლო 30 დღე" },
  { value: 90, label: "ბოლო 90 დღე" },
];

export default function AdminAnalytics() {
  const { t } = useI18n();
  const [granularity, setGranularity] = useState("monthly");
  const [period, setPeriod] = useState("m12");
  const [days, setDays] = useState(30);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const params = dateFrom || dateTo
      ? { granularity, ...(dateFrom ? { start_date: dateFrom } : {}), ...(dateTo ? { end_date: dateTo } : {}) }
      : granularity === "daily"
        ? { granularity, days }
        : { ...PERIODS.find((p) => p.value === period).params, granularity };
    const load = () => api.get("/admin/analytics/overview", { params })
      .then((r) => { if (!cancelled) setData(r.data); })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false); });
    setLoading(true);
    load();
    const timer = setInterval(load, 15000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [granularity, period, days, dateFrom, dateTo]);

  const s = data?.summary;
  return (
    <div className="space-y-6" data-testid="admin-analytics-page">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold tracking-tight">ანალიტიკა</h1>
        <div className="flex items-center gap-2">
          {loading && <Loader2 className="h-4 w-4 animate-spin" />}
          <div className="inline-flex rounded-md border border-border p-0.5" role="group" aria-label="ანალიტიკის პერიოდულობა">
            {[ ["daily", "დღიური"], ["monthly", "თვიური"] ].map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => setGranularity(value)}
                aria-pressed={granularity === value}
                className={`rounded px-3 py-1.5 text-sm ${granularity === value ? "bg-primary text-primary-foreground" : "text-muted-foreground"}`}
                data-testid={`analytics-${value}-toggle`}
              >
                {label}
              </button>
            ))}
          </div>
          {granularity === "daily" ? (
            <select
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className="rounded-md border border-border bg-background px-3 py-2 text-sm"
              data-testid="analytics-period"
            >
              {DAY_PERIODS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
            </select>
          ) : (
            <select
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
              className="rounded-md border border-border bg-background px-3 py-2 text-sm"
              data-testid="analytics-period"
            >
              {PERIODS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
            </select>
          )}
          <label className="space-y-1 text-[11px] text-muted-foreground">
            <span>{t("finance.from")}</span>
            <Input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
          </label>
          <label className="space-y-1 text-[11px] text-muted-foreground">
            <span>{t("finance.to")}</span>
            <Input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
          </label>
        </div>
      </div>

      {loading && !data && (
        <div className="space-y-4" data-testid="admin-analytics-skeleton" aria-busy="true">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-5">{[0, 1, 2, 3, 4].map((item) => <Skeleton key={item} className="h-28" />)}</div>
          <Skeleton className="h-80 w-full" />
          <div className="grid gap-4 xl:grid-cols-2"><Skeleton className="h-64" /><Skeleton className="h-64" /></div>
        </div>
      )}

      {s && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-5">
          <SummaryCard label="საშუალო თვიური შემოსავალი (MRR)" value={money(s.mrr)} hint={`სულ: ${money(s.total_revenue)}`} />
          <SummaryCard label="საშუალო შეკვეთა (AOV)" value={money(s.aov)} hint={`GMV: ${money(s.total_gmv)}`} />
          <SummaryCard label="აქტიური მომხმარებლები" value={`${s.active_pct}%`} hint={`${s.users_active} / ${s.users_total} (ბოლო 30 დღე)`} />
          <SummaryCard label="პასიური მომხმარებლები" value={`${s.inactive_pct}%`} hint={`${s.users_inactive} / ${s.users_total}`} />
          <SummaryCard label={t("adm.systemDebt")} value={money(s.system_debt)} hint={`${s.open_invoices} ${t("bill.invoiceNo").toLowerCase()}`} tone="text-rose-500" />
        </div>
      )}

      {data && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <div className="xl:col-span-2">
            <ChartCard title="ბრუნვა (GMV) და პლატფორმის საკომისიო" testid="chart-revenue">
              <RevenueChart data={data.series} />
            </ChartCard>
          </div>
          <ChartCard title="რეგისტრაციების ზრდა" testid="chart-users">
            <UserGrowthChart data={data.series} />
          </ChartCard>
          <ChartCard title="შეკვეთების სტატისტიკა" testid="chart-orders">
            <OrdersChart data={data.series} />
          </ChartCard>
        </div>
      )}
    </div>
  );
}
