import { Fragment, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "@/lib/api";
import { useI18n } from "@/context/I18nContext";
import { StatusBadge } from "@/components/StatusBadge";
import { LogoAvatar } from "@/components/BusinessLogo";
import { ClipboardList, CreditCard, Banknote, FileClock } from "lucide-react";
import { cn } from "@/lib/utils";

const PAY_ICON = { cash: Banknote, card: CreditCard, tbc: CreditCard, bog: CreditCard, consignment: FileClock, bank_transfer: Banknote };

export function PaymentBadge({ method }) {
  const { t } = useI18n();
  const m = method || "cash";
  const Icon = PAY_ICON[m] || Banknote;
  const color = m === "card" ? "bg-info/10 text-info border-info/30"
    : m === "consignment" ? "bg-processing/10 text-processing border-processing/30"
    : m === "bank_transfer" ? "bg-amber-500/10 text-amber-600 border-amber-500/30"
    : ["tbc", "bog"].includes(m) ? "bg-highlight/10 text-highlight border-highlight/30"
    : "bg-emerald-500/10 text-emerald-500 border-emerald-500/30";
  return (
    <span data-testid={`payment-badge-${m}`} className={cn("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold", color)}>
      <Icon className="h-3.5 w-3.5" /> {t(`payment.${m}`)}
    </span>
  );
}

export default function AdminOrders() {
  const { t } = useI18n();
  const [orders, setOrders] = useState([]);
  const [expanded, setExpanded] = useState(null);
  const [searchParams] = useSearchParams();
  const requestedOrderId = searchParams.get("order");
  useEffect(() => {
    // Skip a tick while the previous request is still running so slow responses never pile up.
    let inFlight = false;
    const load = async () => {
      if (inFlight) return;
      inFlight = true;
      try { const r = await api.get("/orders", { params: { limit: 200 } }); setOrders(r.data); }
      catch { /* keep showing the last good data; next tick retries */ }
      finally { inFlight = false; }
    };
    load();
    const iv = setInterval(load, 15000);
    return () => clearInterval(iv);
  }, []);
  useEffect(() => {
    if (!requestedOrderId || !orders.some((order) => order.id === requestedOrderId)) return undefined;
    setExpanded(requestedOrderId);
    const timer = setTimeout(() => {
      document.getElementById(`admin-order-${requestedOrderId}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 0);
    return () => clearTimeout(timer);
  }, [orders, requestedOrderId]);

  return (
    <div>
      <h1 className="mb-6 text-2xl font-bold tracking-tight sm:text-3xl">{t("orders.allOrders")}</h1>
      {orders.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border py-20 text-center"><ClipboardList className="h-10 w-10 text-muted-foreground" /><p className="mt-3 text-sm text-muted-foreground">{t("orders.noOrders")}</p></div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border bg-card">
          <table className="w-full text-sm">
            <thead className="border-b border-border bg-secondary/50"><tr className="text-left font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
              <th className="px-4 py-3">{t("orders.order")}</th><th className="px-4 py-3">{t("orders.retailer")}</th><th className="px-4 py-3">{t("orders.supplier")}</th>
              <th className="px-4 py-3">{t("orders.payment")}</th><th className="px-4 py-3">{t("common.status")}</th><th className="px-4 py-3 text-right">{t("common.total")}</th>
            </tr></thead>
            <tbody>
              {orders.map((o) => (
                <Fragment key={o.id}>
                  <tr id={`admin-order-${o.id}`} data-testid={`admin-order-${o.id}`} className="border-b border-border/50 last:border-0">
                    <td className="px-4 py-3 font-mono font-bold">
                      <button type="button" className="text-left hover:text-primary" onClick={() => setExpanded(expanded === o.id ? null : o.id)}>{o.order_no}</button>
                    </td>
                    <td className="px-4 py-3">{o.retailer_name}</td>
                    <td className="px-4 py-3 text-muted-foreground"><span className="flex items-center gap-2"><LogoAvatar logo={o.supplier_logo} name={o.supplier_name} className="h-6 w-6 shrink-0 text-xs" />{o.supplier_name}</span></td>
                    <td className="px-4 py-3"><PaymentBadge method={o.payment_method} /></td>
                    <td className="px-4 py-3"><StatusBadge status={o.status} /></td>
                    <td className="px-4 py-3 text-right font-bold">₾{o.total.toFixed(2)}</td>
                  </tr>
                  {expanded === o.id && (
                    <tr className="border-b border-border bg-secondary/30" data-testid={`admin-order-details-${o.id}`}>
                      <td colSpan={6} className="space-y-2 px-4 py-4">
                        <p>{t("orders.deliverTo")}: {o.delivery_address} · {t("orders.window")}: {o.delivery_window}</p>
                        <div className="space-y-1">
                          {o.items.map((item) => (
                            <p key={item.product_id} className="text-muted-foreground">
                              {item.name} — {item.quantity} × ₾{item.unit_price.toFixed(2)}
                            </p>
                          ))}
                        </div>
                        {o.notes && <p>{t("orders.notes")}: {o.notes}</p>}
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
