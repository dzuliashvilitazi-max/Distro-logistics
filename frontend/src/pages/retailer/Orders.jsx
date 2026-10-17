import { useEffect, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { useI18n } from "@/context/I18nContext";
import { StatusBadge } from "@/components/StatusBadge";
import { PaymentBadge } from "@/pages/admin/AdminOrders";
import { Package, ChevronDown, ChevronUp, XCircle, CheckCircle2, Clock, Truck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

const STEPS = ["Pending", "Processing", "In Transit", "Delivered"];

export function OrderTimeline({ order }) {
  const { t } = useI18n();
  if (order.status === "Cancelled")
    return <div className="flex items-center gap-2 rounded-lg bg-rose-500/10 px-3 py-2 text-sm font-medium text-rose-500"><XCircle className="h-4 w-4" /> {t("status.Cancelled")}</div>;
  const current = STEPS.indexOf(order.status);
  return (
    <div className="flex items-center">
      {STEPS.map((s, i) => (
        <div key={s} className="flex flex-1 items-center last:flex-none">
          <div className="flex flex-col items-center">
            <div className={cn("flex h-8 w-8 items-center justify-center rounded-full border-2", i <= current ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card text-muted-foreground")}>
              {i < current ? <CheckCircle2 className="h-4 w-4" /> : i === 0 ? <Clock className="h-4 w-4" /> : i === 2 ? <Truck className="h-4 w-4" /> : <Package className="h-4 w-4" />}
            </div>
            <span className={cn("mt-1 whitespace-nowrap text-[10px] font-semibold", i <= current ? "text-foreground" : "text-muted-foreground")}>{t(`status.${s}`)}</span>
          </div>
          {i < STEPS.length - 1 && <div className={cn("mx-1 h-0.5 flex-1", i < current ? "bg-primary" : "bg-border")} />}
        </div>
      ))}
    </div>
  );
}

export default function Orders() {
  const { t } = useI18n();
  const [orders, setOrders] = useState([]);
  const [expanded, setExpanded] = useState(null);

  const load = () => api.get("/orders").then((r) => setOrders(r.data));
  useEffect(() => { load(); const iv = setInterval(load, 7000); return () => clearInterval(iv); }, []);

  const cancel = async (id) => {
    try { await api.put(`/orders/${id}/status`, { status: "Cancelled" }); toast.success(t("orders.orderCancelled")); load(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  if (orders.length === 0)
    return <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border py-24 text-center"><Package className="h-12 w-12 text-muted-foreground" /><p className="mt-3 text-sm text-muted-foreground">{t("orders.noOrders")}</p></div>;

  return (
    <div>
      <h1 className="mb-6 text-2xl font-bold tracking-tight sm:text-3xl">{t("orders.orderHistory")}</h1>
      <div className="space-y-4">
        {orders.map((o) => (
          <div key={o.id} data-testid={`order-${o.id}`} className="rounded-xl border border-border bg-card p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2.5">
                  <p className="font-mono text-sm font-bold">{o.order_no}</p>
                  <StatusBadge status={o.status} testid={`order-status-${o.id}`} />
                  <PaymentBadge method={o.payment_method} />
                </div>
                <p className="mt-1 text-sm text-muted-foreground">{o.supplier_name} · {new Date(o.created_at).toLocaleDateString()}</p>
              </div>
              <div className="text-right"><p className="text-xl font-extrabold">₾{o.total.toFixed(2)}</p><p className="font-mono text-[11px] text-muted-foreground">{o.items.length} {t("orders.itemsCount")}</p></div>
            </div>

            <div className="my-5"><OrderTimeline order={o} /></div>

            <div className="flex items-center justify-between">
              <Button variant="ghost" size="sm" onClick={() => setExpanded(expanded === o.id ? null : o.id)} data-testid={`expand-order-${o.id}`}>
                {expanded === o.id ? <ChevronUp className="mr-1 h-4 w-4" /> : <ChevronDown className="mr-1 h-4 w-4" />} {t("orders.details")}
              </Button>
              {(o.status === "Pending" || o.status === "Processing") && (
                <Button variant="outline" size="sm" className="text-rose-500 hover:bg-rose-500/10" onClick={() => cancel(o.id)} data-testid={`cancel-order-${o.id}`}><XCircle className="mr-1 h-4 w-4" /> {t("orders.cancel")}</Button>
              )}
            </div>

            {expanded === o.id && (
              <div className="mt-3 space-y-2 border-t border-border pt-3">
                {o.items.map((i) => (
                  <div key={i.product_id} className="flex items-center gap-3 text-sm">
                    <img src={i.image} alt="" className="h-10 w-10 rounded border border-border object-cover" />
                    <span className="flex-1 truncate">{i.name}</span>
                    <span className="font-mono text-muted-foreground">{i.quantity} × ₾{i.unit_price.toFixed(2)}</span>
                    <span className="w-20 text-right font-semibold">₾{(i.quantity * i.unit_price).toFixed(2)}</span>
                  </div>
                ))}
                <div className="pt-2 text-sm text-muted-foreground">
                  <p><span className="font-semibold text-foreground">{t("orders.payment")}:</span> {t(`payment.${o.payment_method || "cash"}`)}</p>
                  <p><span className="font-semibold text-foreground">{t("orders.deliverTo")}:</span> {o.delivery_address}</p>
                  <p><span className="font-semibold text-foreground">{t("orders.window")}:</span> {o.delivery_window}</p>
                  {o.notes && <p><span className="font-semibold text-foreground">{t("orders.notes")}:</span> {o.notes}</p>}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
