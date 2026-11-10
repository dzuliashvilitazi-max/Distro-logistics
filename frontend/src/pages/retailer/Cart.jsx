import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useCart } from "@/context/CartContext";
import { useAuth } from "@/context/AuthContext";
import { useStoreBranch } from "@/context/StoreBranchContext";
import { useI18n } from "@/context/I18nContext";
import { api, tierPrice, formatApiError } from "@/lib/api";
import ProductImage from "@/components/ProductImage";
import { PAYMENT_METHODS } from "@/lib/i18n";
import { Trash2, Plus, Minus, ShoppingCart, Truck, Loader2, Banknote, CreditCard, FileClock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

const PAY_ICON = { cash: Banknote, card: CreditCard, consignment: FileClock, bank_transfer: Banknote };

export default function Cart() {
  const { items, updateQty, removeItem, clear } = useCart();
  const { user } = useAuth();
  const { activeBranch } = useStoreBranch();
  const { t } = useI18n();
  const navigate = useNavigate();
  const address = [activeBranch?.address || user.address || "", activeBranch?.city || ""]
    .filter(Boolean)
    .join(", ");
  const [notes, setNotes] = useState("");
  const [deliveryWindow, setDeliveryWindow] = useState("9am - 12pm");
  const [payment, setPayment] = useState(user.card_verified ? "online" : "cash");
  const [cards, setCards] = useState([]);
  const [cardId, setCardId] = useState(null);
  const [recentOrders, setRecentOrders] = useState([]);
  const [placing, setPlacing] = useState(false);
  useEffect(() => {
    api.get("/payments/cards").then((r) => {
      const list = r.data.cards || [];
      setCards(list);
      setCardId((cur) => (list.some((c) => c.id === cur) ? cur : list[0]?.id || null));
      if (!list.length) setPayment((p) => (p === "online" ? "cash" : p));
    }).catch(() => {});
  }, []);
  const lines = useMemo(() => items.map((i) => ({ ...i, unit: tierPrice(i, i.quantity), subtotal: tierPrice(i, i.quantity) * i.quantity })), [items]);
  const total = lines.reduce((s, l) => s + l.subtotal, 0);

  const checkout = async () => {
    if (!address.trim()) { toast.error(t("checkout.enterAddress")); return; }
    const locationLat = activeBranch?.lat ?? activeBranch?.route_coordinates?.lat;
    const locationLng = activeBranch?.lng ?? activeBranch?.route_coordinates?.lng ?? activeBranch?.route_coordinates?.lon;
    if (!Number.isFinite(locationLat) || !Number.isFinite(locationLng)) { toast.error(t("checkout.pinAddress")); return; }
    for (const l of lines) if (l.quantity < l.moq) { toast.error(`${l.name} — ${t("checkout.belowMoq")} (${l.moq})`); return; }
    setPlacing(true);
    try {
      const { data: connections } = await api.get("/connections/mine");
      const approvedDistributors = new Set(
        connections.filter((connection) => connection.status === "APPROVED")
          .map((connection) => connection.distributor_id),
      );
      if (lines.some((line) => !approvedDistributors.has(line.supplier_id))) {
        toast.error(t("checkout.connectionRequired"));
        navigate("/catalog");
        return;
      }
      const payload = {
        items: lines.map((l) => ({ product_id: l.product_id, name: l.name, image: l.image, supplier_id: l.supplier_id, quantity: l.quantity, unit_price: l.unit })),
        delivery_address: address, notes, delivery_window: deliveryWindow, payment_method: payment,
        branch_id: activeBranch?.id,
        ...(payment === "online" ? { card_id: cardId } : {}),
      };
      const { data } = await api.post("/orders", payload);
      clear();
      if (payment === "bank_transfer") {
        setRecentOrders(data.orders || []);
        const refs = data.orders.map((order) => order.payment_reference).filter(Boolean).join(", ");
        toast.success(`${t("checkout.bankTransferPlaced")}${refs ? ` (${refs})` : ""}`);
        return;
      } else {
        toast.success(`${data.orders.length} ${t("checkout.orderPlaced")}`);
      }
      navigate("/orders");
    } catch (err) {
      const detail = formatApiError(err.response?.data?.detail);
      if (/bank account missing/i.test(detail)) toast.error(detail, { duration: 10000 });
      else toast.error(detail);
    } finally { setPlacing(false); }
  };

  const downloadInvoice = async (orderId, orderNo) => {
    try {
      const response = await api.get(`/orders/${orderId}/invoice.pdf`, { responseType: "blob" });
      const url = URL.createObjectURL(new Blob([response.data], { type: "application/pdf" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = `${orderNo}-invoice.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail));
    }
  };

  if (items.length === 0 && recentOrders.length > 0)
    return (
      <div className="rounded-xl border border-border bg-card p-6 text-center">
        <h2 className="text-xl font-semibold">{t("checkout.bankTransferPlaced")}</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          {recentOrders.map((order) => order.payment_reference).filter(Boolean).join(", ")}
        </p>
        <div className="mt-4 flex flex-wrap justify-center gap-2">
          {recentOrders.map((order) => (
            <Button key={order.id} variant="outline" onClick={() => downloadInvoice(order.id, order.order_no)}>
              <Banknote className="mr-2 h-4 w-4" />{order.order_no}
            </Button>
          ))}
        </div>
        <Button className="mt-5" onClick={() => navigate("/orders")}>{t("orders.orderHistory")}</Button>
      </div>
    );

  if (items.length === 0)
    return (
      <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border py-24 text-center">
        <ShoppingCart className="h-12 w-12 text-muted-foreground" />
        <h2 className="mt-4 text-xl font-semibold">{t("checkout.cartEmptyTitle")}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{t("checkout.cartEmptyDesc")}</p>
        <Button className="mt-5" onClick={() => navigate("/catalog")} data-testid="browse-catalog-btn">{t("checkout.browseCatalog")}</Button>
      </div>
    );

  return (
    <div>
      <h1 className="mb-6 text-2xl font-bold tracking-tight sm:text-3xl">{t("checkout.cartTitle")}</h1>
      <div className="grid gap-6 lg:grid-cols-12">
        <div className="space-y-3 lg:col-span-7">
          {lines.map((l) => (
            <div key={l.product_id} data-testid={`cart-item-${l.product_id}`} className="flex gap-4 rounded-xl border border-border bg-card p-4">
              <ProductImage image={l.image} name={l.name} alt={l.name} className="h-20 w-20 shrink-0 rounded-lg border border-border object-cover" />
              <div className="min-w-0 flex-1">
                <p className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">{l.supplier_name}</p>
                <h3 className="truncate text-sm font-semibold">{l.name}</h3>
                <p className="mt-0.5 text-sm text-muted-foreground">₾{l.unit.toFixed(2)} {t("catalog.perUnit")} · {t("catalog.moq")} {l.moq}</p>
                <div className="mt-2 flex items-center gap-2">
                  <Button variant="outline" size="icon" className="h-8 w-8" onClick={() => updateQty(l.product_id, Math.max(1, l.quantity - 10))} data-testid={`cart-minus-${l.product_id}`}><Minus className="h-3.5 w-3.5" /></Button>
                  <Input type="number" value={l.quantity} onChange={(e) => updateQty(l.product_id, Math.max(1, parseInt(e.target.value) || 1))} className="h-8 w-20 text-center" data-testid={`cart-qty-${l.product_id}`} />
                  <Button variant="outline" size="icon" className="h-8 w-8" onClick={() => updateQty(l.product_id, l.quantity + 10)} data-testid={`cart-plus-${l.product_id}`}><Plus className="h-3.5 w-3.5" /></Button>
                </div>
              </div>
              <div className="flex flex-col items-end justify-between">
                <Button variant="ghost" size="icon" className="text-muted-foreground hover:text-rose-500" onClick={() => removeItem(l.product_id)} data-testid={`cart-remove-${l.product_id}`}><Trash2 className="h-4 w-4" /></Button>
                <p className="text-lg font-bold">₾{l.subtotal.toFixed(2)}</p>
              </div>
            </div>
          ))}
        </div>

        <div className="lg:col-span-5">
          <div className="sticky top-20 space-y-4 rounded-xl border border-border bg-card p-5">
            <h3 className="text-lg font-semibold">{t("checkout.deliveryDetails")}</h3>
            {activeBranch && <p className="text-xs text-muted-foreground">{t("branch.current")}: <span className="font-semibold text-foreground">{activeBranch.name}</span></p>}
            <div><Label htmlFor="addr">{t("checkout.deliveryAddress")}</Label><Textarea id="addr" value={address} readOnly className="mt-1.5" rows={2} data-testid="checkout-address" placeholder={t("checkout.addressPlaceholder")} />
              {!Number.isFinite(activeBranch?.lat ?? activeBranch?.route_coordinates?.lat) && <p className="mt-1 text-xs text-amber-600" role="status">{t("checkout.pinAddress")}</p>}
            </div>
            <div><Label htmlFor="window">{t("checkout.deliveryWindow")}</Label>
              <select id="window" value={deliveryWindow} onChange={(e) => setDeliveryWindow(e.target.value)} data-testid="checkout-window" className="mt-1.5 h-10 w-full rounded-md border border-input bg-background px-3 text-sm">
                {["9am - 12pm", "12pm - 3pm", "3pm - 6pm", "After hours"].map((w) => <option key={w}>{w}</option>)}
              </select>
            </div>
            <div>
              <Label>{t("checkout.paymentMethod")}</Label>
              <div className="mt-1.5 space-y-2" data-testid="payment-method-group">
                {cards.map((c) => {
                  const active = payment === "online" && cardId === c.id;
                  return (
                    <button type="button" key={c.id} onClick={() => { setPayment("online"); setCardId(c.id); }} data-testid={`payment-option-card-${c.id}`}
                      className={cn("flex w-full items-center gap-3 rounded-lg border-2 px-3 py-2.5 text-left transition-colors duration-200", active ? "border-primary bg-primary/5" : "border-border hover:border-primary/40")}>
                      <CreditCard className={cn("h-5 w-5 shrink-0", active ? "text-primary" : "text-muted-foreground")} />
                      <span className="text-sm font-medium">გადაიხადე ბარათით - {(c.brand || "card").toUpperCase()} ••••{c.last4}{c.exp ? ` · ${c.exp}` : ""}</span>
                      <span className={cn("ml-auto h-4 w-4 rounded-full border-2", active ? "border-primary bg-primary" : "border-muted-foreground")} />
                    </button>
                  );
                })}
                {PAYMENT_METHODS.filter((m) => m !== "card").map((m) => {
                  const Icon = PAY_ICON[m];
                  const active = payment === m;
                  return (
                    <button type="button" key={m} onClick={() => setPayment(m)} data-testid={`payment-option-${m}`}
                      className={cn("flex w-full items-center gap-3 rounded-lg border-2 px-3 py-2.5 text-left transition-colors duration-200",
                        active ? "border-primary bg-primary/5" : "border-border hover:border-primary/40")}>
                      <Icon className={cn("h-5 w-5 shrink-0", active ? "text-primary" : "text-muted-foreground")} />
                      <span className="text-sm font-medium">{t(`payment.${m}`)}</span>
                      <span className={cn("ml-auto h-4 w-4 rounded-full border-2", active ? "border-primary bg-primary" : "border-muted-foreground")} />
                    </button>
                  );
                })}
              </div>
            </div>
            <div><Label htmlFor="notes">{t("checkout.orderNotes")}</Label><Textarea id="notes" value={notes} onChange={(e) => setNotes(e.target.value)} className="mt-1.5" rows={2} data-testid="checkout-notes" placeholder={t("checkout.notesPlaceholder")} /></div>
            <div className="border-t border-border pt-3">
              <div className="flex items-center justify-between text-sm text-muted-foreground"><span>{t("checkout.items")}</span><span>{lines.length}</span></div>
              <div className="mt-2 flex items-center justify-between"><span className="text-base font-semibold">{t("checkout.orderTotal")}</span><span className="text-2xl font-extrabold" data-testid="cart-total">₾{total.toFixed(2)}</span></div>
            </div>
            <Button className="h-12 w-full text-base" onClick={checkout} disabled={placing} data-testid="place-order-btn">
              {placing ? <Loader2 className="h-5 w-5 animate-spin" /> : <><Truck className="mr-2 h-5 w-5" /> {t("checkout.placeOrder")}</>}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
