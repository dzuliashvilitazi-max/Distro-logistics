import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, formatApiError } from "@/lib/api";
import ProductImage from "@/components/ProductImage";
import { useI18n } from "@/context/I18nContext";
import { StatusBadge } from "@/components/StatusBadge";
import { PaymentBadge } from "@/pages/admin/AdminOrders";
import AddressMapPicker from "@/components/AddressMapPicker";
import { Check, X, Truck, Package, ClipboardList, FileDown, Loader2, Plus, Wallet, UserRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

const ORDERS_PAGE_SIZE = 50;

const TABS = ["All", "Pending Payment", "Pending", "Processing", "In Transit", "Delivered", "Cancelled"];
const NEXT = { Pending: "Processing", Processing: "In Transit", "In Transit": "Delivered" };

const PAY_STYLE = {
  PAID: "border-emerald-500/40 bg-emerald-500/10 text-emerald-500",
  PARTIAL: "border-amber-500/40 bg-amber-500/10 text-amber-500",
  UNPAID: "border-border bg-secondary/40 text-muted-foreground",
};

export default function SupplierOrders() {
  const { t: tr } = useI18n();
  const [orders, setOrders] = useState([]);
  const [tab, setTab] = useState("All");
  const [selectedIds, setSelectedIds] = useState(() => new Set());
  const [drivers, setDrivers] = useState([]);
  const [bulkDriverId, setBulkDriverId] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);
  const [payOrder, setPayOrder] = useState(null);
  const [rejectOrder, setRejectOrder] = useState(null);
  const [waybillOrder, setWaybillOrder] = useState(null);
  const [showManualOrder, setShowManualOrder] = useState(false);
  const [creatingManualOrder, setCreatingManualOrder] = useState(false);
  const [savedStores, setSavedStores] = useState([]);
  const [selectedStoreId, setSelectedStoreId] = useState("");
  const [loadingStores, setLoadingStores] = useState(false);
  const [externalOrder, setExternalOrder] = useState(true);
  const [manualOrder, setManualOrder] = useState({
    customer_name: "", customer_phone: "", delivery_address: "", item_name: "",
    city: "", lat: null, lng: null, quantity: "1", unit_price: "", notes: "", delivery_window: "",
  });
  const [searchParams] = useSearchParams();
  const requestedOrderId = searchParams.get("order");

  const load = useCallback(() => api.get("/orders").then((r) => setOrders(r.data)), []);
  useEffect(() => { load(); const iv = setInterval(load, 7000); return () => clearInterval(iv); }, [load]);
  useEffect(() => {
    if (!requestedOrderId || !orders.some((order) => order.id === requestedOrderId)) return undefined;
    setTab("All");
    const timer = setTimeout(() => {
      document.getElementById(`supplier-order-${requestedOrderId}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 0);
    return () => clearTimeout(timer);
  }, [orders, requestedOrderId]);

  const update = async (id, status, reason) => {
    try { await api.put(`/orders/${id}/status`, { status, reason }); toast.success(`${tr("orders.orderMarked")} ${tr(`status.${status === "REJECTED" ? "Rejected" : status}`)}`); load(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const confirmBankTransfer = async (id) => {
    try {
      await api.post(`/supplier/orders/${id}/confirm-bank-transfer`);
      toast.success(tr("orders.confirmBankTransfer"));
      load();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    }
  };
  useEffect(() => {
    api.get("/drivers").then((r) => setDrivers(r.data.filter((d) => d.active !== false))).catch(() => setDrivers([]));
  }, []);
  const toggleSelected = (id) => setSelectedIds((current) => {
    const next = new Set(current);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const runBulk = async (path, payload) => {
    setBulkBusy(true);
    try {
      const { data } = await api.post(path, { order_ids: [...selectedIds], ...payload });
      toast.success(`${tr("bulk.done")}: ${data.updated.length}${data.skipped.length ? ` · ${tr("bulk.skipped")}: ${data.skipped.length} (${data.skipped[0].reason})` : ""}`);
      setSelectedIds(new Set());
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBulkBusy(false); }
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
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail) || "Invoice unavailable"); }
  };
  const toggleManualOrder = async () => {
    if (showManualOrder) {
      setShowManualOrder(false);
      return;
    }
    setShowManualOrder(true);
    setLoadingStores(true);
    try {
      const { data } = await api.get("/supplier/stores");
      setSavedStores(data);
    } catch (error) {
      console.error("Could not load saved delivery stores:", error);
      toast.error(formatApiError(error.response?.data?.detail) || tr("orders.savedStoresError"));
    } finally {
      setLoadingStores(false);
    }
  };
  const selectSavedStore = (storeId) => {
    setSelectedStoreId(storeId);
    const store = savedStores.find((savedStore) => savedStore.id === storeId);
    if (store) {
      setManualOrder((current) => ({
        ...current,
        customer_name: store.name || "",
        customer_phone: store.phone || "",
        delivery_address: store.address || "",
        city: store.city || "",
        lat: store.route_coordinates?.lat ?? null,
        lng: store.route_coordinates?.lng ?? store.route_coordinates?.lon ?? null,
      }));
    }
  };
  const createManualOrder = async (event) => {
    event.preventDefault();
    if (!Number.isFinite(manualOrder.lat) || !Number.isFinite(manualOrder.lng) || !manualOrder.delivery_address) {
      toast.error(tr("checkout.pinAddress"));
      return;
    }
    setCreatingManualOrder(true);
    try {
      await api.post("/external-orders", {
        ...manualOrder,
        quantity: Number(manualOrder.quantity),
        unit_price: Number(manualOrder.unit_price),
        external_order: externalOrder,
      });
      setManualOrder({
        customer_name: "", customer_phone: "", delivery_address: "", item_name: "",
        city: "", lat: null, lng: null, quantity: "1", unit_price: "", notes: "", delivery_window: "",
      });
      setSelectedStoreId("");
      setShowManualOrder(false);
      toast.success(tr("orders.externalCreated"));
      await load();
    } catch (error) {
      console.error("Could not create external delivery order:", error);
      toast.error(formatApiError(error.response?.data?.detail) || tr("orders.externalCreateError"));
    } finally {
      setCreatingManualOrder(false);
    }
  };

  const filtered = useMemo(() => (tab === "All" ? orders : orders.filter((o) => o.status === tab)), [orders, tab]);
  const statusCounts = useMemo(() => orders.reduce((acc, o) => ({ ...acc, [o.status]: (acc[o.status] || 0) + 1 }), {}), [orders]);
  const [visibleCount, setVisibleCount] = useState(ORDERS_PAGE_SIZE);
  useEffect(() => { setVisibleCount(ORDERS_PAGE_SIZE); }, [tab]);
  const visibleOrders = useMemo(() => filtered.slice(0, visibleCount), [filtered, visibleCount]);
  const allSelected = filtered.length > 0 && filtered.every((o) => selectedIds.has(o.id));
  const toggleAll = () => setSelectedIds(allSelected ? new Set() : new Set(filtered.map((o) => o.id)));

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{tr("orders.orderManagement")}</h1>
        <Button type="button" variant="outline" onClick={toggleManualOrder} data-testid="add-external-order-button">
          <Plus className="mr-2 h-4 w-4" />{tr("orders.addExternal")}
        </Button>
      </div>
      {showManualOrder && (
        <form onSubmit={createManualOrder} className="mb-6 space-y-4 rounded-xl border border-highlight/30 bg-card p-5" data-testid="external-order-form">
          <div>
            <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.14em] text-highlight">{tr("orders.externalTitle")}</p>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{tr("orders.externalDescription")}</p>
          </div>
          <label className="block max-w-xl space-y-1 text-xs text-muted-foreground">
            <span>{tr("orders.quickSelectStore")}</span>
            <select
              value={selectedStoreId}
              onChange={(event) => selectSavedStore(event.target.value)}
              disabled={loadingStores}
              className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground"
              data-testid="quick-select-store"
            >
              <option value="">{loadingStores ? tr("orders.loadingSavedStores") : tr("orders.chooseSavedStore")}</option>
              {savedStores.map((store) => (
                <option key={store.id} value={store.id}>
                  {store.name}{store.address ? ` · ${store.address}` : ""}
                </option>
              ))}
            </select>
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="space-y-1 text-xs text-muted-foreground">{tr("orders.customerName")}
              <Input required maxLength={160} value={manualOrder.customer_name} onChange={(event) => setManualOrder((current) => ({ ...current, customer_name: event.target.value }))} />
            </label>
            <label className="space-y-1 text-xs text-muted-foreground">{tr("orders.customerPhone")}
              <Input type="tel" maxLength={40} value={manualOrder.customer_phone} onChange={(event) => setManualOrder((current) => ({ ...current, customer_phone: event.target.value }))} />
            </label>
            <div className="sm:col-span-2"><AddressMapPicker value={manualOrder} onChange={(location) => setManualOrder((current) => ({ ...current, ...location }))} /></div>
            <label className="space-y-1 text-xs text-muted-foreground">{tr("orders.deliveryWindow")}
              <Input maxLength={120} value={manualOrder.delivery_window} onChange={(event) => setManualOrder((current) => ({ ...current, delivery_window: event.target.value }))} />
            </label>
            <label className="space-y-1 text-xs text-muted-foreground">{tr("orders.itemName")}
              <Input required maxLength={200} value={manualOrder.item_name} onChange={(event) => setManualOrder((current) => ({ ...current, item_name: event.target.value }))} />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="space-y-1 text-xs text-muted-foreground">{tr("orders.quantity")}
                <Input required type="number" min="1" max="100000" step="1" value={manualOrder.quantity} onChange={(event) => setManualOrder((current) => ({ ...current, quantity: event.target.value }))} />
              </label>
              <label className="space-y-1 text-xs text-muted-foreground">{tr("orders.unitPrice")}
                <Input required type="number" min="0" step="0.01" value={manualOrder.unit_price} onChange={(event) => setManualOrder((current) => ({ ...current, unit_price: event.target.value }))} />
              </label>
            </div>
          </div>
          <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-border bg-secondary/30 p-3 text-sm">
            <input type="checkbox" checked={externalOrder} onChange={(event) => setExternalOrder(event.target.checked)} className="mt-1 accent-[hsl(var(--primary))]" data-testid="external-order-checkbox" />
            <span>
              <span className="font-medium text-foreground">{tr("orders.externalCheckbox")}</span>
              <span className="mt-1 block text-xs leading-relaxed text-muted-foreground">{tr("orders.externalDisclaimer")}</span>
            </span>
          </label>
          <label className="block space-y-1 text-xs text-muted-foreground">{tr("orders.notes")}
            <Textarea maxLength={1000} rows={2} value={manualOrder.notes} onChange={(event) => setManualOrder((current) => ({ ...current, notes: event.target.value }))} />
          </label>
          <div className="flex justify-end">
            <Button type="submit" disabled={creatingManualOrder || !externalOrder} data-testid="create-external-order-button">
              {creatingManualOrder ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Plus className="mr-2 h-4 w-4" />}
              {tr("orders.createExternal")}
            </Button>
          </div>
        </form>
      )}
      <div className="mb-6 flex flex-wrap gap-2">
        {TABS.map((tb) => (
          <button key={tb} onClick={() => setTab(tb)} data-testid={`order-tab-${tb.replace(/\s/g, "-")}`}
            className={cn("rounded-full border px-3.5 py-1.5 text-sm font-medium transition-colors duration-200", tab === tb ? "border-primary bg-primary text-primary-foreground" : "border-border text-muted-foreground hover:text-foreground")}>
            {tb === "All" ? tr("usr.all") : tr(`status.${tb}`)} {tb !== "All" && <span className="font-mono">({statusCounts[tb] || 0})</span>}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border py-20 text-center"><ClipboardList className="h-10 w-10 text-muted-foreground" /><p className="mt-3 text-sm text-muted-foreground">{tr("orders.noOrdersView")}</p></div>
      ) : (
        <div className="space-y-4">
          <label className="flex w-fit cursor-pointer items-center gap-2 text-sm text-muted-foreground">
            <input type="checkbox" checked={allSelected} onChange={toggleAll} className="h-4 w-4 accent-[hsl(var(--primary))]" data-testid="select-all-orders" />
            {tr("bulk.selectAll")}
          </label>
          {visibleOrders.map((o) => (
            <div key={o.id} id={`supplier-order-${o.id}`} data-testid={`supplier-order-${o.id}`} className={cn("rounded-xl border bg-card p-5", selectedIds.has(o.id) ? "border-primary" : "border-border")}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <input type="checkbox" checked={selectedIds.has(o.id)} onChange={() => toggleSelected(o.id)} className="mt-1 h-4 w-4 accent-[hsl(var(--primary))]" aria-label={o.order_no} data-testid={`select-order-${o.id}`} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2.5"><p className="font-mono text-sm font-bold">{o.order_no}</p><StatusBadge status={o.rejected && o.status === "Cancelled" ? "Rejected" : o.status} /><PaymentBadge method={o.payment_method} />
                    {!o.external_order && <span className={cn("rounded-full border px-2 py-0.5 text-[10px] font-semibold", PAY_STYLE[o.paymentStatus || "UNPAID"])} data-testid={`payment-status-${o.id}`}>{tr(`pay.${o.paymentStatus || "UNPAID"}`)}{o.paymentStatus === "PARTIAL" && ` · ${tr("pay.balance")} ₾${Number(o.balance).toFixed(2)}`}</span>}
                    {o.external_order && <span className="rounded-full border border-highlight/30 bg-highlight/10 px-2 py-0.5 text-[10px] font-semibold text-highlight">{tr("orders.externalBadge")}</span>}</div>
                  <p className="mt-1 text-sm text-muted-foreground">{tr("orders.from")} <span className="font-medium text-foreground">{o.retailer_name}</span> · {new Date(o.created_at).toLocaleString()}</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">{tr("orders.deliverTo")}: {o.delivery_address} · {o.delivery_window}</p>
                  {o.assigned_driver_name && <p className="mt-0.5 text-xs text-muted-foreground">{tr("orders.assignedDriver")}: {o.assigned_driver_name}</p>}
                  {o.rejected && o.rejection_reason && <p className="mt-0.5 text-xs text-rose-500">{o.rejection_reason}</p>}
                  {(o.retailer_establishment || o.retailer_tax_id) && <p className="mt-0.5 text-xs text-muted-foreground">{tr("orders.establishment")}: {o.retailer_establishment ? tr(`est.${o.retailer_establishment}`) : "—"} · {tr("orders.taxId")}: {o.retailer_tax_id || "—"}</p>}
                </div>
                <p className="text-xl font-extrabold">₾{o.total.toFixed(2)}</p>
              </div>

              <div className="my-3 space-y-1.5 border-y border-border py-3">
                {o.items.map((i) => (
                  <div key={i.product_id} className="flex items-center gap-3 text-sm"><ProductImage image={i.image} name={i.name} alt="" className="h-9 w-9 rounded border border-border object-cover" /><span className="flex-1 truncate">{i.name}</span><span className="font-mono text-muted-foreground">{i.quantity} × {i.list_price > i.unit_price && <s className="mr-1">₾{i.list_price.toFixed(2)}</s>}₾{i.unit_price.toFixed(2)}</span></div>
                ))}
                {o.commission_breakdown && (
                  <dl className="mt-2 space-y-0.5 rounded-md bg-secondary/40 p-2.5 text-xs" data-testid={`commission-breakdown-${o.id}`}>
                    <div className="flex justify-between"><dt className="text-muted-foreground">საბაზისო თანხა</dt><dd className="font-mono">₾{Number(o.commission_breakdown.base_amount).toFixed(2)}</dd></div>
                    <div className="flex justify-between"><dt className="text-muted-foreground">პლატფორმის საკომისიო{o.commission_breakdown.fee_type === "percent" ? ` (${o.commission_breakdown.fee_value}%)` : ""}</dt><dd className="font-mono">−₾{Number(o.commission_breakdown.commission).toFixed(2)}</dd></div>
                    <div className="flex justify-between border-t border-border pt-0.5 font-semibold"><dt>თქვენთვის გადასახდელი</dt><dd className="font-mono">₾{Number(o.commission_breakdown.distributor_net).toFixed(2)}</dd></div>
                  </dl>
                )}
                {o.notes && <p className="pt-1 text-xs text-muted-foreground"><span className="font-semibold text-foreground">{tr("orders.notes")}:</span> {o.notes}</p>}
              </div>

              <div className="flex flex-wrap gap-2">
                {o.status === "Pending Payment" && o.payment_method === "bank_transfer" && (
                  <Button size="sm" onClick={() => confirmBankTransfer(o.id)} data-testid={`confirm-transfer-${o.id}`}>
                    <Wallet className="mr-1 h-4 w-4" /> {tr("orders.confirmBankTransfer")}
                  </Button>
                )}
                {o.status === "Pending" && (
                  <>
                    <Button size="sm" onClick={() => update(o.id, "Processing")} data-testid={`accept-order-${o.id}`}><Check className="mr-1 h-4 w-4" /> {tr("orders.accept")}</Button>
                    <Button size="sm" variant="outline" className="text-rose-500 hover:bg-rose-500/10" onClick={() => setRejectOrder(o)} data-testid={`reject-order-${o.id}`}><X className="mr-1 h-4 w-4" /> {tr("orders.reject")}</Button>
                  </>
                )}
                {NEXT[o.status] && o.status !== "Pending" && (
                  <Button size="sm" onClick={() => update(o.id, NEXT[o.status])} data-testid={`advance-order-${o.id}`}><Truck className="mr-1 h-4 w-4" /> {tr("orders.markAs")} {tr(`status.${NEXT[o.status]}`)}</Button>
                )}
                {o.status === "Delivered" && <span className="flex items-center gap-1.5 text-sm font-medium text-delivered"><Package className="h-4 w-4" /> {tr("orders.fulfilled")}</span>}
                {["Processing", "In Transit", "Delivered"].includes(o.status) && !o.external_order && (
                  <Button size="sm" variant="outline" onClick={() => downloadInvoice(o)} data-testid={`invoice-pdf-${o.id}`}>
                    <FileDown className="mr-1.5 h-4 w-4" />{tr("orders.invoicePdf")}
                  </Button>
                )}
                {!o.external_order && o.status !== "Cancelled" && o.paymentStatus !== "PAID" && (
                  <Button size="sm" variant="outline" onClick={() => setPayOrder(o)} data-testid={`mark-paid-${o.id}`}>
                    <Wallet className="mr-1.5 h-4 w-4" />{tr("pay.markPaid")}
                  </Button>
                )}
                {["Processing", "In Transit", "Delivered"].includes(o.status) && (
                  <Button size="sm" variant="outline" onClick={() => setWaybillOrder(o)} data-testid={`generate-waybill-${o.id}`}>
                    <FileDown className="mr-1.5 h-4 w-4" />{tr("waybill.download")}
                  </Button>
                )}
              </div>
            </div>
          ))}
          {filtered.length > visibleCount && (
            <div className="flex justify-center pt-2">
              <Button variant="outline" onClick={() => setVisibleCount((n) => n + ORDERS_PAGE_SIZE)} data-testid="orders-show-more">
                {tr("common.showMore")} ({filtered.length - visibleCount})
              </Button>
            </div>
          )}
        </div>
      )}
      <WaybillDialog order={waybillOrder} drivers={drivers} onClose={() => setWaybillOrder(null)} />
      <PaymentDialog order={payOrder} onClose={() => setPayOrder(null)} onSaved={load} />
      <RejectDialog order={rejectOrder} onClose={() => setRejectOrder(null)} onReject={(reason) => update(rejectOrder.id, "REJECTED", reason)} />
      {selectedIds.size > 0 && (
        <div className="fixed inset-x-3 bottom-4 z-40 mx-auto flex max-w-3xl flex-wrap items-center gap-2 rounded-xl border border-primary/40 bg-card p-3 shadow-xl" data-testid="bulk-action-bar">
          <span className="px-2 text-sm font-semibold">{selectedIds.size} {tr("bulk.selected")}</span>
          <Button size="sm" disabled={bulkBusy} onClick={() => runBulk("/supplier/orders/bulk-status", { status: "APPROVED" })} data-testid="bulk-approve"><Check className="mr-1 h-4 w-4" />{tr("bulk.approve")}</Button>
          <Button size="sm" variant="outline" disabled={bulkBusy} onClick={() => runBulk("/supplier/orders/bulk-status", { status: "IN_TRANSIT" })} data-testid="bulk-in-transit"><Truck className="mr-1 h-4 w-4" />{tr("bulk.inTransit")}</Button>
          <select value={bulkDriverId} onChange={(e) => setBulkDriverId(e.target.value)} className="h-9 rounded-md border border-input bg-background px-2 text-sm" data-testid="bulk-driver-select">
            <option value="">{tr("bulk.chooseDriver")}</option>
            {drivers.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
          <Button size="sm" variant="outline" disabled={bulkBusy || !bulkDriverId} onClick={() => runBulk("/supplier/orders/bulk-assign-driver", { driver_id: bulkDriverId })} data-testid="bulk-assign-driver"><UserRound className="mr-1 h-4 w-4" />{tr("bulk.assignDriver")}</Button>
          <Button size="sm" variant="ghost" className="ml-auto" onClick={() => setSelectedIds(new Set())}>{tr("bulk.clear")}</Button>
        </div>
      )}
    </div>
  );
}

function PaymentDialog({ order, onClose, onSaved }) {
  const { t } = useI18n();
  const [mode, setMode] = useState("full");
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState("cash");
  const [busy, setBusy] = useState(false);
  const balance = Number(order?.balance ?? 0);

  useEffect(() => { setMode("full"); setAmount(""); setMethod("cash"); }, [order]);

  const submit = async (event) => {
    event.preventDefault();
    const value = mode === "full" ? balance : Math.round(Number(amount) * 100) / 100;
    if (!(value > 0) || value > balance) { toast.error(t("pay.invalidAmount")); return; }
    setBusy(true);
    try {
      await api.post(`/supplier/orders/${order.id}/payments`, { amount: value, method });
      toast.success(t("pay.recorded"));
      onSaved();
      onClose();
    } catch (error) { toast.error(formatApiError(error.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  return (
    <Dialog open={!!order} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("pay.title")} · {order?.order_no}</DialogTitle>
          <DialogDescription>{t("pay.balance")}: ₾{balance.toFixed(2)} / ₾{Number(order?.total ?? 0).toFixed(2)}</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <div className="grid grid-cols-2 gap-2">
            {["full", "partial"].map((value) => (
              <button type="button" key={value} onClick={() => setMode(value)} data-testid={`pay-mode-${value}`}
                className={cn("rounded-lg border px-3 py-2 text-sm", mode === value ? "border-primary bg-primary/10 font-semibold" : "border-border")}>
                {t(`pay.${value}`)}
              </button>
            ))}
          </div>
          {mode === "partial" && (
            <div><Label htmlFor="pay-amount">{t("pay.amount")}</Label>
              <Input id="pay-amount" type="number" min="0.01" max={balance} step="0.01" required value={amount} onChange={(e) => setAmount(e.target.value)} className="mt-1.5" data-testid="pay-amount" /></div>
          )}
          <div><Label htmlFor="pay-method">{t("pay.method")}</Label>
            <select id="pay-method" value={method} onChange={(e) => setMethod(e.target.value)} className="mt-1.5 h-10 w-full rounded-md border border-input bg-background px-3 text-sm">
              <option value="cash">{t("pay.cash")}</option><option value="bank_transfer">{t("pay.bank")}</option>
            </select></div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose} disabled={busy}>{t("common.cancel")}</Button>
            <Button type="submit" disabled={busy} data-testid="pay-confirm">{busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}{t("pay.confirm")}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function RejectDialog({ order, onClose, onReject }) {
  const { t } = useI18n();
  const [reason, setReason] = useState("");
  useEffect(() => { setReason(""); }, [order]);
  return (
    <Dialog open={!!order} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle>{t("orders.rejectTitle")} · {order?.order_no}</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <Label htmlFor="reject-reason">{t("orders.rejectReason")}</Label>
          <Input id="reject-reason" maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} data-testid="reject-reason" />
          <div className="flex flex-wrap gap-2">
            {["orders.rejectOutOfStock", "orders.rejectCredit"].map((key) => (
              <button type="button" key={key} onClick={() => setReason(t(key))} className="rounded-full border border-border px-3 py-1 text-xs hover:bg-secondary">{t(key)}</button>
            ))}
          </div>
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>{t("common.cancel")}</Button>
          <Button type="button" variant="destructive" onClick={() => { onReject(reason.trim()); onClose(); }} data-testid="reject-confirm">{t("orders.rejectConfirm")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function WaybillDialog({ order, drivers = [], onClose }) {
  const { t } = useI18n();
  const [selectedDriverId, setSelectedDriverId] = useState("");
  const [driverName, setDriverName] = useState("");
  const [driverId, setDriverId] = useState("");
  const [vehiclePlate, setVehiclePlate] = useState("");
  const [transportType, setTransportType] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!order) {
      setSelectedDriverId(""); setDriverName(""); setDriverId(""); setVehiclePlate(""); setTransportType("");
      return;
    }
    const assigned = order.assigned_driver_id && drivers.find((d) => d.id === order.assigned_driver_id);
    if (assigned) handleDriverChange(assigned.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [order]);

  const handleDriverChange = (id) => {
    setSelectedDriverId(id);
    const driver = drivers.find((d) => d.id === id);
    if (!driver) return;
    setDriverName(driver.name || "");
    setDriverId(driver.personal_id || "");
    setVehiclePlate(driver.vehicle_plate || "");
    setTransportType(driver.transport_type || "");
  };

  const generate = async (event) => {
    event.preventDefault();
    if (!order) return;
    setBusy(true);
    try {
      const response = await api.post(`/orders/${order.id}/waybill`, {
        driver_name: driverName,
        driver_id: driverId,
        vehicle_plate: vehiclePlate,
        transport_type: transportType,
      }, { responseType: "blob" });
      const blob = new Blob([response.data], { type: "text/html;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `waybill-${String(order.order_no || order.id).replace(/[^a-zA-Z0-9-]/g, "-")}.html`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      toast.success(t("waybill.downloaded"));
      onClose();
    } catch (error) {
      toast.error(formatApiError(error.response?.data?.detail) || t("waybill.error"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={!!order} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("waybill.title")}</DialogTitle>
          <DialogDescription>{t("waybill.description")}</DialogDescription>
        </DialogHeader>
        <form onSubmit={generate} className="space-y-4">
          {drivers.length > 0 && (
            <div>
              <Label htmlFor="waybill-driver-select">{t("waybill.selectDriver")}</Label>
              <select
                id="waybill-driver-select"
                data-testid="waybill-driver-select"
                value={selectedDriverId}
                onChange={(event) => handleDriverChange(event.target.value)}
                className="mt-1.5 h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              >
                <option value="">{t("waybill.manualDriver")}</option>
                {drivers.map((d) => <option key={d.id} value={d.id}>{d.name}{d.vehicle_plate ? ` · ${d.vehicle_plate}` : ""}</option>)}
              </select>
            </div>
          )}
          <div>
            <Label htmlFor="waybill-driver">{t("waybill.driver")}</Label>
            <Input id="waybill-driver" value={driverName} onChange={(event) => setDriverName(event.target.value)} required maxLength={120} className="mt-1.5" />
          </div>
          <div>
            <Label htmlFor="waybill-driver-id">{t("waybill.driverId")}</Label>
            <Input id="waybill-driver-id" value={driverId} onChange={(event) => setDriverId(event.target.value)} maxLength={32} className="mt-1.5" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="waybill-plate">{t("waybill.plate")}</Label>
              <Input id="waybill-plate" value={vehiclePlate} onChange={(event) => setVehiclePlate(event.target.value)} required maxLength={32} className="mt-1.5" />
            </div>
            <div>
              <Label htmlFor="waybill-transport">{t("waybill.transport")}</Label>
              <Input id="waybill-transport" value={transportType} onChange={(event) => setTransportType(event.target.value)} maxLength={80} className="mt-1.5" />
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose} disabled={busy}>{t("common.cancel")}</Button>
            <Button type="submit" disabled={busy}>
              {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <FileDown className="mr-2 h-4 w-4" />}
              {t("waybill.download")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
