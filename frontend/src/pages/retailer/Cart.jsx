import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useCart } from "@/context/CartContext";
import { useAuth } from "@/context/AuthContext";
import { api, tierPrice, formatApiError } from "@/lib/api";
import { Trash2, Plus, Minus, ShoppingCart, Truck, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";

export default function Cart() {
  const { items, updateQty, removeItem, clear } = useCart();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [address, setAddress] = useState(user.address || "");
  const [notes, setNotes] = useState("");
  const [window, setWindow] = useState("9am - 12pm");
  const [placing, setPlacing] = useState(false);

  const lines = useMemo(() => items.map((i) => ({ ...i, unit: tierPrice(i, i.quantity), subtotal: tierPrice(i, i.quantity) * i.quantity })), [items]);
  const total = lines.reduce((s, l) => s + l.subtotal, 0);

  const checkout = async () => {
    if (!address.trim()) { toast.error("Please enter a delivery address"); return; }
    for (const l of lines) if (l.quantity < l.moq) { toast.error(`${l.name} is below MOQ (${l.moq})`); return; }
    setPlacing(true);
    try {
      const payload = {
        items: lines.map((l) => ({ product_id: l.product_id, name: l.name, image: l.image, supplier_id: l.supplier_id, quantity: l.quantity, unit_price: l.unit })),
        delivery_address: address, notes, delivery_window: window,
      };
      const { data } = await api.post("/orders", payload);
      clear();
      toast.success(`${data.orders.length} order(s) placed successfully!`);
      navigate("/orders");
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail));
    } finally { setPlacing(false); }
  };

  if (items.length === 0)
    return (
      <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border py-24 text-center">
        <ShoppingCart className="h-12 w-12 text-muted-foreground" />
        <h2 className="mt-4 text-xl font-semibold">Your cart is empty</h2>
        <p className="mt-1 text-sm text-muted-foreground">Browse the catalog to start a bulk order.</p>
        <Button className="mt-5" onClick={() => navigate("/catalog")} data-testid="browse-catalog-btn">Browse Catalog</Button>
      </div>
    );

  return (
    <div>
      <h1 className="mb-6 text-2xl font-bold tracking-tight sm:text-3xl">Bulk Cart & Checkout</h1>
      <div className="grid gap-6 lg:grid-cols-12">
        <div className="space-y-3 lg:col-span-7">
          {lines.map((l) => (
            <div key={l.product_id} data-testid={`cart-item-${l.product_id}`} className="flex gap-4 rounded-xl border border-border bg-card p-4">
              <img src={l.image} alt={l.name} className="h-20 w-20 shrink-0 rounded-lg border border-border object-cover" />
              <div className="min-w-0 flex-1">
                <p className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">{l.supplier_name}</p>
                <h3 className="truncate text-sm font-semibold">{l.name}</h3>
                <p className="mt-0.5 text-sm text-muted-foreground">${l.unit.toFixed(2)} / unit · MOQ {l.moq}</p>
                <div className="mt-2 flex items-center gap-2">
                  <Button variant="outline" size="icon" className="h-8 w-8" onClick={() => updateQty(l.product_id, Math.max(1, l.quantity - 10))} data-testid={`cart-minus-${l.product_id}`}><Minus className="h-3.5 w-3.5" /></Button>
                  <Input type="number" value={l.quantity} onChange={(e) => updateQty(l.product_id, Math.max(1, parseInt(e.target.value) || 1))} className="h-8 w-20 text-center" data-testid={`cart-qty-${l.product_id}`} />
                  <Button variant="outline" size="icon" className="h-8 w-8" onClick={() => updateQty(l.product_id, l.quantity + 10)} data-testid={`cart-plus-${l.product_id}`}><Plus className="h-3.5 w-3.5" /></Button>
                </div>
              </div>
              <div className="flex flex-col items-end justify-between">
                <Button variant="ghost" size="icon" className="text-muted-foreground hover:text-rose-500" onClick={() => removeItem(l.product_id)} data-testid={`cart-remove-${l.product_id}`}><Trash2 className="h-4 w-4" /></Button>
                <p className="text-lg font-bold">${l.subtotal.toFixed(2)}</p>
              </div>
            </div>
          ))}
        </div>

        <div className="lg:col-span-5">
          <div className="sticky top-20 space-y-4 rounded-xl border border-border bg-card p-5">
            <h3 className="text-lg font-semibold">Delivery Details</h3>
            <div><Label htmlFor="addr">Delivery warehouse address</Label><Textarea id="addr" value={address} onChange={(e) => setAddress(e.target.value)} className="mt-1.5" rows={2} data-testid="checkout-address" placeholder="Warehouse / store address" /></div>
            <div><Label htmlFor="window">Delivery time window</Label>
              <select id="window" value={window} onChange={(e) => setWindow(e.target.value)} data-testid="checkout-window" className="mt-1.5 h-10 w-full rounded-md border border-input bg-background px-3 text-sm">
                {["9am - 12pm", "12pm - 3pm", "3pm - 6pm", "After hours"].map((w) => <option key={w}>{w}</option>)}
              </select>
            </div>
            <div><Label htmlFor="notes">Order notes</Label><Textarea id="notes" value={notes} onChange={(e) => setNotes(e.target.value)} className="mt-1.5" rows={2} data-testid="checkout-notes" placeholder="Special instructions..." /></div>
            <div className="border-t border-border pt-3">
              <div className="flex items-center justify-between text-sm text-muted-foreground"><span>Items</span><span>{lines.length}</span></div>
              <div className="mt-2 flex items-center justify-between"><span className="text-base font-semibold">Order Total</span><span className="text-2xl font-extrabold" data-testid="cart-total">${total.toFixed(2)}</span></div>
            </div>
            <Button className="h-12 w-full text-base" onClick={checkout} disabled={placing} data-testid="place-order-btn">
              {placing ? <Loader2 className="h-5 w-5 animate-spin" /> : <><Truck className="mr-2 h-5 w-5" /> Place Bulk Order</>}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
