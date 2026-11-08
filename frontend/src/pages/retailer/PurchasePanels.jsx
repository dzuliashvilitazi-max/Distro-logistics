import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { endOfMonth, format, parseISO, startOfMonth, startOfYear, subDays, subMonths } from "date-fns";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ArrowLeft, Eye, FileDown, Printer } from "lucide-react";
import { toast } from "sonner";
import { api, formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { calculatePurchaseAnalytics, purchaseDay } from "@/lib/purchaseAnalytics.mjs";

const money = (value) => `₾${Number(value || 0).toFixed(2)}`;
const dateLabel = (value) => value && !Number.isNaN(new Date(value).getTime())
  ? new Date(value).toLocaleDateString("ka-GE", { timeZone: "Asia/Tbilisi" }) : "—";
const paymentLabels = { paid: "გადახდილი", unpaid: "გადაუხდელი", overdue: "ვადაგადაცილებული", partially_paid: "ნაწილობრივ გადახდილი" };

function usePurchaseOrders() {
  const [state, setState] = useState({ orders: [], loading: true, error: "" });
  useEffect(() => {
    let active = true;
    let inFlight = false;
    setState({ orders: [], loading: true, error: "" });
    const load = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const orders = new Map();
        let offset = 0;
        let page;
        do {
          const response = await api.get("/store/purchase-orders", { params: { limit: 1000, offset } });
          page = response.data;
          page.forEach((order) => orders.set(order.id, order));
          offset += page.length;
        } while (page.length === 1000);
        if (active) setState({ orders: [...orders.values()], loading: false, error: "" });
      } catch (error) {
        if (active) setState((current) => ({ ...current, loading: false, error: formatApiError(error.response?.data?.detail) || "მონაცემების ჩატვირთვა ვერ მოხერხდა" }));
      } finally { inFlight = false; }
    };
    load();
    const interval = setInterval(load, 15000);
    return () => { active = false; clearInterval(interval); };
  }, []);
  return state;
}

async function downloadInvoice(order) {
  try {
    const response = await api.get(`/orders/${encodeURIComponent(order.id)}/invoice.pdf`, { responseType: "blob" });
    const url = URL.createObjectURL(new Blob([response.data], { type: "application/pdf" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `${order.order_no}-invoice.pdf`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  } catch (error) {
    toast.error(formatApiError(error.response?.data?.detail) || "ინვოისის ჩამოტვირთვა ვერ მოხერხდა");
  }
}

function DataState({ state, children }) {
  if (state.loading) return <p className="py-8 text-sm text-muted-foreground" aria-busy="true">იტვირთება...</p>;
  if (state.error) return <p className="py-8 text-sm text-destructive" role="alert">{state.error}</p>;
  return children;
}

function OrderItems({ order }) {
  return (
    <div className="space-y-2">
      {(order.items || []).map((item, index) => (
        <div key={`${item.product_id}-${index}`} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-sm">
          <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">{item.name}</span>
          <span className="font-mono text-muted-foreground">{item.quantity} × {money(item.unit_price)}</span>
          <span className="font-semibold">{money(Number(item.quantity || 0) * Number(item.unit_price || 0))}</span>
        </div>
      ))}
    </div>
  );
}

export function CompletedOrders() {
  const state = usePurchaseOrders();
  const orders = state.orders.filter((order) => order.status === "Delivered");
  return (
    <div className="space-y-5" data-testid="completed-orders-page">
      <h1 className="text-2xl font-bold">დასრულებული შეკვეთები</h1>
      <DataState state={state}>
        {orders.length === 0 && <p className="py-8 text-sm text-muted-foreground">დასრულებული შეკვეთები არ არის.</p>}
        <div className="space-y-3">
          {orders.map((order) => (
            <Link key={order.id} to={`/completed-orders/${encodeURIComponent(order.id)}`} className="block rounded-md border border-border bg-card p-4 hover:border-primary" data-testid={`completed-order-${order.id}`}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div><span className="font-semibold text-primary">{order.order_no}</span><p className="mt-1 text-sm text-muted-foreground">{order.supplier_name} · {dateLabel(order.created_at)}</p></div>
                <div className="text-right"><p className="font-semibold">{money(order.total)}</p><p className="text-xs text-muted-foreground">{paymentLabels[order.payment_status] || order.payment_status}</p></div>
              </div>
              <p className="mt-3 text-xs text-muted-foreground">დასრულება: {dateLabel(order.delivered_at)}{!order.external_order && " · ინვოისი ხელმისაწვდომია"}</p>
              <div className="mt-3 border-t border-border pt-3"><OrderItems order={order} /></div>
            </Link>
          ))}
        </div>
      </DataState>
    </div>
  );
}

export function CompletedOrderDetail({ completedOnly = true }) {
  const { orderId } = useParams();
  const state = usePurchaseOrders();
  const order = state.orders.find((entry) => entry.id === orderId && (!completedOnly || entry.status === "Delivered"));
  return (
    <div className="space-y-5" data-testid="completed-order-detail">
      <Link to={completedOnly ? "/completed-orders" : "/purchase-invoices"} className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="h-4 w-4" />{completedOnly ? "დასრულებული შეკვეთები" : "ინვოისები"}</Link>
      <DataState state={state}>
        {!order ? <p className="py-8 text-sm text-muted-foreground">შეკვეთა ვერ მოიძებნა.</p> : (
          <>
            <header className="flex flex-wrap items-start justify-between gap-3"><div><h1 className="text-2xl font-bold">{order.order_no}</h1><p className="mt-1 text-sm text-muted-foreground">{order.supplier_name}</p></div><p className="text-xl font-semibold">{money(order.total)}</p></header>
            <dl className="grid gap-4 border-y border-border py-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
              <div><dt className="text-muted-foreground">შეკვეთის თარიღი</dt><dd>{dateLabel(order.created_at)}</dd></div>
              <div><dt className="text-muted-foreground">დასრულების თარიღი</dt><dd>{dateLabel(order.delivered_at)}</dd></div>
              <div><dt className="text-muted-foreground">გადახდის სტატუსი</dt><dd>{paymentLabels[order.payment_status] || order.payment_status}</dd></div>
              <div><dt className="text-muted-foreground">გადახდილი / დარჩენილი</dt><dd>{money(order.amount_paid)} / {money(order.balance_due)}</dd></div>
              <div><dt className="text-muted-foreground">გადახდის ვადა</dt><dd>{dateLabel(order.payment_due_date)}</dd></div>
              <div><dt className="text-muted-foreground">გადახდის მეთოდი</dt><dd>{order.payment_method || "—"}</dd></div>
              <div><dt className="text-muted-foreground">გადახდის დანიშნულება</dt><dd className="[overflow-wrap:anywhere]">{order.payment_reference || "—"}</dd></div>
              <div><dt className="text-muted-foreground">მიწოდების მისამართი</dt><dd className="[overflow-wrap:anywhere]">{order.delivery_address || "—"}</dd></div>
              <div><dt className="text-muted-foreground">მიწოდების დრო</dt><dd>{order.delivery_window || "—"}</dd></div>
              <div><dt className="text-muted-foreground">შენიშვნა</dt><dd className="[overflow-wrap:anywhere]">{order.notes || "—"}</dd></div>
            </dl>
            <section><h2 className="mb-3 font-semibold">პროდუქტები</h2><OrderItems order={order} /></section>
            {!order.external_order && order.status !== "Cancelled" && <div className="flex flex-wrap gap-2"><Link to={`/purchase-invoices?search=${encodeURIComponent(order.order_no)}`} className="inline-flex items-center text-sm text-primary hover:underline">ინვოისი {order.order_no}</Link><Button variant="outline" onClick={() => downloadInvoice(order)}><FileDown className="h-4 w-4" />ინვოისის ჩამოტვირთვა</Button></div>}
          </>
        )}
      </DataState>
    </div>
  );
}

const dateInput = (date) => format(date, "yyyy-MM-dd");

function presetRange(preset) {
  const today = parseISO(purchaseDay(new Date()));
  if (preset === "today") return [dateInput(today), dateInput(today)];
  if (preset === "7") return [dateInput(subDays(today, 6)), dateInput(today)];
  if (preset === "30") return [dateInput(subDays(today, 29)), dateInput(today)];
  if (preset === "month") return [dateInput(startOfMonth(today)), dateInput(today)];
  if (preset === "previous") {
    const previous = subMonths(today, 1);
    return [dateInput(startOfMonth(previous)), dateInput(endOfMonth(previous))];
  }
  if (preset === "year") return [dateInput(startOfYear(today)), dateInput(today)];
  return ["", ""];
}

function AnalyticsChart({ title, data, currency = false }) {
  return (
    <section className="min-w-0 border-t border-border pt-4">
      <h2 className="mb-3 text-sm font-semibold">{title}</h2>
      {data.length ? <div className="h-56 w-full"><ResponsiveContainer width="100%" height="100%"><BarChart data={data} margin={{ left: 0, right: 8 }}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="date" tick={{ fontSize: 10 }} minTickGap={20} /><YAxis tick={{ fontSize: 10 }} width={48} /><Tooltip formatter={(value) => currency ? money(value) : value} /><Bar dataKey="value" fill="#15806d" radius={[3, 3, 0, 0]} /></BarChart></ResponsiveContainer></div> : <p className="py-8 text-sm text-muted-foreground">მონაცემები არ არის.</p>}
    </section>
  );
}

export function PurchaseAnalytics() {
  const state = usePurchaseOrders();
  const [preset, setPreset] = useState("30");
  const [[from, to], setRange] = useState(() => presetRange("30"));
  const [productId, setProductId] = useState("");
  const stats = useMemo(() => calculatePurchaseAnalytics(state.orders, from, to), [state.orders, from, to]);
  const product = stats.products.find((item) => item.id === productId);
  const rangeInvalid = from && to && from > to;
  return (
    <div className="space-y-6" data-testid="purchase-analytics-page">
      <h1 className="text-2xl font-bold">შესყიდვების ანალიტიკა</h1>
      <div className="flex flex-wrap items-end gap-3">
        <label className="space-y-1 text-sm"><span>პერიოდი</span><select className="block h-9 rounded-md border border-input bg-background px-3" value={preset} onChange={(event) => { setPreset(event.target.value); if (event.target.value !== "custom") setRange(presetRange(event.target.value)); }}><option value="today">დღეს</option><option value="7">ბოლო 7 დღე</option><option value="30">ბოლო 30 დღე</option><option value="month">მიმდინარე თვე</option><option value="previous">წინა თვე</option><option value="year">მიმდინარე წელი</option><option value="custom">თარიღების არჩევა</option></select></label>
        {preset === "custom" && <><label className="space-y-1 text-sm"><span>დან</span><Input type="date" value={from} onChange={(event) => setRange([event.target.value, to])} /></label><label className="space-y-1 text-sm"><span>მდე</span><Input type="date" value={to} onChange={(event) => setRange([from, event.target.value])} /></label></>}
      </div>
      {rangeInvalid ? <p role="alert" className="text-sm text-destructive">დაწყების თარიღი დასრულების თარიღზე გვიანია.</p> : <DataState state={state}>
        <div className="grid gap-3 sm:grid-cols-3">
          {[{ label: "სულ შეკვეთები", value: stats.orderCount }, { label: "დასრულებული", value: stats.completedCount }, { label: "გადახდილი თანხა", value: money(stats.spent) }].map((item) => <div key={item.label} className="border-l-2 border-primary pl-3"><p className="text-sm text-muted-foreground">{item.label}</p><p className="mt-1 text-2xl font-semibold">{item.value}</p></div>)}
        </div>
        {stats.undatedPayments > 0 && <p className="text-sm text-amber-600" role="status">ზოგიერთ გადახდას თარიღი არ აქვს და გადახდების სტატისტიკაში არ შედის.</p>}
        <div className="grid gap-x-6 gap-y-4 lg:grid-cols-2">
          <AnalyticsChart title="შეკვეთები თვეების მიხედვით" data={stats.ordersByMonth} />
          <AnalyticsChart title="გადახდები დღეების მიხედვით" data={stats.paymentsByDay} currency />
          <AnalyticsChart title="გადახდები კვირების მიხედვით" data={stats.paymentsByWeek} currency />
          <AnalyticsChart title="გადახდები თვეების მიხედვით" data={stats.paymentsByMonth} currency />
        </div>
        <div className="grid gap-6 border-t border-border pt-4 lg:grid-cols-2">
          <section><h2 className="mb-3 font-semibold">ყველაზე ხშირად შეძენილი პროდუქტები</h2><div className="space-y-2">{stats.products.map((item) => <button key={item.id} type="button" className="flex w-full justify-between gap-3 border-b border-border py-2 text-left text-sm hover:text-primary" onClick={() => setProductId(item.id)}><span className="min-w-0 [overflow-wrap:anywhere]">{item.name}</span><span className="shrink-0 font-mono">{item.quantity}</span></button>)}{!stats.products.length && <p className="text-sm text-muted-foreground">მონაცემები არ არის.</p>}</div></section>
          <section><h2 className="mb-3 font-semibold">აქტიური დისტრიბუტორები</h2><div className="space-y-2">{stats.suppliers.map((supplier) => <div key={supplier.id} className="flex justify-between gap-3 border-b border-border py-2 text-sm"><span>{supplier.name}</span><span className="font-mono">{supplier.orders}</span></div>)}{!stats.suppliers.length && <p className="text-sm text-muted-foreground">მონაცემები არ არის.</p>}</div></section>
        </div>
        {product && <section className="border-t border-border pt-4"><h2 className="mb-3 font-semibold">{product.name} · შესყიდვების ისტორია</h2><div className="overflow-x-auto"><table className="w-full min-w-[560px] text-left text-sm"><thead className="text-muted-foreground"><tr><th className="py-2">შეკვეთა</th><th>თარიღი</th><th>დისტრიბუტორი</th><th>რაოდენობა</th><th>ერთეულის ფასი</th></tr></thead><tbody>{product.history.map((entry, index) => <tr key={`${entry.orderId}-${index}`} className="border-t border-border"><td className="py-2"><Link className="text-primary hover:underline" to={`/completed-orders/${encodeURIComponent(entry.orderId)}`}>{entry.orderNo}</Link></td><td>{dateLabel(entry.date)}</td><td>{entry.supplier}</td><td>{entry.quantity}</td><td>{money(entry.price)}</td></tr>)}</tbody></table></div></section>}
      </DataState>}
    </div>
  );
}

export function PurchaseInvoices() {
  const state = usePurchaseOrders();
  const [searchParams] = useSearchParams();
  const [status, setStatus] = useState("all");
  const [supplier, setSupplier] = useState("all");
  const [search, setSearch] = useState(() => searchParams.get("search") || "");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [minimum, setMinimum] = useState("");
  const [maximum, setMaximum] = useState("");
  const [viewer, setViewer] = useState(null);
  const [opening, setOpening] = useState("");
  const iframe = useRef(null);
  useEffect(() => () => { if (viewer?.url) URL.revokeObjectURL(viewer.url); }, [viewer]);
  const invoiceOrders = state.orders.filter((order) => !order.external_order && order.status !== "Cancelled");
  const suppliers = [...new Map(invoiceOrders.map((order) => [order.supplier_id, order.supplier_name])).entries()];
  const filtered = invoiceOrders.filter((order) => {
    const day = purchaseDay(order.created_at);
    const partial = Number(order.amount_paid || 0) > 0 && Number(order.balance_due || 0) > 0;
    return (status === "all" || (status === "partially_paid" ? partial : order.payment_status === status))
      && (supplier === "all" || order.supplier_id === supplier)
      && (!search || String(order.order_no || "").toLowerCase().includes(search.toLowerCase().trim()))
      && (!from || day >= from) && (!to || day <= to)
      && (minimum === "" || Number(order.total) >= Number(minimum))
      && (maximum === "" || Number(order.total) <= Number(maximum));
  });
  const openInvoice = async (order) => {
    setOpening(order.id);
    try {
      const { data } = await api.get(`/orders/${encodeURIComponent(order.id)}/invoice.pdf`, { responseType: "blob" });
      setViewer({ order, url: URL.createObjectURL(new Blob([data], { type: "application/pdf" })) });
    } catch (error) {
      toast.error(formatApiError(error.response?.data?.detail) || "ინვოისის გახსნა ვერ მოხერხდა");
    } finally { setOpening(""); }
  };
  return (
    <div className="space-y-5" data-testid="purchase-invoices-page">
      <h1 className="text-2xl font-bold">ინვოისები</h1>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="space-y-1 text-sm"><span>სტატუსი</span><select className="h-9 w-full rounded-md border border-input bg-background px-3" value={status} onChange={(event) => setStatus(event.target.value)}><option value="all">ყველა</option><option value="paid">გადახდილი</option><option value="unpaid">გადაუხდელი</option><option value="overdue">ვადაგადაცილებული</option><option value="partially_paid">ნაწილობრივ გადახდილი</option></select></label>
        <label className="space-y-1 text-sm"><span>დისტრიბუტორი</span><select className="h-9 w-full rounded-md border border-input bg-background px-3" value={supplier} onChange={(event) => setSupplier(event.target.value)}><option value="all">ყველა</option>{suppliers.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
        <label className="space-y-1 text-sm"><span>ინვოისის ნომერი</span><Input value={search} onChange={(event) => setSearch(event.target.value)} /></label>
        <div className="grid grid-cols-2 gap-2"><label className="space-y-1 text-sm"><span>თანხა მინ.</span><Input type="number" min="0" value={minimum} onChange={(event) => setMinimum(event.target.value)} /></label><label className="space-y-1 text-sm"><span>თანხა მაქს.</span><Input type="number" min="0" value={maximum} onChange={(event) => setMaximum(event.target.value)} /></label></div>
        <label className="space-y-1 text-sm"><span>თარიღიდან</span><Input type="date" value={from} onChange={(event) => setFrom(event.target.value)} /></label>
        <label className="space-y-1 text-sm"><span>თარიღამდე</span><Input type="date" value={to} onChange={(event) => setTo(event.target.value)} /></label>
      </div>
      {(from && to && from > to) || (minimum !== "" && maximum !== "" && Number(minimum) > Number(maximum)) ? <p role="alert" className="text-sm text-destructive">ფილტრის დიაპაზონი არასწორია.</p> : <DataState state={state}>
        <div className="overflow-x-auto"><table className="w-full min-w-[960px] text-left text-sm"><thead className="text-muted-foreground"><tr><th className="p-2">ინვოისი</th><th>შექმნა</th><th>გადახდის ვადა</th><th>დისტრიბუტორი</th><th>თანხა</th><th>სტატუსი</th><th>შეკვეთა</th><th>მოქმედებები</th></tr></thead><tbody>
          {filtered.map((order) => <tr key={order.id} className="border-t border-border"><td className="p-2 font-semibold">{order.order_no}</td><td>{dateLabel(order.created_at)}</td><td>{dateLabel(order.payment_due_date)}</td><td>{order.supplier_name}</td><td>{money(order.total)}</td><td>{paymentLabels[order.payment_status] || order.payment_status}</td><td><Link className="text-primary hover:underline" to={`/purchase-orders/${encodeURIComponent(order.id)}`}>{order.order_no}</Link></td><td><div className="flex gap-1"><Button variant="ghost" size="icon" title="ნახვა და ბეჭდვა" aria-label="ინვოისის ნახვა" disabled={opening === order.id} onClick={() => openInvoice(order)}><Eye /></Button><Button variant="ghost" size="icon" title="PDF ჩამოტვირთვა" aria-label="ინვოისის ჩამოტვირთვა" onClick={() => downloadInvoice(order)}><FileDown /></Button></div></td></tr>)}
          {!filtered.length && <tr><td colSpan={8} className="py-8 text-center text-muted-foreground">ინვოისები არ არის.</td></tr>}
        </tbody></table></div>
      </DataState>}
      <Dialog open={Boolean(viewer)} onOpenChange={(open) => { if (!open) setViewer(null); }}><DialogContent className="max-w-4xl" aria-describedby={undefined}><DialogTitle>ინვოისი {viewer?.order.order_no}</DialogTitle><iframe ref={iframe} title="ინვოისი" src={viewer?.url} className="h-[65vh] w-full border border-border" /><Button variant="outline" onClick={() => { try { iframe.current?.contentWindow?.focus(); iframe.current?.contentWindow?.print(); } catch { toast.error("ბეჭდვა ვერ მოხერხდა"); } }}><Printer />ბეჭდვა</Button></DialogContent></Dialog>
    </div>
  );
}