import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AlertTriangle, ArrowUpRight, Loader2, Package, RotateCw, ShoppingCart } from "lucide-react";
import { api, formatApiError } from "@/lib/api";
import { useCart } from "@/context/CartContext";
import { useStoreBranch } from "@/context/StoreBranchContext";
import { useI18n } from "@/context/I18nContext";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";

const RETAILER_LOW_STOCK_LIMIT = 10;

function reorderQuantity(product) {
  const stock = Math.max(0, Number(product.stock) || 0);
  const minimum = Math.max(1, Number(product.moq) || 1);
  return Math.max(minimum, Math.min(Number(product.reorder_quantity) || minimum, stock));
}

export default function SmartInventoryWidget({ mode, supplierProducts = [] }) {
  const { t } = useI18n();
  const { addItems } = useCart();
  const { activeBranchId } = useStoreBranch();
  const navigate = useNavigate();
  const [retailerProducts, setRetailerProducts] = useState([]);
  const [loading, setLoading] = useState(mode === "retailer");
  const [loadError, setLoadError] = useState(false);
  const [busyProductId, setBusyProductId] = useState("");
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    if (mode !== "retailer") return undefined;
    let active = true;
    setLoading(true);
    setLoadError(false);
    Promise.all([
      api.get("/orders", { params: activeBranchId ? { branch_id: activeBranchId } : {} }),
      api.get("/products"),
    ]).then(([ordersResponse, productsResponse]) => {
      if (!active) return;
      const previousPurchases = new Map();
      for (const order of ordersResponse.data || []) {
        if (order.status !== "Delivered") continue;
        for (const item of order.items || []) {
          if (!item.product_id) continue;
          const previous = previousPurchases.get(item.product_id);
          const purchasedAt = order.created_at || "";
          if (!previous || purchasedAt > previous.purchasedAt) {
            previousPurchases.set(item.product_id, {
              reorder_quantity: Number(item.quantity) || 1,
              purchasedAt,
            });
          }
        }
      }
      const alerts = (productsResponse.data || [])
        .filter((product) => {
          const stock = Number(product.stock) || 0;
          return previousPurchases.has(product.id) && stock <= RETAILER_LOW_STOCK_LIMIT;
        })
        .map((product) => ({ ...product, ...previousPurchases.get(product.id) }))
        .sort((left, right) => Number(left.stock) - Number(right.stock))
        .slice(0, 6);
      setRetailerProducts(alerts);
    }).catch((error) => {
      if (!active) return;
      console.error("Could not load low-stock reorder recommendations:", error);
      setLoadError(true);
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [mode, activeBranchId, reloadToken]);

  const alerts = mode === "supplier" ? supplierProducts : retailerProducts;

  const reorder = async (product) => {
    if (busyProductId) return;
    setBusyProductId(product.id);
    try {
      const { data: currentProducts } = await api.get("/products", {
        params: { supplier_id: product.supplier_id },
      });
      const currentProduct = currentProducts.find((item) => item.id === product.id);
      if (!currentProduct || Number(currentProduct.stock) <= 0) {
        toast.error(t("inventoryWidget.noLongerAvailable"));
        return;
      }
      const quantity = reorderQuantity({ ...product, ...currentProduct });
      if (quantity > Number(currentProduct.stock)) {
        toast.error(t("inventoryWidget.belowMinimum"));
        return;
      }
      addItems([{ ...currentProduct, quantity }]);
      toast.success(t("inventoryWidget.addedToCart"));
      navigate("/cart");
    } catch (error) {
      toast.error(formatApiError(error.response?.data?.detail) || t("inventoryWidget.reorderError"));
    } finally {
      setBusyProductId("");
    }
  };

  return (
    <section className="overflow-hidden rounded-lg border border-processing/30 bg-card" data-testid={`smart-inventory-${mode}`}>
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-processing/5 px-4 py-3 sm:px-5">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-processing/30 bg-processing/10 text-processing">
            <AlertTriangle className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <h2 className="truncate text-sm font-semibold text-foreground">{t("inventoryWidget.title")}</h2>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {mode === "retailer" ? t("inventoryWidget.retailerDescription") : t("inventoryWidget.supplierDescription")}
            </p>
          </div>
        </div>
        <span className="rounded-md border border-processing/30 bg-processing/10 px-2.5 py-1 font-mono text-xs font-bold text-processing">
          {loading ? "..." : alerts.length}
        </span>
      </header>

      <div className="divide-y divide-border">
        {loading ? (
          <div className="flex items-center gap-2 px-4 py-6 text-sm text-muted-foreground sm:px-5">
            <Loader2 className="h-4 w-4 animate-spin" />{t("inventoryWidget.loading")}
          </div>
        ) : loadError ? (
          <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-5 sm:px-5">
            <p role="alert" className="text-sm text-muted-foreground">{t("inventoryWidget.loadError")}</p>
            <Button type="button" variant="outline" size="sm" onClick={() => setReloadToken((token) => token + 1)}>
              <RotateCw className="mr-1.5 h-4 w-4" />{t("common.retry")}
            </Button>
          </div>
        ) : alerts.length ? alerts.map((product) => {
          const stock = Math.max(0, Number(product.stock) || 0);
          const quantity = reorderQuantity(product);
          const canReorder = mode === "retailer" && stock > 0 && quantity <= stock;
          return (
            <div key={product.id} className="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:px-5">
              <Package className="hidden h-4 w-4 shrink-0 text-muted-foreground sm:block" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-foreground">{product.name}</p>
                <p className="mt-0.5 truncate text-xs text-muted-foreground">
                  {mode === "retailer" ? product.supplier_name : product.sku || t("inventoryWidget.inventoryItem")}
                  {mode === "retailer" && ` · ${t("inventoryWidget.reorderQty")}: ${quantity}`}
                </p>
              </div>
              <div className="flex items-center justify-between gap-3 sm:justify-end">
                <div className="min-w-24 text-right">
                  <p className={`font-mono text-sm font-bold ${stock === 0 ? "text-destructive" : "text-processing"}`}>
                    {stock} <span className="text-[10px] font-medium">{t("inventoryWidget.unitsLeft")}</span>
                  </p>
                  <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-secondary">
                    <div className={`h-full ${stock === 0 ? "bg-destructive" : "bg-processing"}`} style={{ width: `${Math.min(100, stock / (mode === "retailer" ? RETAILER_LOW_STOCK_LIMIT : 50) * 100)}%` }} />
                  </div>
                </div>
                {mode === "retailer" ? (
                  <Button type="button" size="sm" disabled={!canReorder || busyProductId === product.id} onClick={() => reorder(product)} className="min-w-28">
                    {busyProductId === product.id ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <ShoppingCart className="mr-1.5 h-4 w-4" />}
                    {t("inventoryWidget.reorder")}
                  </Button>
                ) : (
                  <Button asChild type="button" size="sm" variant="outline" className="min-w-28">
                    <Link to="/supplier/inventory">{t("inventoryWidget.manageStock")}<ArrowUpRight className="ml-1.5 h-4 w-4" /></Link>
                  </Button>
                )}
              </div>
            </div>
          );
        }) : (
          <div className="flex items-center gap-3 px-4 py-5 text-sm text-muted-foreground sm:px-5">
            <Package className="h-4 w-4 shrink-0 text-delivered" />{t("inventoryWidget.allClear")}
          </div>
        )}
      </div>
      {mode === "retailer" && !loading && !loadError && alerts.length > 0 && (
        <footer className="border-t border-border px-4 py-2.5 text-[11px] text-muted-foreground sm:px-5">
          {t("inventoryWidget.cartNote")}
        </footer>
      )}
    </section>
  );
}