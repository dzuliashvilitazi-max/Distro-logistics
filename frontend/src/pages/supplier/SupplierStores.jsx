import { useCallback, useEffect, useMemo, useState } from "react";
import { api, requestErrorMessage } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Check, X, Tags, Store, Megaphone } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

const storeName = (c) => c.store?.business_name || c.store?.name || c.store_id;

function localDateTimeValue(date) {
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function remainingOfferTime(expiresAt, now) {
  const minutes = Math.ceil((new Date(expiresAt).getTime() - now) / 60000);
  if (minutes <= 0) return "ვადა ამოიწურა";
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  const rest = minutes % 60;
  if (days) return `დარჩა ${days} დღე ${hours} სთ`;
  if (hours) return `დარჩა ${hours} სთ ${rest} წთ`;
  return `დარჩა ${rest} წთ`;
}

export default function SupplierStores() {
  const [tab, setTab] = useState("PENDING");
  const [pending, setPending] = useState([]);
  const [active, setActive] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState("");
  const [pricingStore, setPricingStore] = useState(null);
  const [approvalMode, setApprovalMode] = useState(false);
  const [deleting, setDeleting] = useState(null);
  const [offerStoreIds, setOfferStoreIds] = useState(null);
  const [offers, setOffers] = useState([]);
  const [offerHistory, setOfferHistory] = useState([]);
  const [offerBusyId, setOfferBusyId] = useState("");

  const remove = async () => {
    setBusyId(deleting.store_id);
    try {
      await api.delete(`/connections/${encodeURIComponent(deleting.id)}`);
      toast.success("პარტნიორობა გაუქმებულია");
      setDeleting(null);
      await load();
    } catch (error) {
      toast.error(requestErrorMessage(error));
    } finally {
      setBusyId("");
    }
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [p, a, offerResponse] = await Promise.all([
        api.get("/connections/partners", { params: { status: "PENDING" } }),
        api.get("/connections/partners", { params: { status: "APPROVED" } }),
        api.get("/supplier/offers"),
      ]);
      setPending(p.data.filter((connection) => connection.requested_by_role !== "supplier"));
      setActive(a.data);
      setOffers(offerResponse.data.offers || []);
      setOfferHistory(offerResponse.data.history || []);
    } catch (error) {
      toast.error(requestErrorMessage(error));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const decide = async (connection, status) => {
    setBusyId(connection.store_id);
    try {
      await api.patch("/connections/approve", { store_id: connection.store_id, status });
      toast.success(status === "APPROVED" ? "მაღაზია დადასტურდა" : "მოთხოვნა უარყოფილია");
      if (status === "APPROVED") setTab("APPROVED");
      await load();
    } catch (error) {
      toast.error(requestErrorMessage(error));
    } finally {
      setBusyId("");
    }
  };

  const cancelOffer = async (offer) => {
    setOfferBusyId(offer.id);
    try {
      await api.delete(`/supplier/offers/${encodeURIComponent(offer.id)}`);
      toast.success("შეთავაზება გაუქმდა და სტანდარტული ფასი აღდგა");
      await load();
    } catch (error) {
      toast.error(requestErrorMessage(error));
    } finally {
      setOfferBusyId("");
    }
  };

  const rows = tab === "PENDING" ? pending : active;

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">ჩემი მაღაზიები</h1>
        <p className="mt-1 text-sm text-muted-foreground">მართეთ პარტნიორი მაღაზიები და მათი ინდივიდუალური ფასები.</p>
      </div>

      <div className="mb-5 flex flex-wrap items-center gap-2">
        <Button variant={tab === "PENDING" ? "default" : "outline"} onClick={() => setTab("PENDING")} data-testid="tab-pending">
          მოთხოვნები {pending.length > 0 && <Badge className="ml-2">{pending.length}</Badge>}
        </Button>
        <Button variant={tab === "APPROVED" ? "default" : "outline"} onClick={() => setTab("APPROVED")} data-testid="tab-active">
          აქტიური მაღაზიები ({active.length})
        </Button>
        {tab === "APPROVED" && active.length > 0 && (
          <Button variant="secondary" onClick={() => setOfferStoreIds([])} data-testid="bulk-product-offer">
            <Megaphone className="mr-2 h-4 w-4" />მასობრივი შეთავაზების გაგზავნა
          </Button>
        )}
      </div>

      {loading ? <p className="py-10 text-center text-sm text-muted-foreground">იტვირთება...</p>
        : rows.length === 0 ? <p className="rounded-xl border border-dashed border-border py-16 text-center text-sm text-muted-foreground">
          {tab === "PENDING" ? "ახალი მოთხოვნები არ არის" : "აქტიური მაღაზიები არ არის"}
        </p> : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {rows.map((c) => (
              <div key={c.store_id} className="flex flex-col justify-between rounded-xl border border-border bg-card p-4" data-testid={`store-card-${c.store_id}`}>
                <div className="flex items-start gap-3">
                  <Store className="mt-0.5 h-5 w-5 text-primary" />
                  <div className="min-w-0">
                    <p className="truncate font-semibold">{storeName(c)}</p>
                    <p className="text-xs text-muted-foreground">{[c.store?.city, c.store?.email, c.store?.phone].filter(Boolean).join(" · ")}</p>
                    {tab === "APPROVED" && <p className="mt-1 font-mono text-[11px] text-muted-foreground">ფასდაკლება: {Number(c.discount_percent || 0)}%</p>}
                  </div>
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  {tab === "PENDING" ? <>
                    <Button size="sm" disabled={busyId === c.store_id} onClick={() => { setApprovalMode(true); setPricingStore(c); }} data-testid={`approve-${c.store_id}`}><Check className="mr-1 h-4 w-4" />დადასტურება</Button>
                    <Button size="sm" variant="outline" disabled={busyId === c.store_id} onClick={() => decide(c, "REJECTED")} data-testid={`reject-${c.store_id}`}><X className="mr-1 h-4 w-4" />უარყოფა</Button>
                  </> : <>
                    <Button size="sm" onClick={() => { setApprovalMode(false); setPricingStore(c); }} data-testid={`pricing-${c.store_id}`}><Tags className="mr-1 h-4 w-4" />ინდივიდუალური ფასების მართვა / ფასდაკლება</Button>
                    <Button size="sm" variant="outline" onClick={() => setOfferStoreIds([c.store_id])} data-testid={`offer-${c.store_id}`}><Megaphone className="mr-1 h-4 w-4" />პროდუქციის შეთავაზება</Button>
                    <Button size="sm" variant="outline" className="text-rose-500" onClick={() => setDeleting(c)} data-testid={`delete-${c.store_id}`}>🗑️ წაშლა</Button>
                    <ProductOfferPanel
                      storeId={c.store_id}
                      offers={offers}
                      history={offerHistory}
                      busyOfferId={offerBusyId}
                      onCancel={cancelOffer}
                    />
                  </>}
                </div>
              </div>
            ))}
          </div>
        )}

      <PricingDialog
        connection={pricingStore}
        approval={approvalMode}
        onClose={() => setPricingStore(null)}
        onSaved={() => {
          if (approvalMode) setTab("APPROVED");
          load();
        }}
      />
      <ProductOfferDialog
        storeIds={offerStoreIds}
        stores={active}
        onClose={() => setOfferStoreIds(null)}
        onSaved={load}
      />
      <Dialog open={!!deleting} onOpenChange={(o) => !o && setDeleting(null)}>
        <DialogContent className="bg-card sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{deleting && storeName(deleting)}</DialogTitle>
            <DialogDescription>ნამდვილად გსურთ პარტნიორობის გაუქმება? ინდივიდუალური ფასები წაიშლება.</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleting(null)}>გაუქმება</Button>
            <Button variant="destructive" disabled={!!busyId} onClick={remove} data-testid="confirm-delete">წაშლა</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function ProductOfferDialog({ storeIds, stores, onClose, onSaved }) {
  const [products, setProducts] = useState([]);
  const [productId, setProductId] = useState("");
  const [offerPrice, setOfferPrice] = useState("");
  const [expiryMode, setExpiryMode] = useState("duration");
  const [durationDays, setDurationDays] = useState("3");
  const [expiresAt, setExpiresAt] = useState(() => localDateTimeValue(new Date(Date.now() + 3 * 86400000)));
  const [selectedStores, setSelectedStores] = useState([]);
  const [allStores, setAllStores] = useState(false);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    if (storeIds === null) return;
    let live = true;
    setLoading(true);
    setProductId("");
    setOfferPrice("");
    setExpiryMode("duration");
    setDurationDays("3");
    setExpiresAt(localDateTimeValue(new Date(Date.now() + 3 * 86400000)));
    setSelectedStores(storeIds);
    setAllStores(storeIds.length === 0);
    api.get("/supplier/offers/products")
      .then(({ data }) => {
        if (!live) return;
        setProducts(data);
        setProductId(data[0]?.id || "");
      })
      .catch((error) => toast.error(requestErrorMessage(error)))
      .finally(() => live && setLoading(false));
    return () => { live = false; };
  }, [storeIds]);

  const product = products.find((p) => p.id === productId);
  const targetStoreIds = allStores ? stores.map((s) => s.store_id) : selectedStores;

  const send = async () => {
    if (!productId || !offerPrice || !Number.isFinite(Number(offerPrice)) || Number(offerPrice) < 0) {
      toast.error("აირჩიეთ პროდუქტი და მიუთითეთ სწორი სპეციალური ფასი");
      return;
    }
    if (!targetStoreIds.length) {
      toast.error("აირჩიეთ მინიმუმ ერთი მაღაზია");
      return;
    }
    if (expiryMode === "date" && (!expiresAt || new Date(expiresAt) <= new Date())) {
      toast.error("მიუთითეთ ვადის გასვლის მომავალი თარიღი და დრო");
      return;
    }
    setSending(true);
    try {
      const { data } = await api.post("/supplier/offers", {
        product_id: productId,
        offer_price: Number(offerPrice),
        store_ids: targetStoreIds,
        ...(expiryMode === "duration"
          ? { duration_days: Number(durationDays) }
          : { expires_at: new Date(expiresAt).toISOString() }),
      });
      toast.success(`შეთავაზება გაეგზავნა ${data.sent_count} მაღაზიას`);
      onClose();
      onSaved?.();
    } catch (error) {
      toast.error(requestErrorMessage(error));
    } finally {
      setSending(false);
    }
  };

  return (
    <Dialog open={storeIds !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="bg-card sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>სპეციალური პროდუქტის შეთავაზება</DialogTitle>
          <DialogDescription>აირჩიეთ პროდუქტი და მიუთითეთ პარტნიორი მაღაზიისთვის შეთავაზებული ფასი.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <p className="mb-1 text-sm font-medium">პროდუქტი</p>
            <select value={productId} onChange={(e) => setProductId(e.target.value)} disabled={loading || products.length === 0}
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm" data-testid="offer-product-select">
              {products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
          {product && (
            <p className="rounded-md bg-secondary/50 p-3 text-sm">
              სტანდარტული ფასი: <strong>₾{Number(product.price_per_unit || 0).toFixed(2)}</strong>
            </p>
          )}
          <div>
            <p className="mb-1 text-sm font-medium">სპეციალური ფასი (₾)</p>
            <Input type="number" min="0" step="0.01" value={offerPrice} onChange={(e) => setOfferPrice(e.target.value)}
              placeholder="მაგ. 2.40" data-testid="offer-price" />
          </div>
          <div>
            <label htmlFor="offer-expiry-mode" className="mb-1 block text-sm font-medium">შეთავაზების ვადა</label>
            <select id="offer-expiry-mode" value={expiryMode} onChange={(e) => setExpiryMode(e.target.value)}
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm" data-testid="offer-expiry-mode">
              <option value="duration">ხანგრძლივობით</option>
              <option value="date">კონკრეტული თარიღით</option>
            </select>
            {expiryMode === "duration" ? (
              <select value={durationDays} onChange={(e) => setDurationDays(e.target.value)}
                className="mt-2 h-10 w-full rounded-md border border-input bg-background px-3 text-sm" data-testid="offer-duration-days">
                {[2, 3, 7, 14, 30].map((days) => <option key={days} value={days}>{days} დღე</option>)}
              </select>
            ) : (
              <Input type="datetime-local" min={localDateTimeValue(new Date())} value={expiresAt}
                onChange={(e) => setExpiresAt(e.target.value)} className="mt-2" data-testid="offer-expires-at" />
            )}
          </div>
          {storeIds?.length === 0 && (
            <div className="space-y-2 rounded-md border border-border p-3">
              <label className="flex cursor-pointer items-center gap-2 text-sm font-medium">
                <input type="checkbox" checked={allStores} onChange={(e) => {
                  const checked = e.target.checked;
                  setAllStores(checked);
                  setSelectedStores(checked ? stores.map((s) => s.store_id) : []);
                }} data-testid="offer-all-stores" />
                ყველა მაღაზიის მონიშვნა
              </label>
              {!allStores && stores.map((store) => (
                <label key={store.store_id} className="flex cursor-pointer items-center gap-2 text-sm">
                  <input type="checkbox" checked={selectedStores.includes(store.store_id)} onChange={(e) => {
                    setSelectedStores((current) => e.target.checked
                      ? [...current, store.store_id]
                      : current.filter((id) => id !== store.store_id));
                  }} />
                  {storeName(store)}
                </label>
              ))}
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>გაუქმება</Button>
          <Button onClick={send} disabled={sending || loading || !products.length} data-testid="send-product-offer">
            {sending ? "იგზავნება..." : "შეთავაზების გაგზავნა"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ProductOfferPanel({ storeId, offers, history, busyOfferId, onCancel }) {
  const [expanded, setExpanded] = useState(false);
  const [now, setNow] = useState(Date.now());
  const storeOffers = offers.filter((offer) => offer.store_id === storeId && offer.status === "active");
  const storeHistory = history.filter((event) => event.store_id === storeId).slice(0, 5);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <div className="mt-3 w-full border-t border-border pt-3">
      <button type="button" onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center justify-between gap-3 text-left text-xs font-semibold">
        <span>სპეციალური შეთავაზებები</span>
        <span className="rounded border border-processing/30 bg-processing/10 px-2 py-0.5 font-mono text-processing">
          {storeOffers.length} აქტიური
        </span>
      </button>
      {expanded && (
        <div className="mt-3 space-y-2">
          {storeOffers.map((offer) => {
            const expired = new Date(offer.expiresAt).getTime() <= now;
            return (
              <div key={offer.id} className="rounded-md border border-border bg-secondary/30 p-3" data-testid={`active-offer-${offer.id}`}>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-xs font-semibold">{offer.product_name}</p>
                    <p className="mt-1 font-mono text-sm font-bold text-processing">₾{Number(offer.offer_price).toFixed(2)}</p>
                  </div>
                  <span className={`rounded border px-2 py-1 text-[10px] font-semibold ${expired ? "border-destructive/30 text-destructive" : "border-delivered/30 text-delivered"}`}>
                    {remainingOfferTime(offer.expiresAt, now)}
                  </span>
                </div>
                <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                  <p className="text-[10px] text-muted-foreground">
                    გაგზავნილია {new Date(offer.created_at).toLocaleString("ka-GE")} · ვადა: {new Date(offer.expiresAt).toLocaleString("ka-GE")}
                  </p>
                  <Button size="sm" variant="outline" disabled={expired || busyOfferId === offer.id}
                    onClick={() => onCancel(offer)} className="h-8 text-[11px] text-destructive hover:text-destructive" data-testid={`cancel-offer-${offer.id}`}>
                    შეთავაზების გაუქმება
                  </Button>
                </div>
              </div>
            );
          })}
          {storeOffers.length === 0 && <p className="text-xs text-muted-foreground">აქტიური შეთავაზება არ არის.</p>}
          {storeHistory.length > 0 && (
            <details className="rounded-md border border-border px-3 py-2">
              <summary className="cursor-pointer text-xs font-medium">შეთავაზებების ისტორია</summary>
              <ul className="mt-2 space-y-1.5">
                {storeHistory.map((event) => (
                  <li key={event.id} className="flex flex-wrap justify-between gap-x-3 text-[10px] text-muted-foreground">
                    <span>{event.product_name} · ₾{Number(event.offer_price).toFixed(2)} · {event.action}</span>
                    <time>{new Date(event.at).toLocaleString("ka-GE")}</time>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

function PricingDialog({ connection, approval = false, onClose, onSaved }) {
  const [products, setProducts] = useState([]);
  const [discount, setDiscount] = useState("0");
  const [prices, setPrices] = useState({});
  const [original, setOriginal] = useState({});
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [customMode, setCustomMode] = useState(false);

  useEffect(() => {
    if (!connection) return;
    let live = true;
    setLoading(true);
    setSearch("");
    setCustomMode(false);
    api.get(`/supplier/stores/${encodeURIComponent(connection.store_id)}/pricing`)
      .then(({ data }) => {
        if (!live) return;
        const initial = Object.fromEntries(data.products.map((p) => [p.id, p.custom_price == null ? "" : String(p.custom_price)]));
        setProducts(data.products);
        setDiscount(String(data.discount_percent ?? 0));
        setPrices(initial);
        setOriginal(initial);
      })
      .catch((error) => toast.error(requestErrorMessage(error)))
      .finally(() => live && setLoading(false));
    return () => { live = false; };
  }, [connection]);

  const discountValue = Math.min(100, Math.max(0, parseFloat(discount) || 0));
  const visible = useMemo(() => products.filter((p) => p.name.toLowerCase().includes(search.trim().toLowerCase())), [products, search]);

  const finalPrice = (p) => {
    const custom = prices[p.id];
    if (custom !== "" && custom != null && !Number.isNaN(parseFloat(custom))) return parseFloat(custom);
    return Math.round(Number(p.price_per_unit || 0) * (1 - discountValue / 100) * 100) / 100;
  };

  const standardApproval = async () => {
    setSaving(true);
    try {
      await api.patch("/connections/approve", {
        store_id: connection.store_id,
        status: "APPROVED",
        discount_percent: 0,
        custom_prices: [],
      });
      toast.success("მაღაზია დადასტურდა საბაზო ფასებით");
      onSaved();
      onClose();
    } catch (error) {
      toast.error(requestErrorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  const save = async () => {
    const changed = products.filter((p) => (prices[p.id] ?? "") !== (original[p.id] ?? ""));
    for (const p of changed) {
      const v = prices[p.id];
      if (v !== "" && (Number.isNaN(parseFloat(v)) || parseFloat(v) < 0)) {
        toast.error(`არასწორი ფასი: ${p.name}`);
        return;
      }
    }
    setSaving(true);
    try {
      if (approval) {
        await api.patch("/connections/approve", {
          store_id: connection.store_id,
          status: "APPROVED",
          discount_percent: discountValue,
          custom_prices: products
            .filter((p) => prices[p.id] !== "" && prices[p.id] != null)
            .map((p) => ({ product_id: p.id, custom_price: parseFloat(prices[p.id]) })),
        });
        toast.success("მაღაზია დადასტურდა შეთავაზებული ფასებით");
      } else {
        await api.put(`/supplier/stores/${encodeURIComponent(connection.store_id)}/pricing`, {
          discount_percent: discountValue,
          custom_prices: changed.map((p) => ({ product_id: p.id, custom_price: prices[p.id] === "" ? null : parseFloat(prices[p.id]) })),
        });
        toast.success("ფასები შენახულია");
      }
      onSaved();
      onClose();
    } catch (error) {
      toast.error(requestErrorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={!!connection} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className={cn("bg-card", approval ? "sm:max-w-3xl" : "sm:max-w-3xl")}>
        <DialogHeader>
          <DialogTitle>{approval ? "პარტნიორობის მოთხოვნის დადასტურება" : `ფასები: ${connection && storeName(connection)}`}</DialogTitle>
          {approval ? (
            <DialogDescription>გადაამოწმეთ მაღაზიის მონაცემები და აირჩიეთ ფასების შეთავაზება.</DialogDescription>
          ) : (
            <DialogDescription>დააყენეთ საერთო ფასდაკლება ან ინდივიდუალური ფასი თითოეულ პროდუქტზე. ცარიელი ველი = ბაზისური ფასი − ფასდაკლება.</DialogDescription>
          )}
        </DialogHeader>
        {approval && connection && (
          <div className="grid grid-cols-1 gap-3 rounded-lg border border-border bg-secondary/30 p-4 text-sm sm:grid-cols-2" data-testid="approval-store-details">
            <p><span className="text-muted-foreground">მაღაზია:</span> {storeName(connection)}</p>
            <p><span className="text-muted-foreground">ელ.ფოსტა:</span> {connection.store?.email || "—"}</p>
            <p><span className="text-muted-foreground">ტელეფონი:</span> {connection.store?.phone || "—"}</p>
            <p><span className="text-muted-foreground">ს.კ.:</span> {connection.store?.identification_number || "—"}</p>
            <p className="sm:col-span-2"><span className="text-muted-foreground">მისამართი:</span> {connection.store?.address || "—"}</p>
          </div>
        )}
        {approval && !customMode ? (
          <DialogFooter className="flex-col gap-2 sm:flex-row">
            <Button variant="outline" onClick={onClose}>გაუქმება</Button>
            <Button variant="outline" disabled={saving || loading} onClick={() => setCustomMode(true)} data-testid="offer-custom-pricing">
              <Tags className="mr-1.5 h-4 w-4" />ინდივიდუალური ფასების შეთავაზება
            </Button>
            <Button disabled={saving || loading} onClick={standardApproval} data-testid="approve-standard-prices">
              {saving ? "მუშავდება..." : "სტანდარტული ფასებით დადასტურება"}
            </Button>
          </DialogFooter>
        ) : (
          <>
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <p className="mb-1 font-mono text-[11px] uppercase text-muted-foreground">საერთო ფასდაკლება (%)</p>
            <Input type="number" min="0" max="100" step="0.1" value={discount} onChange={(e) => setDiscount(e.target.value)} className="w-36" data-testid="global-discount" />
          </div>
          <Input placeholder="პროდუქტის ძებნა..." value={search} onChange={(e) => setSearch(e.target.value)} className="flex-1" />
        </div>
        <div className="max-h-[50vh] overflow-y-auto rounded-lg border border-border">
          {loading ? <p className="p-6 text-center text-sm text-muted-foreground">იტვირთება...</p> : (
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-secondary text-left font-mono text-[11px] uppercase text-muted-foreground">
                <tr><th className="p-2">პროდუქტი</th><th className="p-2">ბაზისური</th><th className="p-2">ინდივ. ფასი</th><th className="p-2">საბოლოო</th></tr>
              </thead>
              <tbody>
                {visible.map((p) => (
                  <tr key={p.id} className="border-t border-border">
                    <td className="p-2 font-medium">{p.name}</td>
                    <td className="p-2">₾{Number(p.price_per_unit || 0).toFixed(2)}</td>
                    <td className="p-2">
                      <Input type="number" min="0" step="0.01" value={prices[p.id] ?? ""} placeholder="—" className="h-8 w-28"
                        onChange={(e) => setPrices((prev) => ({ ...prev, [p.id]: e.target.value }))} data-testid={`custom-price-${p.id}`} />
                    </td>
                    <td className={cn("p-2 font-bold", prices[p.id] ? "text-primary" : "")}>₾{finalPrice(p).toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={approval ? () => setCustomMode(false) : onClose}>{approval ? "უკან" : "გაუქმება"}</Button>
          <Button onClick={save} disabled={saving || loading} data-testid={approval ? "approve-custom-prices" : "save-pricing"}>
            {saving ? "ინახება..." : approval ? "ინდივიდუალური ფასებით დადასტურება" : "შენახვა"}
          </Button>
        </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
