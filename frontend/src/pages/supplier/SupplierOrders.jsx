import { useEffect, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { useI18n } from "@/context/I18nContext";
import { StatusBadge } from "@/components/StatusBadge";
import { PaymentBadge } from "@/pages/admin/AdminOrders";
import { Check, X, Truck, Package, ClipboardList } from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

const TABS = ["All", "Pending", "Processing", "In Transit", "Delivered", "Cancelled"];
const NEXT = { Pending: "Processing", Processing: "In Transit", "In Transit": "Delivered" };

export default function SupplierOrders() {
  const { t: tr } = useI18n();
  const [orders, setOrders] = useState([]);
  const [tab, setTab] = useState("All");

  const load = () => api.get("/orders").then((r) => setOrders(r.data));
  useEffect(() => { load(); const iv = setInterval(load, 7000); return () => clearInterval(iv); }, []);

  const update = async (id, status) => {
    try { await api.put(`/orders/${id}/status`, { status }); toast.success(`${tr("orders.orderMarked")} ${tr(`status.${status}`)}`); load(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const filtered = tab === "All" ? orders : orders.filter((o) => o.status === tab);

  return (
    <div>
      <h1 className="mb-6 text-2xl font-bold tracking-tight sm:text-3xl">{tr("orders.orderManagement")}</h1>
      <div className="mb-6 flex flex-wrap gap-2">
        {TABS.map((tb) => (
          <button key={tb} onClick={() => setTab(tb)} data-testid={`order-tab-${tb.replace(/\s/g, "-")}`}
            className={cn("rounded-full border px-3.5 py-1.5 text-sm font-medium transition-colors duration-200", tab === tb ? "border-primary bg-primary text-primary-foreground" : "border-border text-muted-foreground hover:text-foreground")}>
            {tb === "All" ? tr("usr.all") : tr(`status.${tb}`)} {tb !== "All" && <span className="font-mono">({orders.filter((o) => o.status === tb).length})</span>}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border py-20 text-center"><ClipboardList className="h-10 w-10 text-muted-foreground" /><p className="mt-3 text-sm text-muted-foreground">{tr("orders.noOrdersView")}</p></div>
      ) : (
        <div className="space-y-4">
          {filtered.map((o) => (
            <div key={o.id} data-testid={`supplier-order-${o.id}`} className="rounded-xl border border-border bg-card p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2.5"><p className="font-mono text-sm font-bold">{o.order_no}</p><StatusBadge status={o.status} /><PaymentBadge method={o.payment_method} /></div>
                  <p className="mt-1 text-sm text-muted-foreground">{tr("orders.from")} <span className="font-medium text-foreground">{o.retailer_name}</span> · {new Date(o.created_at).toLocaleString()}</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">{tr("orders.deliverTo")}: {o.delivery_address} · {o.delivery_window}</p>
                </div>
                <p className="text-xl font-extrabold">${o.total.toFixed(2)}</p>
              </div>

              <div className="my-3 space-y-1.5 border-y border-border py-3">
                {o.items.map((i) => (
                  <div key={i.product_id} className="flex items-center gap-3 text-sm"><img src={i.image || undefined} alt="" className="h-9 w-9 rounded border border-border object-cover" /><span className="flex-1 truncate">{i.name}</span><span className="font-mono text-muted-foreground">{i.quantity} × ${i.unit_price.toFixed(2)}</span></div>
                ))}
                {o.notes && <p className="pt-1 text-xs text-muted-foreground"><span className="font-semibold text-foreground">{tr("orders.notes")}:</span> {o.notes}</p>}
              </div>

              <div className="flex flex-wrap gap-2">
                {o.status === "Pending" && (
                  <>
                    <Button size="sm" onClick={() => update(o.id, "Processing")} data-testid={`accept-order-${o.id}`}><Check className="mr-1 h-4 w-4" /> {tr("orders.accept")}</Button>
                    <Button size="sm" variant="outline" className="text-rose-500 hover:bg-rose-500/10" onClick={() => update(o.id, "Cancelled")} data-testid={`reject-order-${o.id}`}><X className="mr-1 h-4 w-4" /> {tr("orders.reject")}</Button>
                  </>
                )}
                {NEXT[o.status] && o.status !== "Pending" && (
                  <Button size="sm" onClick={() => update(o.id, NEXT[o.status])} data-testid={`advance-order-${o.id}`}><Truck className="mr-1 h-4 w-4" /> {tr("orders.markAs")} {tr(`status.${NEXT[o.status]}`)}</Button>
                )}
                {o.status === "Delivered" && <span className="flex items-center gap-1.5 text-sm font-medium text-emerald-500"><Package className="h-4 w-4" /> {tr("orders.fulfilled")}</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
