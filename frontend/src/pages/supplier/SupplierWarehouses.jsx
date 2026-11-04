import { useCallback, useEffect, useMemo, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { useI18n } from "@/context/I18nContext";
import { useSupplierWarehouse } from "@/context/SupplierWarehouseContext";
import { CityMultiSelect } from "@/components/CityMultiSelect";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Boxes, MapPin, Pencil, Plus, RefreshCw, Trash2, Warehouse as WarehouseIcon } from "lucide-react";
import { toast } from "sonner";

const EMPTY_WAREHOUSE = { name: "", city: "", servedCities: [], address: "", active: true };
const EMPTY_TRANSFER = { from_warehouse_id: "", to_warehouse_id: "", product_id: "", quantity: "" };
const asList = (value, keys = []) => {
  if (Array.isArray(value)) return value;
  for (const key of keys) if (Array.isArray(value?.[key])) return value[key];
  return [];
};

function stockRows(warehouse) {
  return asList(warehouse?.stock_items || warehouse?.items || warehouse?.products || warehouse?.stock, ["items", "products", "stock_items"])
    .map((item) => ({
      id: item.product_id ?? item.id,
      name: item.product_name || item.name || item.product?.name || "—",
      quantity: item.quantity ?? item.stock ?? item.available_quantity ?? item.product?.stock ?? 0,
    }));
}

export default function SupplierWarehouses() {
  const { t } = useI18n();
  const { refreshWarehouses } = useSupplierWarehouse();
  const [warehouses, setWarehouses] = useState([]);
  const [transfers, setTransfers] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [form, setForm] = useState(EMPTY_WAREHOUSE);
  const [editingId, setEditingId] = useState("");
  const [transfer, setTransfer] = useState(EMPTY_TRANSFER);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [transferring, setTransferring] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [warehouseResponse, transferResponse] = await Promise.all([
        api.get("/supplier/warehouses"),
        api.get("/supplier/warehouses/transfers"),
      ]);
      const nextWarehouses = asList(warehouseResponse.data, ["warehouses"]);
      setWarehouses(nextWarehouses);
      setTransfers(asList(transferResponse.data, ["transfers", "items"]));
      setSelectedId((current) => nextWarehouses.some((warehouse) => warehouse.id === current)
        ? current
        : nextWarehouses[0]?.id || "");
      setTransfer((current) => ({
        ...current,
        from_warehouse_id: nextWarehouses.some((warehouse) => warehouse.id === current.from_warehouse_id)
          ? current.from_warehouse_id : nextWarehouses[0]?.id || "",
        to_warehouse_id: nextWarehouses.some((warehouse) => warehouse.id === current.to_warehouse_id)
          ? current.to_warehouse_id : nextWarehouses.find((warehouse) => warehouse.id !== nextWarehouses[0]?.id)?.id || "",
      }));
      setError("");
    } catch (requestError) {
      setError(formatApiError(requestError.response?.data?.detail) || t("warehouse.loadError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { load(); }, [load]);

  const selectedWarehouse = warehouses.find((warehouse) => warehouse.id === selectedId);
  const selectedStock = useMemo(() => stockRows(selectedWarehouse), [selectedWarehouse]);
  const sourceStock = stockRows(warehouses.find((warehouse) => warehouse.id === transfer.from_warehouse_id));
  const sourceProducts = sourceStock.length
    ? sourceStock
    : asList(warehouses.find((warehouse) => warehouse.id === transfer.from_warehouse_id)?.products);

  const startNew = () => {
    setEditingId("");
    setForm(EMPTY_WAREHOUSE);
  };
  const startEdit = (warehouse) => {
    setEditingId(warehouse.id);
    setForm({
      name: warehouse.name || "",
      city: warehouse.city || "",
      servedCities: warehouse.servedCities?.length ? warehouse.servedCities : (warehouse.city ? [warehouse.city] : []),
      address: warehouse.address || "",
      active: warehouse.active !== false,
    });
  };
  const saveWarehouse = async (event) => {
    event.preventDefault();
    setSaving(true);
    try {
      const { data } = editingId
        ? await api.put(`/supplier/warehouses/${encodeURIComponent(editingId)}`, form)
        : await api.post("/supplier/warehouses", form);
      setWarehouses((current) => {
        const next = editingId
          ? current.map((warehouse) => warehouse.id === editingId ? data : warehouse)
          : [...current, data];
        return next;
      });
      setSelectedId(data.id || editingId);
      setForm(EMPTY_WAREHOUSE);
      setEditingId("");
      toast.success(t(editingId ? "warehouse.updated" : "warehouse.created"));
      await load();
      await refreshWarehouses().catch((refreshError) => {
        console.error("Warehouse was saved but the global selector could not refresh:", refreshError);
        setError(t("warehouse.loadError"));
      });
    } catch (requestError) {
      setError(formatApiError(requestError.response?.data?.detail) || t("warehouse.saveError"));
    } finally {
      setSaving(false);
    }
  };
  const deleteWarehouse = async (warehouse) => {
    if (!window.confirm(`${t("warehouse.deleteConfirm")} "${warehouse.name}"?`)) return;
    try {
      await api.delete(`/supplier/warehouses/${encodeURIComponent(warehouse.id)}`);
      if (editingId === warehouse.id) startNew();
      toast.success(t("warehouse.deleted"));
      await load();
      await refreshWarehouses().catch((refreshError) => console.error(refreshError));
    } catch (requestError) {
      setError(formatApiError(requestError.response?.data?.detail) || t("warehouse.deleteError"));
    }
  };
  const sendTransfer = async (event) => {
    event.preventDefault();
    setTransferring(true);
    try {
      await api.post("/supplier/warehouses/transfers", {
        ...transfer,
        quantity: Number(transfer.quantity),
      });
      toast.success(t("warehouse.transferCreated"));
      setTransfer((current) => ({ ...current, product_id: "", quantity: "" }));
      await load();
    } catch (requestError) {
      setError(formatApiError(requestError.response?.data?.detail) || t("warehouse.transferError"));
    } finally {
      setTransferring(false);
    }
  };

  return (
    <div className="space-y-6" data-testid="supplier-warehouses-page">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <WarehouseIcon className="h-6 w-6 text-primary" />
            <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{t("warehouse.title")}</h1>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{t("warehouse.subtitle")}</p>
        </div>
        <Button type="button" variant="outline" onClick={startNew}>
          <Plus className="mr-2 h-4 w-4" />{t("warehouse.add")}
        </Button>
      </header>

      {error && <div role="alert" className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-600">{error}</div>}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">
        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">{t("warehouse.listTitle")}</h2>
            <Button type="button" variant="ghost" size="sm" onClick={load} disabled={loading} aria-label={t("warehouse.refresh")}>
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            </Button>
          </div>
          {loading && warehouses.length === 0 ? (
            <div className="h-32 animate-pulse rounded-xl bg-secondary" />
          ) : warehouses.length === 0 ? (
            <div className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">{t("warehouse.empty")}</div>
          ) : (
            <div className="space-y-3">
              {warehouses.map((warehouse) => {
                const count = stockRows(warehouse).length;
                return (
                  <article
                    key={warehouse.id}
                    className={`rounded-xl border bg-card p-4 transition-colors ${selectedId === warehouse.id ? "border-primary/50" : "border-border"}`}
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <button type="button" className="min-w-0 flex-1 text-left" onClick={() => setSelectedId(warehouse.id)}>
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="font-semibold">{warehouse.name}</h3>
                          <Badge variant={warehouse.active === false ? "secondary" : "outline"}>
                            {t(warehouse.active === false ? "warehouse.inactive" : "warehouse.active")}
                          </Badge>
                        </div>
                        <p className="mt-1 flex items-center gap-1 text-sm text-muted-foreground">
                          <MapPin className="h-3.5 w-3.5 shrink-0" />{[warehouse.city, warehouse.address].filter(Boolean).join(" · ") || "—"}
                        </p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {t("warehouse.servedCities")}: {(warehouse.servedCities?.length ? warehouse.servedCities : [warehouse.city]).filter(Boolean).join(", ") || "—"}
                        </p>
                        <p className="mt-2 text-xs text-muted-foreground">{count} {t("warehouse.stockItems")}</p>
                      </button>
                      <Button type="button" variant="ghost" size="sm" onClick={() => startEdit(warehouse)} aria-label={t("warehouse.edit")}>
                        <Pencil className="mr-1 h-4 w-4" />{t("warehouse.edit")}
                      </Button>
                      <Button type="button" variant="ghost" size="sm" className="text-rose-600 hover:text-rose-700"
                        onClick={() => deleteWarehouse(warehouse)} aria-label={t("warehouse.delete")}
                        data-testid={`delete-warehouse-${warehouse.id}`}>
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
          <section className="overflow-hidden rounded-xl border border-border bg-card">
            <div className="flex items-center gap-2 border-b border-border p-4">
              <Boxes className="h-4 w-4 text-primary" />
              <h2 className="font-semibold">{t("warehouse.stockTitle")}</h2>
              {selectedWarehouse && <span className="text-sm text-muted-foreground">· {selectedWarehouse.name}</span>}
            </div>
            {!selectedWarehouse ? (
              <p className="p-5 text-sm text-muted-foreground">{t("warehouse.chooseWarehouse")}</p>
            ) : selectedStock.length === 0 ? (
              <p className="p-5 text-sm text-muted-foreground">{t("warehouse.noStock")}</p>
            ) : (
              <div className="divide-y divide-border">
                {selectedStock.map((item, index) => (
                  <div key={item.id || `${item.name}-${index}`} className="flex items-center justify-between gap-4 px-4 py-3 text-sm">
                    <span className="font-medium">{item.name}</span>
                    <span className="text-muted-foreground">{item.quantity} {t("common.units")}</span>
                  </div>
                ))}
              </div>
            )}
          </section>
        </section>

        <section className="space-y-6">
          <form onSubmit={saveWarehouse} className="space-y-4 rounded-xl border border-border bg-card p-5">
            <div>
              <h2 className="font-semibold">{t(editingId ? "warehouse.editTitle" : "warehouse.formTitle")}</h2>
              <p className="mt-1 text-xs text-muted-foreground">{t("warehouse.formHint")}</p>
            </div>
            <label className="block space-y-1 text-xs text-muted-foreground">{t("warehouse.name")}
              <Input required maxLength={160} value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} />
            </label>
            <label className="block space-y-1 text-xs text-muted-foreground">{t("warehouse.city")}
              <Input required maxLength={120} value={form.city} onChange={(event) => setForm((current) => ({ ...current, city: event.target.value }))} />
            </label>
            <div className="space-y-1 text-xs text-muted-foreground">
              <label>{t("warehouse.servedCities")}</label>
              <CityMultiSelect
                value={form.servedCities}
                onChange={(servedCities) => setForm((current) => ({ ...current, servedCities }))}
                idPrefix="warehouse-served-cities"
                allowAll={false}
              />
            </div>
            <label className="block space-y-1 text-xs text-muted-foreground">{t("warehouse.address")}
              <Input maxLength={500} value={form.address} onChange={(event) => setForm((current) => ({ ...current, address: event.target.value }))} />
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={form.active} onChange={(event) => setForm((current) => ({ ...current, active: event.target.checked }))} className="h-4 w-4 accent-primary" />
              {t("warehouse.active")}
            </label>
            <div className="flex flex-wrap gap-2">
              <Button type="submit" disabled={saving || form.servedCities.length === 0}>{saving ? t("common.saving") : t("common.save")}</Button>
              {editingId && <Button type="button" variant="outline" onClick={startNew}>{t("common.cancel")}</Button>}
            </div>
          </form>

          <form onSubmit={sendTransfer} className="space-y-4 rounded-xl border border-border bg-card p-5">
            <div>
              <h2 className="font-semibold">{t("warehouse.transferTitle")}</h2>
              <p className="mt-1 text-xs text-muted-foreground">{t("warehouse.transferHint")}</p>
            </div>
            <label className="block space-y-1 text-xs text-muted-foreground">{t("warehouse.from")}
              <select required value={transfer.from_warehouse_id} onChange={(event) => {
                const fromId = event.target.value;
                setTransfer((current) => ({
                  ...current,
                  from_warehouse_id: fromId,
                  to_warehouse_id: current.to_warehouse_id !== fromId
                    ? current.to_warehouse_id : warehouses.find((warehouse) => warehouse.id !== fromId)?.id || "",
                  product_id: "",
                }));
              }} className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground">
                <option value="">{t("warehouse.selectWarehouse")}</option>
                {warehouses.map((warehouse) => <option key={warehouse.id} value={warehouse.id}>{warehouse.name}</option>)}
              </select>
            </label>
            <label className="block space-y-1 text-xs text-muted-foreground">{t("warehouse.to")}
              <select required value={transfer.to_warehouse_id} onChange={(event) => setTransfer((current) => ({ ...current, to_warehouse_id: event.target.value }))} className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground">
                <option value="">{t("warehouse.selectWarehouse")}</option>
                {warehouses.filter((warehouse) => warehouse.id !== transfer.from_warehouse_id).map((warehouse) => <option key={warehouse.id} value={warehouse.id}>{warehouse.name}</option>)}
              </select>
            </label>
            <label className="block space-y-1 text-xs text-muted-foreground">{t("warehouse.product")}
              <select required value={transfer.product_id} onChange={(event) => setTransfer((current) => ({ ...current, product_id: event.target.value }))} className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground">
                <option value="">{t("warehouse.selectProduct")}</option>
                {sourceProducts.map((product, index) => (
                  <option key={product.id || product.product_id || index} value={product.product_id || product.id}>
                    {product.product_name || product.name || product.product?.name || "—"} · {product.quantity ?? product.stock ?? 0}
                  </option>
                ))}
              </select>
            </label>
            <label className="block space-y-1 text-xs text-muted-foreground">{t("warehouse.quantity")}
              <Input required type="number" min="0.01" step="any" value={transfer.quantity} onChange={(event) => setTransfer((current) => ({ ...current, quantity: event.target.value }))} />
            </label>
            <Button type="submit" disabled={transferring || warehouses.length < 2 || sourceProducts.length === 0}>
              {transferring ? t("warehouse.transferring") : t("warehouse.transfer")}
            </Button>
          </form>

          <section className="rounded-xl border border-border bg-card p-5">
            <h2 className="mb-3 font-semibold">{t("warehouse.transferHistory")}</h2>
            {transfers.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("warehouse.noTransfers")}</p>
            ) : (
              <div className="space-y-3">
                {transfers.slice(0, 8).map((item, index) => (
                  <div key={item.id || index} className="border-b border-border pb-3 last:border-0 last:pb-0">
                    <p className="text-sm font-medium">{item.product_name || item.product?.name || item.product_id || "—"}</p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {(item.from_warehouse_name || warehouses.find((warehouse) => warehouse.id === item.from_warehouse_id)?.name || "—")}
                      {" → "}
                      {(item.to_warehouse_name || warehouses.find((warehouse) => warehouse.id === item.to_warehouse_id)?.name || "—")}
                      {" · "}{item.quantity ?? "—"}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </section>
        </section>
      </div>
    </div>
  );
}
