import { useCallback, useEffect, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { useI18n } from "@/context/I18nContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Check, Loader2, RotateCcw, X } from "lucide-react";
import { toast } from "sonner";

const FILTERS = ["ALL", "PENDING", "APPROVING", "APPROVED", "REJECTED"];
const STATUS_STYLE = {
  PENDING: "border-amber-500/30 bg-amber-500/10 text-amber-700",
  APPROVING: "border-sky-500/30 bg-sky-500/10 text-sky-700",
  APPROVED: "border-emerald-500/30 bg-emerald-500/10 text-emerald-700",
  REJECTED: "border-rose-500/30 bg-rose-500/10 text-rose-700",
};

export default function ReturnsDashboard() {
  const { user } = useAuth();
  const { t, lang } = useI18n();
  const isSupplier = user?.role === "supplier";
  const [filter, setFilter] = useState("ALL");
  const [rows, setRows] = useState(null);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState(null);
  const [decisionComment, setDecisionComment] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = filter === "ALL" ? {} : { status: filter };
      const path = isSupplier ? "/supplier/returns" : "/returns/mine";
      const { data } = await api.get(path, { params });
      setRows(data);
    } catch (error) {
      toast.error(formatApiError(error.response?.data?.detail));
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [filter, isSupplier]);

  useEffect(() => { load(); }, [load]);

  const openDecision = (row, decision) => {
    setSelected({ ...row, decision });
    setDecisionComment("");
  };

  const submitDecision = async (event) => {
    event.preventDefault();
    if (!selected || saving) return;
    if (selected.decision === "REJECTED" && !decisionComment.trim()) {
      toast.error(t("returns.reasonRequired"));
      return;
    }
    setSaving(true);
    try {
      await api.patch(`/supplier/returns/${encodeURIComponent(selected.id)}/decision`, {
        decision: selected.decision, comment: decisionComment.trim(),
      });
      toast.success(t("returns.decisionSaved"));
      setSelected(null);
      await load();
    } catch (error) {
      toast.error(formatApiError(error.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  };

  const dateLabel = (value) => value
    ? new Date(value).toLocaleString(lang === "ka" ? "ka-GE" : lang === "ru" ? "ru-RU" : "en-GB")
    : "—";

  if (rows === null) return (
    <div className="space-y-5" data-testid="returns-skeleton" aria-busy="true">
      <Skeleton className="h-12 w-64" />
      <Skeleton className="h-10 w-full" />
      <Skeleton className="h-72 w-full" />
    </div>
  );

  return (
    <div className="space-y-6" data-testid="returns-dashboard">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-4">
        <div className="flex items-center gap-2">
          <RotateCcw className="h-6 w-6 text-primary" />
          <h1 className="text-2xl font-bold tracking-tight">{t("returns.title")}</h1>
        </div>
        {loading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-hidden="true" />}
      </header>

      <div className="flex flex-wrap gap-2" role="group" aria-label={t("returns.history")} data-testid="return-status-filters">
        {FILTERS.map((status) => (
          <Button key={status} type="button" size="sm" variant={filter === status ? "default" : "outline"}
            aria-pressed={filter === status} onClick={() => setFilter(status)} data-testid={`return-filter-${status.toLowerCase()}`}>
            {status === "ALL" ? t("bill.filter.all") : t(`returns.${status.toLowerCase()}`)}
          </Button>
        ))}
      </div>

      <div className="overflow-x-auto rounded-md border border-border bg-card">
        <table className="w-full min-w-[980px] text-sm">
          <thead className="bg-secondary/60 text-left text-xs uppercase text-muted-foreground">
            <tr>
              <th className="px-4 py-3">{t("orders.order")}</th>
              <th className="px-4 py-3">{t("common.product")}</th>
              <th className="px-4 py-3">{t("returns.quantity")}</th>
              {isSupplier && <th className="px-4 py-3">{t("finance.store")}</th>}
              <th className="px-4 py-3">{t("returns.reason")}</th>
              <th className="px-4 py-3">{t("common.status")}</th>
              <th className="px-4 py-3">{t("returns.comment")}</th>
              {isSupplier && <th className="px-4 py-3 text-right">{t("common.actions")}</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map((row) => (
              <tr key={row.id} data-testid={`return-row-${row.id}`}>
                <td className="px-4 py-3">
                  <div className="font-mono font-semibold">{row.order_no}</div>
                  <div className="mt-1 text-xs text-muted-foreground">{dateLabel(row.created_at)}</div>
                </td>
                <td className="px-4 py-3 font-medium">{row.product_name}</td>
                <td className="px-4 py-3 font-mono">{row.quantity}</td>
                {isSupplier && <td className="px-4 py-3">{row.retailer_name}</td>}
                <td className="px-4 py-3">{t(`returns.reasons.${row.reason}`)}</td>
                <td className="px-4 py-3">
                  <span className={`inline-flex rounded-sm border px-2 py-1 text-xs font-semibold ${STATUS_STYLE[row.status] || ""}`}>
                    {t(`returns.${row.status.toLowerCase()}`)}
                  </span>
                </td>
                <td className="max-w-[240px] px-4 py-3 text-xs text-muted-foreground">
                  <p>{row.comment || "—"}</p>
                  {row.decision_comment && <p className="mt-1 text-foreground">{row.decision_comment}</p>}
                </td>
                {isSupplier && <td className="px-4 py-3 text-right">
                  {["PENDING", "APPROVING"].includes(row.status) && (
                    <div className="flex justify-end gap-2">
                      <Button size="sm" onClick={() => openDecision(row, "APPROVED")} data-testid={`return-approve-${row.id}`}>
                        <Check className="mr-1 h-4 w-4" />{row.status === "APPROVING" ? t("returns.retry") : t("returns.approve")}
                      </Button>
                      {row.status === "PENDING" && (
                        <Button size="sm" variant="outline" className="text-rose-600" onClick={() => openDecision(row, "REJECTED")} data-testid={`return-reject-${row.id}`}>
                          <X className="mr-1 h-4 w-4" />{t("returns.reject")}
                        </Button>
                      )}
                    </div>
                  )}
                </td>}
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={isSupplier ? 8 : 6} className="px-4 py-12 text-center text-muted-foreground">{t("returns.noReturns")}</td></tr>}
          </tbody>
        </table>
      </div>

      <Dialog open={!!selected} onOpenChange={(open) => { if (!open && !saving) setSelected(null); }}>
        <DialogContent className="bg-card sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{selected?.decision === "APPROVED" ? t("returns.approve") : t("returns.reject")}</DialogTitle>
            <DialogDescription>{selected?.order_no} · {selected?.product_name} · {selected?.quantity}</DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={submitDecision}>
            <label className="block space-y-1 text-sm">
              <span>{t("returns.decisionComment")}{selected?.decision === "REJECTED" ? " *" : ""}</span>
              <Textarea value={decisionComment} onChange={(event) => setDecisionComment(event.target.value)} maxLength={1000} rows={3} />
            </label>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setSelected(null)} disabled={saving}>{t("common.cancel")}</Button>
              <Button type="submit" variant={selected?.decision === "REJECTED" ? "destructive" : "default"} disabled={saving}>
                {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {selected?.decision === "APPROVED" ? t("returns.approve") : t("returns.reject")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
