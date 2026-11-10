import { useEffect, useState } from "react";
import { CheckCircle2, Eye } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  DateRangeFields, ExportButtons, Field, InvoiceActions, InvoiceDialog, Pager, Stat, StatusBadge, selectClass,
  useInvoiceViewer, useReport,
} from "@/components/ReportBits";
import { COMMISSION_LABELS, PAYMENT_LABELS, dateLabel, money, presetRange } from "@/lib/reports";

const PAGE_SIZE = 25;
const EMPTY = { preset: "30", from: presetRange("30")[0], to: presetRange("30")[1], store: "", product: "", orderNo: "", payment: "all" };

function commissionText(order) {
  const agreement = order.commission_type === "percent" ? `${order.commission_value}%` : order.commission_type === "fixed" ? money(order.commission_value) : "";
  return agreement ? `${money(order.commission)} (${agreement})` : money(order.commission);
}

function OrderDetails({ order, viewer, onClose }) {
  return (
    <Dialog open={Boolean(order)} onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        {order && (
          <>
            <DialogHeader>
              <DialogTitle>შეკვეთა {order.order_no}</DialogTitle>
              <DialogDescription>{order.store_name}</DialogDescription>
            </DialogHeader>
            <dl className="grid gap-3 text-sm sm:grid-cols-2">
              <div><dt className="text-muted-foreground">შეკვეთის თარიღი</dt><dd>{dateLabel(order.created_at)}</dd></div>
              <div><dt className="text-muted-foreground">დასრულების თარიღი</dt><dd>{dateLabel(order.completed_at)}</dd></div>
              <div><dt className="text-muted-foreground">გადახდის სტატუსი</dt><dd><StatusBadge status={order.payment_status} /></dd></div>
              <div><dt className="text-muted-foreground">გადახდილი / ნაშთი</dt><dd>{money(order.amount_paid)} / {money(order.balance_due)}</dd></div>
              <div><dt className="text-muted-foreground">Distro საკომისიო</dt><dd>{commissionText(order)}</dd></div>
              <div><dt className="text-muted-foreground">საკომისიოს მდგომარეობა</dt><dd>{COMMISSION_LABELS[order.commission_state]}</dd></div>
              <div><dt className="text-muted-foreground">ნეტო საკომისიოს შემდეგ</dt><dd className="font-semibold">{money(order.net_after_commission)}</dd></div>
              <div className="sm:col-span-2"><dt className="text-muted-foreground">მისამართი</dt><dd className="[overflow-wrap:anywhere]">{order.delivery_address || "—"}</dd></div>
              {order.notes && <div className="sm:col-span-2"><dt className="text-muted-foreground">შენიშვნა</dt><dd className="[overflow-wrap:anywhere]">{order.notes}</dd></div>}
            </dl>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[420px] text-left text-sm">
                <thead className="text-xs text-muted-foreground"><tr><th className="py-1">პროდუქტი</th><th>რაოდ.</th><th>ფასი</th><th className="text-right">ჯამი</th></tr></thead>
                <tbody>
                  {order.items.map((item, index) => (
                    <tr key={`${item.product_id}-${index}`} className="border-t border-border">
                      <td className="py-1.5 [overflow-wrap:anywhere]">{item.name}</td>
                      <td>{item.quantity}{item.returned_quantity ? ` (−${item.returned_quantity})` : ""}</td>
                      <td>{item.list_price > item.unit_price && <s className="mr-1 text-muted-foreground">{money(item.list_price)}</s>}{money(item.unit_price)}</td>
                      <td className="text-right">{money(item.line_total)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot><tr className="border-t border-border font-semibold"><td colSpan={3} className="py-1.5">ჯამი</td><td className="text-right">{money(order.net_total)}</td></tr></tfoot>
              </table>
            </div>
            <div className="flex items-center justify-between gap-2"><span className="text-sm text-muted-foreground">ინვოისი {order.invoice_no}</span><InvoiceActions order={order} viewer={viewer} /></div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

export default function SupplierCompletedOrders() {
  const [filters, setFilters] = useState(EMPTY);
  const [page, setPage] = useState(0);
  const [details, setDetails] = useState(null);
  const viewer = useInvoiceViewer();
  const params = {
    start_date: filters.from, end_date: filters.to, store_id: filters.store, product: filters.product,
    order_no: filters.orderNo.trim(), payment_status: filters.payment,
  };
  const { data, loading, error } = useReport("/supplier/reports/completed-orders", { ...params, limit: PAGE_SIZE, offset: page * PAGE_SIZE });
  const update = (patch) => { setFilters((current) => ({ ...current, ...patch })); setPage(0); };
  useEffect(() => { setPage(0); }, [filters.preset]);
  const invalidRange = filters.from && filters.to && filters.from > filters.to;
  const summary = data?.summary;

  return (
    <div className="space-y-6" data-testid="completed-orders-report">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2"><CheckCircle2 className="h-6 w-6 text-primary" /><h1 className="text-2xl font-bold tracking-tight sm:text-3xl">დასრულებული შეკვეთები</h1></div>
          <p className="mt-1 text-sm text-muted-foreground">მხოლოდ მიწოდებული შეკვეთები. საკომისიო აღებულია შეკვეთის დროს დაფიქსირებული პირობებიდან.</p>
        </div>
        <ExportButtons path="/supplier/reports/completed-orders/export" params={params} name="completed-orders" />
      </header>

      <section className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4" aria-label="ფილტრები">
        <DateRangeFields preset={filters.preset} from={filters.from} to={filters.to} onChange={(value) => update(value)} />
        <Field label="მაღაზია"><select className={selectClass} value={filters.store} onChange={(e) => update({ store: e.target.value })} data-testid="filter-store"><option value="">ყველა</option>{(data?.stores || []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></Field>
        <Field label="პროდუქტი"><select className={selectClass} value={filters.product} onChange={(e) => update({ product: e.target.value })} data-testid="filter-product"><option value="">ყველა</option>{(data?.products || []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
        <Field label="შეკვეთის ნომერი"><Input value={filters.orderNo} onChange={(e) => update({ orderNo: e.target.value })} placeholder="ORD-..." data-testid="filter-order-no" /></Field>
        <Field label="გადახდის სტატუსი"><select className={selectClass} value={filters.payment} onChange={(e) => update({ payment: e.target.value })} data-testid="filter-payment"><option value="all">ყველა</option>{Object.entries(PAYMENT_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
        <div className="flex items-end"><Button variant="ghost" size="sm" onClick={() => { setFilters(EMPTY); setPage(0); }}>ფილტრების გასუფთავება</Button></div>
      </section>

      {invalidRange && <p role="alert" className="text-sm text-destructive">დაწყების თარიღი დასრულების თარიღზე გვიანია.</p>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}

      {summary && (
        <section className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          <Stat label="შეკვეთები" value={summary.count} />
          <Stat label="გაყიდვები" value={money(summary.total)} />
          <Stat label="Distro საკომისიო" value={money(summary.commission)} />
          <Stat label="ნეტო საკომისიოს შემდეგ" value={money(summary.net_after_commission)} />
          <Stat label="გადაუხდელი ნაშთი" value={money(summary.outstanding)} />
        </section>
      )}

      {loading && !data ? <p className="py-10 text-center text-sm text-muted-foreground" aria-busy="true">იტვირთება...</p> : (
        <div className="space-y-3">
          {data?.items.length === 0 && <p className="rounded-xl border border-dashed border-border py-14 text-center text-sm text-muted-foreground">დასრულებული შეკვეთები ვერ მოიძებნა.</p>}
          {data?.items.map((order) => (
            <article key={order.id} className="rounded-xl border border-border bg-card p-4" data-testid={`completed-row-${order.id}`}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-mono text-sm font-bold text-primary">{order.order_no}</p>
                  <p className="font-medium [overflow-wrap:anywhere]">{order.store_name}</p>
                  <p className="text-xs text-muted-foreground">შეკვეთა: {dateLabel(order.created_at)} · დასრულება: {dateLabel(order.completed_at)}</p>
                </div>
                <div className="text-right"><p className="text-xl font-extrabold">{money(order.net_total)}</p><StatusBadge status={order.payment_status} /></div>
              </div>
              <ul className="my-3 space-y-1 border-y border-border py-2 text-sm">
                {order.items.map((item, index) => (
                  <li key={`${item.product_id}-${index}`} className="flex justify-between gap-3"><span className="min-w-0 truncate">{item.name}</span><span className="shrink-0 font-mono text-muted-foreground">{item.quantity} × {money(item.unit_price)}</span></li>
                ))}
              </ul>
              <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
                <div className="space-y-0.5">
                  <p><span className="text-muted-foreground">საკომისიო: </span>{commissionText(order)}</p>
                  <p><span className="text-muted-foreground">ნეტო: </span><strong>{money(order.net_after_commission)}</strong></p>
                </div>
                <div className="flex items-center gap-1">
                  <Button size="sm" variant="outline" onClick={() => setDetails(order)} data-testid={`open-details-${order.id}`}><Eye className="mr-1.5 h-4 w-4" />დეტალები</Button>
                  <InvoiceActions order={order} viewer={viewer} />
                </div>
              </div>
            </article>
          ))}
          <Pager page={page} pageSize={PAGE_SIZE} total={data?.total || 0} onPage={setPage} />
        </div>
      )}
      <OrderDetails order={details} viewer={viewer} onClose={() => setDetails(null)} />
      <InvoiceDialog viewer={viewer.viewer} onClose={() => viewer.setViewer(null)} />
    </div>
  );
}
