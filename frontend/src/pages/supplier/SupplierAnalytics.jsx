import { useState } from "react";
import { BarChart3 } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Button } from "@/components/ui/button";
import { DateRangeFields, ExportButtons, Field, Stat, selectClass, useReport } from "@/components/ReportBits";
import { dateLabel, money, presetRange } from "@/lib/reports";

const EMPTY = { preset: "30", from: presetRange("30")[0], to: presetRange("30")[1], store: "", product: "" };
const tooltipStyle = { backgroundColor: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 };

function Chart({ title, children, empty }) {
  return (
    <section className="min-w-0 rounded-xl border border-border bg-card p-4">
      <h2 className="mb-3 text-sm font-semibold">{title}</h2>
      {empty ? <p className="py-10 text-center text-sm text-muted-foreground">მონაცემები არ არის.</p> : <div className="h-60 w-full">{children}</div>}
    </section>
  );
}

function Table({ columns, rows, empty = "მონაცემები არ არის." }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[480px] text-left text-sm">
        <thead className="text-xs text-muted-foreground"><tr>{columns.map(([key, label, align]) => <th key={key} className={`py-2 ${align === "right" ? "text-right" : ""}`}>{label}</th>)}</tr></thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index} className="border-t border-border">
              {columns.map(([key, , align, render]) => <td key={key} className={`py-1.5 pr-2 ${align === "right" ? "text-right font-mono" : ""}`}>{render ? render(row) : row[key]}</td>)}
            </tr>
          ))}
          {!rows.length && <tr><td colSpan={columns.length} className="py-6 text-center text-muted-foreground">{empty}</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

export default function SupplierAnalytics() {
  const [filters, setFilters] = useState(EMPTY);
  const options = useReport("/supplier/reports/filter-options", {});
  const params = { start_date: filters.from, end_date: filters.to, store_id: filters.store, product_id: filters.product };
  const { data, loading, error } = useReport("/supplier/reports/analytics", params);
  const invalidRange = filters.from && filters.to && filters.from > filters.to;
  const k = data?.kpis;
  const change = data?.change || {};
  const compare = data?.previous;

  return (
    <div className="space-y-6" data-testid="supplier-analytics-panel">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2"><BarChart3 className="h-6 w-6 text-primary" /><h1 className="text-2xl font-bold tracking-tight sm:text-3xl">ანალიტიკა</h1></div>
          <p className="mt-1 text-sm text-muted-foreground">გაუქმებული შეკვეთების გარეშე; დაბრუნებული საქონელი გამოკლებულია. საკომისიო აღებულია შეკვეთაზე დაფიქსირებული პირობებიდან.</p>
        </div>
        <ExportButtons path="/supplier/reports/analytics/export" params={params} name="analytics" />
      </header>

      <section className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4" aria-label="ფილტრები">
        <DateRangeFields preset={filters.preset} from={filters.from} to={filters.to} onChange={(value) => setFilters((c) => ({ ...c, ...value }))} />
        <Field label="მაღაზია"><select className={selectClass} value={filters.store} onChange={(e) => setFilters((c) => ({ ...c, store: e.target.value }))} data-testid="analytics-store"><option value="">ყველა</option>{(options.data?.stores || []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></Field>
        <Field label="პროდუქტი"><select className={selectClass} value={filters.product} onChange={(e) => setFilters((c) => ({ ...c, product: e.target.value }))} data-testid="analytics-product"><option value="">ყველა</option>{(options.data?.products || []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
        <div className="flex items-end"><Button variant="ghost" size="sm" onClick={() => setFilters(EMPTY)}>ფილტრების გასუფთავება</Button></div>
      </section>

      {invalidRange && <p role="alert" className="text-sm text-destructive">დაწყების თარიღი დასრულების თარიღზე გვიანია.</p>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {loading && !data && <p className="py-10 text-center text-sm text-muted-foreground" aria-busy="true">იტვირთება...</p>}

      {k && (
        <>
          <section className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="analytics-kpis">
            <Stat label="ჯამური გაყიდვები" value={money(k.total_sales)} change={change.total_sales} />
            <Stat label="შეკვეთები" value={k.orders} change={change.orders} />
            <Stat label="დასრულებული შეკვეთები" value={k.completed_orders} change={change.completed_orders} />
            <Stat label="საშუალო შეკვეთა" value={money(k.average_order_value)} change={change.average_order_value} />
            <Stat label="გაყიდული რაოდენობა" value={k.quantity} change={change.quantity} />
            <Stat label="Distro საკომისიო" value={money(k.commission)} hint="შეკვეთებზე დაფიქსირებული პირობებით" />
            <Stat label="ნეტო შემოსავალი" value={money(k.net_revenue)} hint="საკომისიოს გამოკლებით" />
          </section>

          <Chart title={`შემოსავლის ტრენდი (${data.granularity === "daily" ? "დღეები" : "თვეები"})`} empty={!data.series.length}>
            <ResponsiveContainer width="100%" height="100%"><LineChart data={data.series} margin={{ left: 0, right: 8 }}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="period" tick={{ fontSize: 10 }} minTickGap={24} /><YAxis tick={{ fontSize: 10 }} width={48} /><Tooltip contentStyle={tooltipStyle} formatter={(v) => money(v)} /><Legend /><Line type="monotone" dataKey="sales" name="გაყიდვები" stroke="#22c55e" strokeWidth={2} dot={false} /><Line type="monotone" dataKey="commission" name="საკომისიო" stroke="#f59e0b" strokeWidth={2} dot={false} /></LineChart></ResponsiveContainer>
          </Chart>

          <div className="grid gap-4 lg:grid-cols-2">
            <Chart title="ყველაზე გაყიდვადი პროდუქტები (რაოდენობა)" empty={!data.top_products.length}>
              <ResponsiveContainer width="100%" height="100%"><BarChart data={data.top_products} layout="vertical" margin={{ left: 8, right: 8 }}><CartesianGrid strokeDasharray="3 3" horizontal={false} /><XAxis type="number" tick={{ fontSize: 10 }} /><YAxis type="category" dataKey="name" width={96} tick={{ fontSize: 10 }} /><Tooltip contentStyle={tooltipStyle} /><Bar dataKey="quantity" name="რაოდენობა" fill="#38bdf8" radius={[0, 3, 3, 0]} /></BarChart></ResponsiveContainer>
            </Chart>
            <Chart title="გაყიდვები მაღაზიების მიხედვით" empty={!data.stores.length}>
              <ResponsiveContainer width="100%" height="100%"><BarChart data={data.stores.slice(0, 10)} layout="vertical" margin={{ left: 8, right: 8 }}><CartesianGrid strokeDasharray="3 3" horizontal={false} /><XAxis type="number" tick={{ fontSize: 10 }} /><YAxis type="category" dataKey="store_name" width={96} tick={{ fontSize: 10 }} /><Tooltip contentStyle={tooltipStyle} formatter={(v) => money(v)} /><Bar dataKey="sales" name="გაყიდვები" fill="#22c55e" radius={[0, 3, 3, 0]} /></BarChart></ResponsiveContainer>
            </Chart>
          </div>

          <section className="rounded-xl border border-border bg-card p-4">
            <h2 className="mb-1 text-sm font-semibold">პერიოდების შედარება</h2>
            {compare ? (
              <>
                <p className="mb-2 text-xs text-muted-foreground">წინა პერიოდი: {dateLabel(data.previous_range.start_date)} – {dateLabel(data.previous_range.end_date)}</p>
                <Table columns={[["m", "მაჩვენებელი"], ["c", "მიმდინარე", "right"], ["p", "წინა", "right"], ["d", "ცვლილება", "right"]]} rows={[
                  ["ჯამური გაყიდვები", money(k.total_sales), money(compare.total_sales), change.total_sales],
                  ["შეკვეთები", k.orders, compare.orders, change.orders],
                  ["გაყიდული რაოდენობა", k.quantity, compare.quantity, change.quantity],
                  ["Distro საკომისიო", money(k.commission), money(compare.commission), change.commission],
                  ["ნეტო შემოსავალი", money(k.net_revenue), money(compare.net_revenue), change.net_revenue],
                ].map(([m, c, p, d]) => ({ m, c, p, d: d === null || d === undefined ? "—" : `${d > 0 ? "+" : ""}${d}%` }))} />
              </>
            ) : <p className="text-sm text-muted-foreground">შედარებისთვის აირჩიეთ კონკრეტული პერიოდი (მთელი პერიოდის არჩევისას წინა პერიოდი არ არსებობს).</p>}
          </section>

          <div className="grid gap-4 lg:grid-cols-2">
            <section className="rounded-xl border border-border bg-card p-4">
              <h2 className="mb-2 text-sm font-semibold">გაყიდვები პროდუქტების მიხედვით</h2>
              <Table columns={[["name", "პროდუქტი"], ["quantity", "რაოდ.", "right"], ["sales", "გაყიდვები", "right", (r) => money(r.sales)], ["commission", "საკომისიო", "right", (r) => money(r.commission)]]} rows={data.products.slice(0, 50)} />
            </section>
            <section className="rounded-xl border border-border bg-card p-4">
              <h2 className="mb-2 text-sm font-semibold">ყველაზე აქტიური მაღაზიები</h2>
              <Table columns={[["store_name", "მაღაზია"], ["orders", "შეკვ.", "right"], ["sales", "გაყიდვები", "right", (r) => money(r.sales)], ["net_revenue", "ნეტო", "right", (r) => money(r.net_revenue)]]} rows={data.most_active_stores} />
            </section>
          </div>
        </>
      )}
    </div>
  );
}
