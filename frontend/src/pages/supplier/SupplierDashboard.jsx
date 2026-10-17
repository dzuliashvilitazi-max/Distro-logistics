import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useI18n } from "@/context/I18nContext";
import { DollarSign, Activity, Boxes, AlertTriangle, TrendingUp } from "lucide-react";
import { AreaChart, Area, XAxis, YAxis, ResponsiveContainer, Tooltip, BarChart, Bar } from "recharts";
import { cn } from "@/lib/utils";

function MetricCard({ icon: Icon, label, value, accent, testid }) {
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

export default function SupplierDashboard() {
  const { t } = useI18n();
  const [a, setA] = useState(null);
  useEffect(() => { api.get("/analytics/supplier").then((r) => setA(r.data)); }, []);
  if (!a) return <div className="h-64 animate-pulse rounded-xl bg-secondary" />;

  return (
    <div>
      <h1 className="mb-6 text-2xl font-bold tracking-tight sm:text-3xl">{t("sup.title")}</h1>
      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard icon={DollarSign} label={t("sup.totalRevenue")} value={`₾${a.revenue.toLocaleString()}`} accent="bg-emerald-500/15 text-emerald-500" testid="metric-revenue" />
        <MetricCard icon={TrendingUp} label={t("sup.todaysSales")} value={`₾${a.daily.toLocaleString()}`} accent="bg-primary/15 text-primary" testid="metric-daily" />
        <MetricCard icon={Activity} label={t("sup.activeOrders")} value={a.active_orders} accent="bg-indigo-500/15 text-indigo-400" testid="metric-active" />
        <MetricCard icon={Boxes} label={t("sup.products")} value={a.product_count} accent="bg-amber-500/15 text-amber-500" testid="metric-products" />
      </div>

      <div className="grid gap-6 lg:grid-cols-12">
        <div className="rounded-xl border border-border bg-card p-5 lg:col-span-7">
          <h3 className="text-lg font-semibold">{t("sup.salesLast7")}</h3>
          <div className="mt-4 h-64 min-w-0">
            <ResponsiveContainer width="100%" height="100%" minWidth={0}>
              <AreaChart data={a.series}>
                <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="hsl(var(--primary))" stopOpacity={0.4} /><stop offset="95%" stopColor="hsl(var(--primary))" stopOpacity={0} /></linearGradient></defs>
                <XAxis dataKey="day" stroke="hsl(var(--muted-foreground))" fontSize={11} />
                <YAxis stroke="hsl(var(--muted-foreground))" fontSize={11} />
                <Tooltip contentStyle={{ background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", borderRadius: 8, color: "hsl(var(--foreground))" }} />
                <Area type="monotone" dataKey="sales" stroke="hsl(var(--primary))" strokeWidth={2} fill="url(#g)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="space-y-6 lg:col-span-5">
          <div className="rounded-xl border border-border bg-card p-5">
            <h3 className="text-lg font-semibold">{t("sup.popularItems")}</h3>
            <div className="mt-4 h-48 min-w-0">
              {a.popular.length === 0 ? <p className="py-10 text-center text-sm text-muted-foreground">{t("sup.noSalesYet")}</p> : (
                <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                  <BarChart data={a.popular} layout="vertical" margin={{ left: 0 }}>
                    <XAxis type="number" hide /><YAxis type="category" dataKey="name" width={0} hide />
                    <Tooltip contentStyle={{ background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", borderRadius: 8 }} />
                    <Bar dataKey="qty" fill="hsl(var(--primary))" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
            <div className="space-y-1.5">
              {a.popular.slice(0, 3).map((p, i) => (
                <div key={p.name} className="flex items-center justify-between text-sm"><span className="truncate"><span className="font-mono text-muted-foreground">#{i + 1}</span> {p.name}</span><span className="font-semibold">{p.qty}</span></div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {a.low_stock.length > 0 && (
        <div className="mt-6 rounded-xl border border-amber-500/30 bg-amber-500/5 p-5" data-testid="low-stock-alert">
          <h3 className="flex items-center gap-2 text-lg font-semibold text-amber-500"><AlertTriangle className="h-5 w-5" /> {t("sup.lowStockAlerts")}</h3>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {a.low_stock.map((p) => (
              <div key={p.id} className="flex items-center justify-between rounded-lg border border-border bg-card px-3 py-2 text-sm"><span className="truncate">{p.name}</span><span className="font-mono font-bold text-amber-500">{p.stock} {t("sup.left")}</span></div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
