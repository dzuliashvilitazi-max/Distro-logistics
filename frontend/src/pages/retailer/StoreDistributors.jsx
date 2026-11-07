import { useCallback, useEffect, useMemo, useState } from "react";
import { api, requestErrorMessage } from "@/lib/api";
import { LogoAvatar } from "@/components/BusinessLogo";
import ProductImage from "@/components/ProductImage";
import { useCart } from "@/context/CartContext";
import { OrderDialog } from "@/pages/retailer/Catalog";
import ProductFilterBar from "@/components/ProductFilterBar";
import { filterAndSortProducts } from "@/lib/productFilters";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { ArrowLeft, Check, Package, X } from "lucide-react";
import { toast } from "sonner";

export default function StoreDistributors() {
  const { addItem } = useCart();
  const [distributors, setDistributors] = useState([]);
  const [incomingInvitations, setIncomingInvitations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [products, setProducts] = useState([]);
  const [loadingProducts, setLoadingProducts] = useState(false);
  const [search, setSearch] = useState("");
  const [priceSort, setPriceSort] = useState("default");
  const [packageType, setPackageType] = useState("");
  const [packageSize, setPackageSize] = useState("");
  const [orderProduct, setOrderProduct] = useState(null);
  const [disconnecting, setDisconnecting] = useState(null);
  const [busy, setBusy] = useState(false);
  const [respondingId, setRespondingId] = useState("");

  const loadConnections = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/connections/mine");
      setDistributors(data.filter((connection) => connection.status === "APPROVED"));
      setIncomingInvitations(data.filter((connection) => connection.status === "PENDING" && connection.requested_by_role === "supplier"));
    } catch (error) {
      toast.error(requestErrorMessage(error));
    } finally {
      setLoading(false);
    }
  }, []);

  const respondToInvitation = async (connection, status) => {
    setRespondingId(connection.id);
    try {
      await api.patch("/connections/respond-invitation", { connection_id: connection.id, status });
      toast.success(status === "APPROVED" ? "თანამშრომლობის მოწვევა მიღებულია" : "თანამშრომლობის მოწვევა უარყოფილია");
      await loadConnections();
    } catch (error) {
      toast.error(requestErrorMessage(error));
    } finally {
      setRespondingId("");
    }
  };

  const disconnect = async () => {
    setBusy(true);
    try {
      await api.delete(`/connections/${encodeURIComponent(disconnecting.id)}`);
      setDistributors((list) => list.filter((c) => c.id !== disconnecting.id));
      toast.success("კავშირი გაუქმებულია");
      setDisconnecting(null);
    } catch (error) {
      toast.error(requestErrorMessage(error));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => { loadConnections(); }, [loadConnections]);

  useEffect(() => {
    if (!selected) return;
    let live = true;
    setLoadingProducts(true);
    setProducts([]);
    api.get("/products", { params: { supplier_id: selected.distributor_id } })
      .then(({ data }) => live && setProducts(data))
      .catch((error) => toast.error(requestErrorMessage(error)))
      .finally(() => live && setLoadingProducts(false));
    return () => { live = false; };
  }, [selected]);

  useEffect(() => {
    setPriceSort("default");
    setPackageType("");
    setPackageSize("");
  }, [selected?.distributor_id]);

  const name = (c) => c.distributor?.business_name || c.distributor?.name || c.distributor_id;
  const visible = useMemo(() => filterAndSortProducts(products, {
    query: search, sortBy: priceSort, packageType, packageSize,
  }), [products, search, priceSort, packageType, packageSize]);

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">ჩემი დისტრიბუტორები</h1>
        <p className="mt-1 text-sm text-muted-foreground">დადასტურებული პარტნიორები და მათი ექსკლუზიური კატალოგი.</p>
      </div>

      {incomingInvitations.length > 0 && (
        <section className="mb-6 space-y-3" aria-label="შემომავალი თანამშრომლობის მოწვევები" data-testid="incoming-connection-invitations">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold">თანამშრომლობის მოწვევები</h2>
              <p className="mt-1 text-xs text-muted-foreground">დადასტურების შემდეგ დისტრიბუტორის კატალოგსა და ფასებზე წვდომა გაგეხსნებათ.</p>
            </div>
            <span className="rounded-md border border-processing/30 bg-processing/10 px-2.5 py-1 font-mono text-xs font-bold text-processing">{incomingInvitations.length}</span>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            {incomingInvitations.map((connection) => {
              const distributorName = connection.distributor?.business_name || connection.distributor?.name || connection.distributor_id;
              return (
                <article key={connection.id} className="flex flex-col justify-between gap-4 rounded-lg border border-border bg-card p-4 sm:flex-row sm:items-center" data-testid={`incoming-invitation-${connection.id}`}>
                  <div className="min-w-0">
                    <h3 className="truncate text-sm font-semibold">{distributorName}</h3>
                    <p className="mt-1 text-xs text-muted-foreground">{[connection.distributor?.city, ...(connection.distributor?.servedSectors || connection.distributor?.business_sectors || [])].filter(Boolean).join(" · ")}</p>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <Button size="sm" disabled={respondingId === connection.id} onClick={() => respondToInvitation(connection, "APPROVED")} data-testid={`accept-invitation-${connection.id}`}>
                      <Check className="mr-1.5 h-4 w-4" />მიღება
                    </Button>
                    <Button size="sm" variant="outline" disabled={respondingId === connection.id} onClick={() => respondToInvitation(connection, "REJECTED")} data-testid={`reject-invitation-${connection.id}`}>
                      <X className="mr-1.5 h-4 w-4" />უარყოფა
                    </Button>
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      )}

      {!selected && (loading ? <p className="py-10 text-center text-sm text-muted-foreground">იტვირთება...</p>
        : distributors.length === 0 ? <p className="rounded-xl border border-dashed border-border py-16 text-center text-sm text-muted-foreground">დადასტურებული დისტრიბუტორები არ გაქვთ. გამოაგზავნეთ მოთხოვნა კატალოგიდან.</p>
        : <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {distributors.map((c) => (
            <div key={c.distributor_id} className="flex flex-col rounded-lg border border-border bg-card transition-colors hover:border-primary/50">
              <button type="button" onClick={() => { setSearch(""); setSelected(c); }} data-testid={`my-distributor-${c.distributor_id}`}
                className="flex min-h-24 flex-1 flex-col justify-between rounded-t-lg p-4 text-left hover:bg-secondary/40">
                <span className="flex items-center gap-2.5"><LogoAvatar logo={c.distributor?.logo_url} name={name(c)} className="h-9 w-9 shrink-0 text-sm" /><span className="font-semibold">{name(c)}</span></span>
                <span className="mt-2 flex w-full items-center justify-between text-xs text-muted-foreground">
                  <span>{c.distributor?.city}</span>
                  {Number(c.discount_percent) > 0 && <Badge variant="secondary">-{Number(c.discount_percent)}%</Badge>}
                </span>
              </button>
              <div className="border-t border-border p-2">
                <Button size="sm" variant="ghost" className="w-full text-rose-500" onClick={() => setDisconnecting(c)} data-testid={`disconnect-${c.distributor_id}`}>🗑️ კავშირის გაუქმება</Button>
              </div>
            </div>
          ))}
        </div>)}

      {selected && <section>
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <Button variant="ghost" onClick={() => setSelected(null)}><ArrowLeft className="mr-2 h-4 w-4" />უკან</Button>
          <h2 className="text-lg font-semibold">{name(selected)}</h2>
                <ProductFilterBar
                  products={products}
                  query={search}
                  onQueryChange={setSearch}
                  sortBy={priceSort}
                  onSortChange={setPriceSort}
                  packageType={packageType}
                  onPackageTypeChange={setPackageType}
                  packageSize={packageSize}
                  onPackageSizeChange={setPackageSize}
                />
        </div>
        {loadingProducts ? <p className="py-10 text-center text-sm text-muted-foreground">იტვირთება...</p>
          : visible.length === 0 ? <div className="flex flex-col items-center rounded-xl border border-dashed border-border py-16 text-center"><Package className="h-10 w-10 text-muted-foreground" /><p className="mt-3 text-sm text-muted-foreground">პროდუქტები არ მოიძებნა</p></div>
          : <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {visible.map((p) => (
              <div key={p.id} data-testid={`exclusive-product-${p.id}`} className="flex flex-col overflow-hidden rounded-xl border border-border bg-card">
                <div className="aspect-[4/3] bg-secondary">
                  <ProductImage image={p.image} name={p.name} category={p.category} alt={p.name} className="h-full w-full object-cover" />
                </div>
                <div className="flex flex-1 flex-col p-4">
                  <h3 className="line-clamp-2 text-sm font-semibold">{p.name}</h3>
                  <div className="mt-3">
                    <p className="text-xl font-extrabold">₾{Number(p.price_per_unit).toFixed(2)}</p>
                    {p.base_price != null && Number(p.base_price) !== Number(p.price_per_unit) &&
                      <p className="font-mono text-[11px] text-muted-foreground line-through">₾{Number(p.base_price).toFixed(2)}</p>}
                    <p className="font-mono text-[11px] text-muted-foreground">MOQ {p.moq}</p>
                  </div>
                  <Button className="mt-4 w-full" disabled={p.stock <= 0 || p.isLocked} onClick={() => setOrderProduct(p)} data-testid={`exclusive-order-${p.id}`}>
                    🛒 კალათაში დამატება / შეკვეთა
                  </Button>
                </div>
              </div>
            ))}
          </div>}
      </section>}

      <Dialog open={!!disconnecting} onOpenChange={(o) => !o && setDisconnecting(null)}>
        <DialogContent className="bg-card sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{disconnecting && name(disconnecting)}</DialogTitle>
            <DialogDescription>ნამდვილად გსურთ პარტნიორობის გაუქმება? ექსკლუზიური ფასები აღარ იქნება ხელმისაწვდომი.</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDisconnecting(null)}>გაუქმება</Button>
            <Button variant="destructive" disabled={busy} onClick={disconnect} data-testid="confirm-disconnect">კავშირის გაუქმება</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <OrderDialog product={orderProduct} onClose={() => setOrderProduct(null)}
        onAdd={(prod, qty) => { addItem(prod, qty); toast.success(`${qty} × ${prod.name} — დამატებულია კალათაში`); setOrderProduct(null); }} />
    </div>
  );
}
