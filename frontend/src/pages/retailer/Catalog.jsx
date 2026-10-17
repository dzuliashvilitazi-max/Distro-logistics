import { useEffect, useMemo, useState } from "react";
import { api, tierPrice } from "@/lib/api";
import { useCart } from "@/context/CartContext";
import { Search, Filter, Plus, Minus, Package, ShoppingCart, Layers } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

const CATEGORIES = ["All Products", "Beverages", "Groceries", "Snacks & Sweets", "Dry Goods"];

export default function Catalog() {
  const [products, setProducts] = useState([]);
  const [category, setCategory] = useState("All Products");
  const [search, setSearch] = useState("");
  const [inStockOnly, setInStockOnly] = useState(false);
  const [selected, setSelected] = useState(null);
  const { addItem } = useCart();

  const load = () => api.get("/products").then((r) => setProducts(r.data));
  useEffect(() => { load(); }, []);

  const filtered = useMemo(() => products.filter((p) => {
    if (category !== "All Products" && p.category !== category) return false;
    if (search && !p.name.toLowerCase().includes(search.toLowerCase())) return false;
    if (inStockOnly && p.stock <= 0) return false;
    return true;
  }), [products, category, search, inStockOnly]);

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">B2B Product Catalog</h1>
        <p className="mt-1 text-sm text-muted-foreground">Wholesale products with tier pricing & minimum order quantities.</p>
      </div>

      <div className="mb-6 flex flex-col gap-3 lg:flex-row lg:items-center">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search products..." className="pl-9" data-testid="catalog-search" />
        </div>
        <Button variant={inStockOnly ? "default" : "outline"} onClick={() => setInStockOnly((v) => !v)} data-testid="filter-instock">
          <Filter className="mr-1.5 h-4 w-4" /> In stock only
        </Button>
      </div>

      <div className="mb-6 flex flex-wrap gap-2">
        {CATEGORIES.map((c) => (
          <button key={c} onClick={() => setCategory(c)} data-testid={`category-${c.replace(/\s|&/g, "-")}`}
            className={cn("rounded-full border px-4 py-1.5 text-sm font-medium transition-colors duration-200",
              category === c ? "border-primary bg-primary text-primary-foreground" : "border-border text-muted-foreground hover:border-primary/40 hover:text-foreground")}>
            {c}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border py-20 text-center">
          <Package className="h-10 w-10 text-muted-foreground" />
          <p className="mt-3 text-sm text-muted-foreground">No products match your filters.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {filtered.map((p) => (
            <div key={p.id} data-testid={`product-card-${p.id}`} className="group flex flex-col overflow-hidden rounded-xl border border-border bg-card transition-all duration-200 hover:border-primary/40 hover:shadow-lg">
              <div className="relative aspect-[4/3] overflow-hidden bg-secondary">
                <img src={p.image} alt={p.name} className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105" />
                <Badge className="absolute left-3 top-3 bg-background/90 text-foreground backdrop-blur">{p.category}</Badge>
                {p.stock <= 0 ? <Badge className="absolute right-3 top-3 bg-rose-500 text-white">Out of stock</Badge>
                  : p.stock < 50 ? <Badge className="absolute right-3 top-3 bg-amber-500 text-white">Low: {p.stock}</Badge> : null}
              </div>
              <div className="flex flex-1 flex-col p-4">
                <p className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">{p.supplier_name}</p>
                <h3 className="mt-1 line-clamp-2 text-sm font-semibold leading-snug">{p.name}</h3>
                <div className="mt-3 flex items-end justify-between">
                  <div>
                    <p className="text-xl font-extrabold">${p.price_per_unit.toFixed(2)}</p>
                    <p className="font-mono text-[11px] text-muted-foreground">MOQ {p.moq} units</p>
                  </div>
                  <span className="flex items-center gap-1 rounded-md bg-primary/10 px-2 py-1 font-mono text-[10px] font-semibold text-primary"><Layers className="h-3 w-3" />{p.tier_pricing?.length || 1} tiers</span>
                </div>
                <Button className="mt-4 w-full" disabled={p.stock <= 0} onClick={() => setSelected(p)} data-testid={`order-product-${p.id}`}>
                  <ShoppingCart className="mr-1.5 h-4 w-4" /> Bulk Order
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      <OrderDialog product={selected} onClose={() => setSelected(null)} onAdd={(prod, qty) => { addItem(prod, qty); toast.success(`${qty} units of ${prod.name} added to cart`); setSelected(null); }} />
    </div>
  );
}

function OrderDialog({ product, onClose, onAdd }) {
  const [qty, setQty] = useState(10);
  useEffect(() => { if (product) setQty(product.moq); }, [product]);
  if (!product) return null;
  const unit = tierPrice(product, qty);
  const belowMoq = qty < product.moq;
  const tiers = [...(product.tier_pricing || [])].sort((a, b) => a.min_qty - b.min_qty);

  return (
    <Dialog open={!!product} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="bg-card sm:max-w-lg">
        <DialogHeader><DialogTitle className="pr-6 text-left">{product.name}</DialogTitle></DialogHeader>
        <div className="space-y-4">
          <div className="flex gap-4">
            <img src={product.image} alt={product.name} className="h-24 w-24 rounded-lg border border-border object-cover" />
            <div className="text-sm text-muted-foreground">
              <p>{product.description}</p>
              <p className="mt-2 font-mono text-xs">Supplier: {product.supplier_name}</p>
              <p className="font-mono text-xs">In stock: {product.stock} units</p>
            </div>
          </div>

          <div className="rounded-lg border border-border p-3">
            <p className="mb-2 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">Volume Tier Pricing</p>
            <div className="grid grid-cols-3 gap-2">
              {tiers.map((t) => (
                <div key={t.min_qty} className={cn("rounded-md border p-2 text-center", qty >= t.min_qty ? "border-primary bg-primary/10" : "border-border")}>
                  <p className="font-mono text-[11px] text-muted-foreground">{t.min_qty}+ units</p>
                  <p className="text-sm font-bold">${t.price.toFixed(2)}</p>
                </div>
              ))}
            </div>
          </div>

          <div>
            <p className="mb-2 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">Quantity (units)</p>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="icon" onClick={() => setQty((q) => Math.max(1, q - 10))} data-testid="qty-minus"><Minus className="h-4 w-4" /></Button>
              <Input type="number" value={qty} onChange={(e) => setQty(Math.max(1, parseInt(e.target.value) || 1))} className="text-center font-bold" data-testid="qty-input" />
              <Button variant="outline" size="icon" onClick={() => setQty((q) => q + 10)} data-testid="qty-plus"><Plus className="h-4 w-4" /></Button>
              {[50, 100].map((n) => <Button key={n} variant="secondary" onClick={() => setQty((q) => q + n)} data-testid={`qty-add-${n}`}>+{n}</Button>)}
            </div>
            {belowMoq && <p className="mt-2 text-xs font-medium text-rose-500">Minimum order quantity is {product.moq} units.</p>}
          </div>
        </div>
        <DialogFooter className="flex-row items-center justify-between gap-3 sm:justify-between">
          <div><p className="font-mono text-[11px] text-muted-foreground">Order total</p><p className="text-2xl font-extrabold" data-testid="order-total">${(unit * qty).toFixed(2)}</p></div>
          <Button size="lg" disabled={belowMoq} onClick={() => onAdd(product, qty)} data-testid="confirm-add-cart">Add to Cart</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
