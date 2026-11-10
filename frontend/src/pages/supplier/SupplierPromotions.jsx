import { useCallback, useEffect, useState } from "react";
import { api, requestErrorMessage } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Megaphone, Trash2 } from "lucide-react";
import { toast } from "sonner";

const localValue = (date) => new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
const STATUS_LABELS = { scheduled: "დაგეგმილი/აქტიური", active: "აქტიური", expired: "ვადაგასული", cancelled: "გაუქმებული" };

export default function SupplierPromotions() {
  const [products, setProducts] = useState([]);
  const [promotions, setPromotions] = useState([]);
  const [productId, setProductId] = useState("");
  const [promoPrice, setPromoPrice] = useState("");
  const [startsAt, setStartsAt] = useState(() => localValue(new Date()));
  const [endsAt, setEndsAt] = useState(() => localValue(new Date(Date.now() + 7 * 86400000)));
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    try {
      const [p, promos] = await Promise.all([api.get("/supplier/offers/products"), api.get("/supplier/promotions")]);
      setProducts(p.data);
      setProductId((current) => current || p.data[0]?.id || "");
      setPromotions(promos.data);
    } catch (error) {
      toast.error(requestErrorMessage(error));
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const product = products.find((p) => p.id === productId);

  const create = async () => {
    if (!productId || !(Number(promoPrice) > 0)) {
      toast.error("აირჩიეთ პროდუქტი და მიუთითეთ აქციური ფასი");
      return;
    }
    setBusy("create");
    try {
      await api.post("/supplier/promotions", {
        product_id: productId,
        promo_price: Number(promoPrice),
        starts_at: new Date(startsAt).toISOString(),
        ends_at: new Date(endsAt).toISOString(),
      });
      toast.success("აქცია შეიქმნა");
      setPromoPrice("");
      await load();
    } catch (error) {
      toast.error(requestErrorMessage(error));
    } finally {
      setBusy("");
    }
  };

  const act = async (promo, action) => {
    setBusy(promo.id);
    try {
      if (action === "broadcast") {
        const { data } = await api.post(`/supplier/promotions/${encodeURIComponent(promo.id)}/broadcast`);
        toast.success(`შეტყობინება გაეგზავნა ${data.sent_count} მაღაზიას`);
      } else {
        await api.delete(`/supplier/promotions/${encodeURIComponent(promo.id)}`);
        toast.success("აქცია გაუქმდა, ძველი ფასი აღდგა");
      }
      await load();
    } catch (error) {
      toast.error(requestErrorMessage(error));
    } finally {
      setBusy("");
    }
  };

  const running = (promo) => ["scheduled", "active"].includes(promo.status);

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">აქციები</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          აქციური პროდუქტები კატალოგში ავტომატურად ზევით გამოჩნდება და ვადის გასვლისას ძველ ფასს დაუბრუნდება.
          მაღაზიის ინდივიდუალური ფასი რჩება, თუ ის აქციურზე დაბალია.
        </p>
      </div>

      <div className="mb-8 grid gap-4 rounded-xl border border-border bg-card p-4 md:grid-cols-2">
        <div>
          <p className="mb-1 text-sm font-medium">პროდუქტი</p>
          <select value={productId} onChange={(e) => setProductId(e.target.value)} data-testid="promo-product"
            className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm">
            {products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          {product && <p className="mt-1 text-xs text-muted-foreground">სტანდარტული ფასი: ₾{Number(product.price_per_unit || 0).toFixed(2)}</p>}
        </div>
        <div>
          <p className="mb-1 text-sm font-medium">აქციური ფასი (₾)</p>
          <Input type="number" min="0" step="0.01" value={promoPrice} onChange={(e) => setPromoPrice(e.target.value)} data-testid="promo-price" />
        </div>
        <div>
          <p className="mb-1 text-sm font-medium">დაწყება</p>
          <Input type="datetime-local" value={startsAt} onChange={(e) => setStartsAt(e.target.value)} data-testid="promo-start" />
        </div>
        <div>
          <p className="mb-1 text-sm font-medium">დასრულება</p>
          <Input type="datetime-local" value={endsAt} onChange={(e) => setEndsAt(e.target.value)} data-testid="promo-end" />
        </div>
        <div className="md:col-span-2">
          <Button onClick={create} disabled={busy === "create"} data-testid="promo-create">აქციის შექმნა</Button>
        </div>
      </div>

      {promotions.length === 0 ? (
        <p className="rounded-xl border border-dashed border-border py-12 text-center text-sm text-muted-foreground">აქციები არ არის</p>
      ) : (
        <div className="space-y-3">
          {promotions.map((promo) => (
            <div key={promo.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-card p-4" data-testid={`promo-${promo.id}`}>
              <div className="min-w-0">
                <p className="truncate font-semibold">{promo.product_name}</p>
                <p className="text-sm text-muted-foreground">
                  ₾{Number(promo.base_price || 0).toFixed(2)} → <strong>₾{Number(promo.promo_price).toFixed(2)}</strong>
                </p>
                <p className="text-xs text-muted-foreground">
                  {new Date(promo.starts_at).toLocaleString()} — {new Date(promo.ends_at).toLocaleString()}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant={running(promo) ? "default" : "secondary"}>{STATUS_LABELS[promo.status] || promo.status}</Badge>
                {running(promo) && (
                  <>
                    <Button size="sm" variant="outline" disabled={busy === promo.id || !!promo.broadcast_at} onClick={() => act(promo, "broadcast")} data-testid={`promo-broadcast-${promo.id}`}>
                      <Megaphone className="mr-1 h-4 w-4" />{promo.broadcast_at ? "გაგზავნილია" : "შეტყობინების გაგზავნა"}
                    </Button>
                    <Button size="sm" variant="outline" className="text-rose-500" disabled={busy === promo.id} onClick={() => act(promo, "cancel")}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
