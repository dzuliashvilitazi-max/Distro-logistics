import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useI18n } from "@/context/I18nContext";
import { StatusBadge } from "@/components/StatusBadge";
import { ClipboardList, CreditCard, Banknote, FileClock } from "lucide-react";
import { cn } from "@/lib/utils";

const PAY_ICON = { cash: Banknote, card: CreditCard, consignment: FileClock };

export function PaymentBadge({ method }) {
  const { t } = useI18n();
  const m = method || "cash";
  const Icon = PAY_ICON[m] || Banknote;
  const color = m === "card" ? "bg-blue-500/10 text-blue-500 border-blue-500/30"
    : m === "consignment" ? "bg-violet-500/10 text-violet-400 border-violet-500/30"
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
  useEffect(() => { const load = () => api.get("/orders").then((r) => setOrders(r.data)); load(); const iv = setInterval(load, 8000); return () => clearInterval(iv); }, []);

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
                <tr key={o.id} data-testid={`admin-order-${o.id}`} className="border-b border-border/50 last:border-0">
                  <td className="px-4 py-3 font-mono font-bold">{o.order_no}</td>
                  <td className="px-4 py-3">{o.retailer_name}</td>
                  <td className="px-4 py-3 text-muted-foreground">{o.supplier_name}</td>
                  <td className="px-4 py-3"><PaymentBadge method={o.payment_method} /></td>
                  <td className="px-4 py-3"><StatusBadge status={o.status} /></td>
                  <td className="px-4 py-3 text-right font-bold">₾{o.total.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
