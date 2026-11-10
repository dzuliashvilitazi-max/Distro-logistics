import { useState } from "react";
import { Info, Landmark } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DateRangeFields, ExportButtons, Field, InvoiceActions, InvoiceDialog, Pager, Stat, StatusBadge, selectClass,
  useInvoiceViewer, useReport,
} from "@/components/ReportBits";
import { COMMISSION_LABELS, PAYMENT_LABELS, dateLabel, money, presetRange } from "@/lib/reports";

const PAGE_SIZE = 25;
const EMPTY = { preset: "30", from: presetRange("30")[0], to: presetRange("30")[1], store: "", status: "all", invoiceNo: "", min: "", max: "" };
const KIND_LABELS = { customer_payment: "მაღაზიის გადახდა", payout: "სისტემაში ჩაწერილი ანგარიშსწორება", commission_invoice: "საკომისიო ინვოისი" };
const KIND_STYLES = { customer_payment: "text-sky-500", payout: "text-emerald-500", commission_invoice: "text-amber-500" };

const agreementText = (a) => `${a.fee_type === "percent" ? `${a.fee_value}%` : a.fee_type === "fixed" ? money(a.fee_value) : "—"} · ${a.orders} შეკვ.`;

export default function SupplierFinanceCenter() {
  const [filters, setFilters] = useState(EMPTY);
  const [page, setPage] = useState(0);
  const viewer = useInvoiceViewer();
  const params = {
    status: filters.status, start_date: filters.from, end_date: filters.to, store_id: filters.store,
    invoice_no: filters.invoiceNo.trim(), min_amount: filters.min, max_amount: filters.max,
  };
  const { data, loading, error } = useReport("/supplier/reports/finance", { ...params, limit: PAGE_SIZE, offset: page * PAGE_SIZE });
  const update = (patch) => { setFilters((current) => ({ ...current, ...patch })); setPage(0); };
  const invalid = (filters.from && filters.to && filters.from > filters.to)
    || (filters.min !== "" && filters.max !== "" && Number(filters.min) > Number(filters.max));
  const s = data?.summary;

  return (
    <div className="space-y-6" data-testid="finance-center">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2"><Landmark className="h-6 w-6 text-primary" /><h1 className="text-2xl font-bold tracking-tight sm:text-3xl">ინვოისები და ფინანსები</h1></div>
          <p className="mt-1 text-sm text-muted-foreground">გაყიდვები, მაღაზიების გადახდები, პლატფორმის საკომისიო და ანგარიშსწორება ნაჩვენებია ერთმანეთისგან განცალკევებით.</p>
        </div>
        <ExportButtons path="/supplier/reports/finance/export" params={params} name="invoices-finance" />
      </header>

      <section className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4" aria-label="ფილტრები">
        <DateRangeFields preset={filters.preset} from={filters.from} to={filters.to} onChange={(value) => update(value)} />
        <Field label="სტატუსი"><select className={selectClass} value={filters.status} onChange={(e) => update({ status: e.target.value })} data-testid="finance-status"><option value="all">ყველა</option>{Object.entries(PAYMENT_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
        <Field label="მაღაზია"><select className={selectClass} value={filters.store} onChange={(e) => update({ store: e.target.value })} data-testid="finance-store"><option value="">ყველა</option>{(data?.stores || []).map((st) => <option key={st.id} value={st.id}>{st.name}</option>)}</select></Field>
        <Field label="ინვოისის ნომერი"><Input value={filters.invoiceNo} onChange={(e) => update({ invoiceNo: e.target.value })} data-testid="finance-invoice-no" /></Field>
        <Field label="თანხა მინ. (₾)"><Input type="number" min="0" value={filters.min} onChange={(e) => update({ min: e.target.value })} /></Field>
        <Field label="თანხა მაქს. (₾)"><Input type="number" min="0" value={filters.max} onChange={(e) => update({ max: e.target.value })} /></Field>
        <div className="flex items-end"><Button variant="ghost" size="sm" onClick={() => { setFilters(EMPTY); setPage(0); }}>ფილტრების გასუფთავება</Button></div>
      </section>

      {invalid && <p role="alert" className="text-sm text-destructive">ფილტრის დიაპაზონი არასწორია.</p>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {loading && !data && <p className="py-10 text-center text-sm text-muted-foreground" aria-busy="true">იტვირთება...</p>}

      {s && (
        <section className="space-y-3" data-testid="finance-summary">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="დასრულებული გაყიდვები" value={money(s.completed_sales)} hint="მიწოდებული შეკვეთები, დაბრუნებების გარეშე" />
            <Stat label="Distro საკომისიო" value={money(s.commission)} hint={s.commission_percent === null ? "—" : `ფაქტობრივი საშუალო: ${s.commission_percent}%`} />
            <Stat label="ნეტო საკომისიოს შემდეგ" value={money(s.net_after_commission)} />
            <Stat label="ინვოისები (ფილტრით)" value={`${money(s.invoiced_total)} · ${s.invoice_count}`} />
            <Stat label="მაღაზიებისგან მიღებული გადახდები" value={money(s.paid)} />
            <Stat label="გადაუხდელი ნაშთი" value={money(s.unpaid)} />
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded-xl border border-border bg-card p-4 text-sm">
              <h2 className="mb-2 font-semibold">საკომისიოს პირობები (დაფიქსირებული შეკვეთებზე)</h2>
              {s.commission_agreements.length ? <ul className="space-y-1">{s.commission_agreements.map((a, i) => <li key={i} className="flex justify-between"><span className="text-muted-foreground">{a.fee_type === "percent" ? "პროცენტი" : "ფიქსირებული"}</span><span className="font-mono">{agreementText(a)}</span></li>)}</ul> : <p className="text-muted-foreground">საკომისიოიანი შეკვეთები არ არის.</p>}
            </div>
            <div className="rounded-xl border border-border bg-card p-4 text-sm">
              <h2 className="mb-2 font-semibold">საკომისიოს მდგომარეობა</h2>
              <ul className="space-y-1">{Object.entries(s.commission_by_state).map(([k, v]) => <li key={k} className="flex justify-between gap-3"><span className="text-muted-foreground">{COMMISSION_LABELS[k]}</span><span className="font-mono">{money(v)}</span></li>)}</ul>
            </div>
          </div>
        </section>
      )}

      <section className="rounded-xl border border-border bg-card p-4">
        <h2 className="mb-3 text-sm font-semibold">ინვოისები</h2>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-left text-sm" data-testid="finance-invoices">
            <thead className="text-xs text-muted-foreground"><tr><th className="py-2">ინვოისი</th><th>შეკვეთა</th><th>მაღაზია</th><th>შექმნა</th><th>გადახდის ვადა</th><th className="text-right">თანხა</th><th className="text-right">გადახდილი</th><th className="text-right">ნაშთი</th><th>სტატუსი</th><th /></tr></thead>
            <tbody>
              {data?.items.map((row) => (
                <tr key={row.id} className="border-t border-border" data-testid={`finance-row-${row.id}`}>
                  <td className="py-2 font-mono font-semibold">{row.invoice_no}</td><td className="font-mono">{row.order_no}</td><td className="max-w-[160px] truncate">{row.store_name}</td>
                  <td>{dateLabel(row.created_at)}</td><td>{dateLabel(row.due_date)}</td>
                  <td className="text-right font-mono">{money(row.total)}</td><td className="text-right font-mono">{money(row.paid)}</td><td className="text-right font-mono">{money(row.balance)}</td>
                  <td><StatusBadge status={row.payment_status} /></td>
                  <td><InvoiceActions order={{ id: row.id, order_no: row.order_no }} viewer={viewer} /></td>
                </tr>
              ))}
              {data && !data.items.length && <tr><td colSpan={10} className="py-8 text-center text-muted-foreground">ინვოისები ვერ მოიძებნა.</td></tr>}
            </tbody>
          </table>
        </div>
        <Pager page={page} pageSize={PAGE_SIZE} total={data?.total || 0} onPage={setPage} />
      </section>

      <section className="rounded-xl border border-border bg-card p-4" data-testid="settlement-history">
        <h2 className="mb-1 text-sm font-semibold">ანგარიშსწორების ისტორია</h2>
        <p className="mb-3 flex items-start gap-1.5 text-xs text-muted-foreground"><Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />ჩანაწერები აღებულია სისტემიდან. „ანგარიშსწორება“ ნაჩვენებია მხოლოდ როცა ბექენდმა დააფიქსირა; ბანკში თანხის ჩარიცხვის დადასტურებას ეს ცხრილი არ ანაცვლებს.</p>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead className="text-xs text-muted-foreground"><tr><th className="py-2">თარიღი</th><th>ტიპი</th><th>შეკვეთა / ინვოისი</th><th>მაღაზია</th><th className="text-right">თანხა</th><th>მეთოდი</th><th>სტატუსი</th></tr></thead>
            <tbody>
              {(data?.settlements || []).slice(0, 100).map((e, i) => (
                <tr key={i} className="border-t border-border">
                  <td className="py-1.5">{dateLabel(e.at)}</td><td className={KIND_STYLES[e.kind]}>{KIND_LABELS[e.kind]}</td><td className="font-mono">{e.order_no}</td>
                  <td className="max-w-[160px] truncate">{e.store_name || "—"}</td><td className="text-right font-mono">{money(e.amount)}</td><td>{e.method || "—"}</td><td>{e.status || "—"}</td>
                </tr>
              ))}
              {data && !data.settlements.length && <tr><td colSpan={7} className="py-6 text-center text-muted-foreground">ჩანაწერები არ არის.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
      <InvoiceDialog viewer={viewer.viewer} onClose={() => viewer.setViewer(null)} />
    </div>
  );
}
