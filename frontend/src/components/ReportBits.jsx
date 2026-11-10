import { useEffect, useRef, useState } from "react";
import { Download, FileSpreadsheet, FileText, Printer } from "lucide-react";
import { toast } from "sonner";
import { api, formatApiError } from "@/lib/api";
import { PAYMENT_LABELS, PAYMENT_STYLES, PRESETS, cleanParams, downloadReport, fetchInvoiceBlob, presetRange } from "@/lib/reports";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

// Loads a report whenever its parameters change; stale responses are ignored.
export function useReport(path, params) {
  const [state, setState] = useState({ data: null, loading: true, error: "" });
  const key = JSON.stringify(cleanParams(params));
  useEffect(() => {
    let active = true;
    setState((current) => ({ ...current, loading: true, error: "" }));
    api.get(path, { params: cleanParams(params) })
      .then(({ data }) => { if (active) setState({ data, loading: false, error: "" }); })
      .catch((error) => { if (active) setState((current) => ({ ...current, loading: false, error: formatApiError(error.response?.data?.detail) || "მონაცემების ჩატვირთვა ვერ მოხერხდა" })); });
    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, key]);
  return state;
}

export function Field({ label, children }) {
  return <label className="block min-w-0 space-y-1 text-xs text-muted-foreground"><span>{label}</span>{children}</label>;
}

export const selectClass = "h-10 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground";

export function Stat({ label, value, hint, change }) {
  return (
    <div className="min-w-0 rounded-xl border border-border bg-card p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 break-words text-xl font-bold sm:text-2xl">{value}</p>
      {change !== undefined && change !== null && (
        <p className={cn("mt-0.5 text-xs font-medium", change >= 0 ? "text-emerald-500" : "text-rose-500")}>
          {change >= 0 ? "▲" : "▼"} {Math.abs(change)}% წინა პერიოდთან
        </p>
      )}
      {hint && <p className="mt-1 text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function StatusBadge({ status }) {
  return <span className={cn("inline-block whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-semibold", PAYMENT_STYLES[status])}>{PAYMENT_LABELS[status] || status || "—"}</span>;
}

export function DateRangeFields({ preset, from, to, onChange }) {
  const set = (nextPreset, nextFrom = from, nextTo = to) => onChange({ preset: nextPreset, from: nextFrom, to: nextTo });
  return (
    <>
      <Field label="პერიოდი">
        <select className={selectClass} value={preset} data-testid="report-preset"
          onChange={(event) => { const value = event.target.value; const [a, b] = value === "custom" ? [from, to] : presetRange(value); set(value, a, b); }}>
          {PRESETS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </Field>
      {preset === "custom" && (
        <>
          <Field label="დან"><Input type="date" value={from} onChange={(event) => set("custom", event.target.value, to)} data-testid="report-from" /></Field>
          <Field label="მდე"><Input type="date" value={to} onChange={(event) => set("custom", from, event.target.value)} data-testid="report-to" /></Field>
        </>
      )}
    </>
  );
}

export function ExportButtons({ path, params, name }) {
  const [busy, setBusy] = useState("");
  const run = async (fmt) => {
    setBusy(fmt);
    await downloadReport(path, params, fmt, name);
    setBusy("");
  };
  return (
    <div className="flex flex-wrap gap-2">
      <Button type="button" variant="outline" size="sm" disabled={!!busy} onClick={() => run("xlsx")} data-testid="export-xlsx"><FileSpreadsheet className="mr-1.5 h-4 w-4" />Excel</Button>
      <Button type="button" variant="outline" size="sm" disabled={!!busy} onClick={() => run("csv")} data-testid="export-csv"><Download className="mr-1.5 h-4 w-4" />CSV</Button>
    </div>
  );
}

export function useInvoiceViewer() {
  const [viewer, setViewer] = useState(null);
  const [loading, setLoading] = useState("");
  useEffect(() => () => { if (viewer?.url) URL.revokeObjectURL(viewer.url); }, [viewer]);
  const open = async (order) => {
    setLoading(order.id);
    try {
      setViewer({ order, url: URL.createObjectURL(await fetchInvoiceBlob(order.id)) });
    } catch (error) {
      toast.error(formatApiError(error.response?.data?.detail) || "ინვოისის გახსნა ვერ მოხერხდა");
    } finally {
      setLoading("");
    }
  };
  const download = async (order) => {
    try {
      const url = URL.createObjectURL(await fetchInvoiceBlob(order.id));
      const link = document.createElement("a");
      link.href = url;
      link.download = `${order.order_no}-invoice.pdf`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch (error) {
      toast.error(formatApiError(error.response?.data?.detail) || "ინვოისის ჩამოტვირთვა ვერ მოხერხდა");
    }
  };
  return { viewer, setViewer, loading, open, download };
}

export function InvoiceDialog({ viewer, onClose }) {
  const frame = useRef(null);
  return (
    <Dialog open={Boolean(viewer)} onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="max-w-4xl" aria-describedby={undefined}>
        <DialogTitle>ინვოისი {viewer?.order.order_no}</DialogTitle>
        <iframe ref={frame} title="ინვოისი" src={viewer?.url} className="h-[60vh] w-full rounded border border-border bg-white" />
        <Button variant="outline" onClick={() => { try { frame.current?.contentWindow?.focus(); frame.current?.contentWindow?.print(); } catch { toast.error("ბეჭდვა ვერ მოხერხდა"); } }}><Printer className="mr-2 h-4 w-4" />ბეჭდვა</Button>
      </DialogContent>
    </Dialog>
  );
}

export function InvoiceActions({ order, viewer }) {
  return (
    <div className="flex gap-1">
      <Button variant="ghost" size="icon" title="ნახვა და ბეჭდვა" aria-label="ინვოისის ნახვა" disabled={viewer.loading === order.id} onClick={() => viewer.open(order)} data-testid={`invoice-view-${order.id}`}><FileText className="h-4 w-4" /></Button>
      <Button variant="ghost" size="icon" title="PDF ჩამოტვირთვა" aria-label="PDF ჩამოტვირთვა" onClick={() => viewer.download(order)} data-testid={`invoice-pdf-${order.id}`}><Download className="h-4 w-4" /></Button>
    </div>
  );
}

export function Pager({ page, pageSize, total, onPage }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (pages <= 1) return null;
  return (
    <div className="flex items-center justify-between gap-2 pt-2 text-sm">
      <Button size="sm" variant="outline" disabled={page === 0} onClick={() => onPage(page - 1)}>წინა</Button>
      <span className="text-muted-foreground">{page + 1} / {pages}</span>
      <Button size="sm" variant="outline" disabled={page + 1 >= pages} onClick={() => onPage(page + 1)}>შემდეგი</Button>
    </div>
  );
}
