import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, formatApiError } from "@/lib/api";
import { LogoAvatar } from "@/components/BusinessLogo";
import { useAuth } from "@/context/AuthContext";
import { useI18n } from "@/context/I18nContext";
import { useCart } from "@/context/CartContext";
import { useStoreBranch } from "@/context/StoreBranchContext";
import { StatusBadge } from "@/components/StatusBadge";
import { ProfitPriceDialog } from "@/components/ProfitPriceDialog";
import ReturnRequestDialog from "@/components/ReturnRequestDialog";
import { PaymentBadge } from "@/pages/admin/AdminOrders";
import { Package, ChevronDown, ChevronUp, XCircle, CheckCircle2, Clock, Truck, FileDown, Mail, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import LiveOrderTracking from "@/components/LiveOrderTracking";

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
  const { user } = useAuth();
  const { t } = useI18n();
  const { clear, addItems } = useCart();
  const { activeBranchId } = useStoreBranch();
  const [orders, setOrders] = useState([]);
  const [expanded, setExpanded] = useState(null);
  const [isPricingDialogOpen, setIsPricingDialogOpen] = useState(false);
  const [pricingItem, setPricingItem] = useState(null);
  const [returnSelection, setReturnSelection] = useState(null);
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const requestedOrderId = searchParams.get("order");
  const paymentId = searchParams.get("payment_id");
  const paymentGateway = searchParams.get("payment_gateway") === "bog" ? "bog" : "tbc";
  const [paymentStatus, setPaymentStatus] = useState("");
  const paymentCheckErrorShown = useRef(false);
  const isStoreOwner = (user?.store_access_role || "global_admin") === "global_admin";

  const load = useCallback(() => api.get("/orders", {
    params: activeBranchId ? { branch_id: activeBranchId } : {},
  }).then((r) => setOrders(r.data)), [activeBranchId]);
  useEffect(() => { load(); const iv = setInterval(load, 7000); return () => clearInterval(iv); }, [load]);
  useEffect(() => {
    if (!paymentId) return undefined;
    let active = true;
    let attempts = 0;
    let interval;
    paymentCheckErrorShown.current = false;
    const checkPayment = () => {
      attempts += 1;
      if (attempts > 240) {
        clearInterval(interval);
        if (!paymentCheckErrorShown.current) {
          toast.error(t("checkout.paymentStatusError"));
          paymentCheckErrorShown.current = true;
        }
        return;
      }
      api.get(`/payments/${paymentGateway}/${encodeURIComponent(paymentId)}`).then(({ data }) => {
      if (!active) return;
      setPaymentStatus(data.status);
      if (data.status === "Succeeded") {
        clear();
        toast.success(t("checkout.paymentSuccess"));
        load();
        navigate("/orders", { replace: true });
      } else if (["Failed", "Expired", "Returned", "PartialReturned"].includes(data.status)) {
        toast.error(t("checkout.paymentFailed"));
        load();
        navigate("/orders", { replace: true });
      }
    }).catch((error) => {
      if (!active) return;
      console.error("Could not check bank payment status:", error);
      if (!paymentCheckErrorShown.current) {
        toast.error(formatApiError(error.response?.data?.detail) || t("checkout.paymentStatusError"));
        paymentCheckErrorShown.current = true;
      }
    });
    };
    checkPayment();
    interval = setInterval(checkPayment, 3000);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, [paymentId, paymentGateway, load]);
  useEffect(() => {
    if (!requestedOrderId || !orders.some((order) => order.id === requestedOrderId)) return undefined;
    setExpanded(requestedOrderId);
    const timer = setTimeout(() => {
      document.getElementById(`order-${requestedOrderId}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 0);
    return () => clearTimeout(timer);
  }, [orders, requestedOrderId]);

  const cancel = async (id) => {
    try { await api.put(`/orders/${id}/status`, { status: "Cancelled" }); toast.success(t("orders.orderCancelled")); load(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const closePricingDialog = () => {
    setIsPricingDialogOpen(false);
    setPricingItem(null);
  };

  const receiveStock = async (orderId) => {
    try {
      await api.post(`/orders/${encodeURIComponent(orderId)}/receive`);
      toast.success(t("orders.stockReceived"));
      await load();
    } catch (error) {
      toast.error(formatApiError(error.response?.data?.detail));
    }
  };

  const downloadInvoice = async (order) => {
    try {
      const response = await api.get(`/orders/${order.id}/invoice.pdf`, { responseType: "blob" });
      const url = URL.createObjectURL(new Blob([response.data], { type: "application/pdf" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = `${order.order_no}-invoice.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast.error(formatApiError(error.response?.data?.detail));
    }
  };

  const reorder = async (order) => {
    try {
      const { data } = await api.post(`/orders/${order.id}/reorder`);
      if (!data.items.length) { toast.error("პროდუქცია ამჟამად მარაგში არ არის"); return; }
      addItems(data.items);
      toast.success("პროდუქცია გადატანილია კალათაში. შეგიძლიათ რაოდენობების კორექტირება და შეკვეთის გაფორმება.");
      if (data.skipped.length) toast.warning(`მარაგში არ არის: ${data.skipped.map((s) => s.name).join(", ")}`);
      navigate("/cart");
    } catch (error) {
      toast.error(formatApiError(error.response?.data?.detail));
    }
  };

  const [otherFor, setOtherFor] = useState(null);
  const [otherEmail, setOtherEmail] = useState("");
  const { refreshUser } = useAuth();

  const sendToAccounting = async (order, email) => {
    try {
      await api.post(`/orders/${order.id}/invoice/share`, email ? { email } : {});
      toast.success("ინვოისი წარმატებით გაიგზავნა ბუღალტრის ელ.ფოსტაზე!");
      if (email) { setOtherFor(null); setOtherEmail(""); refreshUser?.(); }
    } catch (error) {
      toast.error(formatApiError(error.response?.data?.detail));
    }
  };

  if (orders.length === 0)
    return <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border py-24 text-center"><Package className="h-12 w-12 text-muted-foreground" /><p className="mt-3 text-sm text-muted-foreground">{["Pending", "Processing"].includes(paymentStatus) ? t("checkout.paymentChecking") : t("orders.noOrders")}</p></div>;

  return (
    <div>
      <h1 className="mb-6 text-2xl font-bold tracking-tight sm:text-3xl">{t("orders.orderHistory")}</h1>
      {["Pending", "Processing"].includes(paymentStatus) && (
        <div className="mb-4 rounded-xl border border-processing/30 bg-processing/10 px-4 py-3 text-sm" role="status">
          {t("checkout.paymentChecking")}
        </div>
      )}
      <div className="space-y-4">
        {orders.map((o) => (
          <div key={o.id} id={`order-${o.id}`} data-testid={`order-${o.id}`} className="rounded-xl border border-border bg-card p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2.5">
                  <p className="font-mono text-sm font-bold">{o.order_no}</p>
                  <StatusBadge status={o.status} testid={`order-status-${o.id}`} />
                  <PaymentBadge method={o.payment_method} />
                  {["tbc", "bog"].includes(o.payment_method) && o.payment_status === "Pending" && (
                    <span className="rounded-full bg-processing/10 px-2 py-0.5 text-xs font-semibold text-processing">
                      {t("checkout.bankPaymentPending")}
                    </span>
                  )}
                </div>
                <p className="mt-1 flex items-center gap-2 text-sm text-muted-foreground"><LogoAvatar logo={o.supplier_logo} name={o.supplier_name} className="h-6 w-6 shrink-0 text-xs" />{o.supplier_name} · {new Date(o.created_at).toLocaleDateString()}</p>
                {o.payment_method === "bank_transfer" && o.payment_reference && (
                  <p className="mt-1 text-xs font-medium text-amber-600">{t("orders.referenceHint")} {o.payment_reference}</p>
                )}
              </div>
              <div className="text-right"><p className="text-xl font-extrabold">₾{o.total.toFixed(2)}</p><p className="font-mono text-[11px] text-muted-foreground">{o.items.length} {t("orders.itemsCount")}</p></div>
            </div>

            <div className="my-5"><OrderTimeline order={o} /></div>
            {o.status === "In Transit" && <LiveOrderTracking order={o} />}

            <div className="flex items-center justify-between">
              <Button variant="ghost" size="sm" onClick={() => setExpanded(expanded === o.id ? null : o.id)} data-testid={`expand-order-${o.id}`}>
                {expanded === o.id ? <ChevronUp className="mr-1 h-4 w-4" /> : <ChevronDown className="mr-1 h-4 w-4" />} {t("orders.details")}
              </Button>
              {o.status !== "Cancelled" && (
                <Button variant="outline" size="sm" onClick={() => reorder(o)} data-testid={`reorder-${o.id}`}>
                  <RefreshCw className="mr-1 h-4 w-4" />ხელახლა გამოწერა
                </Button>
              )}
              {o.status !== "Cancelled" && (
                <Button variant="outline" size="sm" onClick={() => downloadInvoice(o)} data-testid={`download-order-invoice-${o.id}`}>
                  <FileDown className="mr-1 h-4 w-4" />{t("orders.generateInvoice")}
                </Button>
              )}
              {o.status === "Delivered" && !o.received_at && (
                <Button variant="outline" size="sm" onClick={() => receiveStock(o.id)} data-testid={`receive-order-${o.id}`}>
                  {t("orders.receiveStock")}
                </Button>
              )}
              {o.received_at && <span className="text-xs font-medium text-emerald-600">{t("orders.stockReceived")}</span>}
              {isStoreOwner && (o.status === "Pending" || o.status === "Processing") && !(["tbc", "bog"].includes(o.payment_method) && o.payment_status !== "Succeeded") && (
                <Button variant="outline" size="sm" className="text-rose-500 hover:bg-rose-500/10" onClick={() => cancel(o.id)} data-testid={`cancel-order-${o.id}`}><XCircle className="mr-1 h-4 w-4" /> {t("orders.cancel")}</Button>
              )}
            </div>

            {expanded === o.id && (
              <div className="mt-3 space-y-2 border-t border-border pt-3">
                {o.items.map((i, index) => (
                  <div key={`${i.product_id}-${index}`} className="flex items-center gap-3 text-sm">
                    {i.image ? <img src={i.image} alt="" className="h-10 w-10 rounded border border-border object-cover" /> : <div className="h-10 w-10 rounded border border-border bg-secondary" />}
                    <span className="flex-1 truncate">{i.name}</span>
                    <span className="font-mono text-muted-foreground">{i.quantity} × ₾{i.unit_price.toFixed(2)}</span>
                    <span className="w-20 text-right font-semibold">₾{(i.quantity * i.unit_price).toFixed(2)}</span>
                    {o.status === "Delivered" && !o.external_order && (i.returned_quantity || 0) < i.quantity && (
                      <Button size="sm" variant="outline" onClick={() => setReturnSelection({ order: o, item: i })}
                        data-testid={`request-return-${o.id}-${i.product_id}`}>
                        {t("returns.request")}
                      </Button>
                    )}
                    {isStoreOwner && o.status === "Delivered" && (
                      <Button size="sm" variant="outline" onClick={() => { setPricingItem({ item: i, orderId: o.id }); setIsPricingDialogOpen(true); }}>
                        {t("pricing.calculate")}
                      </Button>
                    )}
                  </div>
                ))}
                <div className="pt-2 text-sm text-muted-foreground">
                  <p><span className="font-semibold text-foreground">{t("orders.payment")}:</span> {t(`payment.${o.payment_method || "cash"}`)}</p>
                  {o.payment_reference && <p><span className="font-semibold text-foreground">{t("orders.referenceNotice")}:</span> {o.payment_reference}</p>}
                  <p><span className="font-semibold text-foreground">{t("orders.deliverTo")}:</span> {o.delivery_address}</p>
                  <p><span className="font-semibold text-foreground">{t("orders.window")}:</span> {o.delivery_window}</p>
                  {o.notes && <p><span className="font-semibold text-foreground">{t("orders.notes")}:</span> {o.notes}</p>}
                </div>
                <div className="flex flex-wrap items-center gap-2 pt-2">
                  <Button variant="outline" size="sm" onClick={() => sendToAccounting(o)} data-testid={`send-accounting-${o.id}`}>
                    <Mail className="mr-1 h-4 w-4" />{t("orders.sendToAccounting")}
                  </Button>
                  <span className="text-xs text-muted-foreground">{user.accountant_email || user.email}</span>
                  {otherFor === o.id ? (
                    <>
                      <input type="email" value={otherEmail} onChange={(e) => setOtherEmail(e.target.value)} placeholder="name@example.com"
                        className="h-8 rounded-md border border-input bg-background px-2 text-sm" data-testid={`other-email-${o.id}`} />
                      <Button size="sm" disabled={!otherEmail.trim()} onClick={() => sendToAccounting(o, otherEmail.trim())}>გაგზავნა</Button>
                      <Button size="sm" variant="ghost" onClick={() => setOtherFor(null)}>გაუქმება</Button>
                    </>
                  ) : (
                    <Button size="sm" variant="ghost" onClick={() => { setOtherFor(o.id); setOtherEmail(""); }}>სხვა ელ.ფოსტაზე</Button>
                  )}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
      <ProfitPriceDialog
        item={pricingItem?.item}
        orderId={pricingItem?.orderId}
        isOpen={isPricingDialogOpen}
        onClose={closePricingDialog}
      />
      <ReturnRequestDialog
        order={returnSelection?.order}
        item={returnSelection?.item}
        onClose={() => setReturnSelection(null)}
        onSubmitted={load}
      />
    </div>
  );
}
