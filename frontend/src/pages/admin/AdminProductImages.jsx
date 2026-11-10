import { useCallback, useEffect, useRef, useState } from "react";
import { api, requestErrorMessage } from "@/lib/api";
import ProductImage from "@/components/ProductImage";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { RefreshCw, Upload } from "lucide-react";
import { toast } from "sonner";

const TABS = [
  ["missing", "სურათის გარეშე"],
  ["failed", "ვერ მოიძებნა / შეცდომა"],
  ["auto", "ავტომატური"],
  ["manual", "ხელით ატვირთული"],
];

export default function AdminProductImages() {
  const [tab, setTab] = useState("missing");
  const [data, setData] = useState({ items: [], counts: {}, search_configured: true });
  const [busy, setBusy] = useState("");
  const [uploadId, setUploadId] = useState(null);
  const fileRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const { data: response } = await api.get("/admin/product-images", { params: { status: tab, limit: 50 } });
      setData(response);
    } catch (error) {
      toast.error(requestErrorMessage(error));
    }
  }, [tab]);

  useEffect(() => { load(); }, [load]);

  const retry = async (product, replace = false) => {
    if (product.image_source === "manual" && !window.confirm("ხელით ატვირთული სურათი ჩანაცვლდეს ავტომატურით?")) return;
    setBusy(product.id);
    try {
      await api.post(`/admin/product-images/${encodeURIComponent(product.id)}/retry`, null, { params: { replace: replace || product.image_source === "manual" } });
      toast.success("ძიება დაიწყო");
      setTimeout(load, 2500);
    } catch (error) {
      toast.error(requestErrorMessage(error));
    } finally {
      setBusy("");
    }
  };

  const runBatch = async () => {
    setBusy("batch");
    try {
      const { data: result } = await api.post("/admin/product-images/run");
      toast.success(`დამუშავდა ${result.processed}, მიენიჭა ${result.ok || 0}`);
      await load();
    } catch (error) {
      toast.error(requestErrorMessage(error));
    } finally {
      setBusy("");
    }
  };

  const upload = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !uploadId) return;
    const form = new FormData();
    form.append("file", file);
    setBusy(uploadId);
    try {
      await api.post(`/admin/product-images/${encodeURIComponent(uploadId)}/upload`, form);
      toast.success("სურათი აიტვირთა");
      await load();
    } catch (error) {
      toast.error(requestErrorMessage(error));
    } finally {
      setBusy("");
      setUploadId(null);
    }
  };

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">პროდუქტების სურათები</h1>
          <p className="mt-1 text-sm text-muted-foreground">ავტომატურად მიენიჭებული და ხელით ატვირთული სურათების მართვა. ხელით ატვირთული სურათი ყოველთვის პრიორიტეტულია.</p>
        </div>
        <Button onClick={runBatch} disabled={busy === "batch"} data-testid="run-image-batch"><RefreshCw className="mr-2 h-4 w-4" />ძიების გაშვება</Button>
      </div>
      {!data.search_configured && (
        <p className="mb-4 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm" role="status">
          სურათების მიმწოდებელი არ არის მორგებული: სერვერზე დააყენეთ გარემოს ცვლადი <code>PIXABAY_API_KEY</code>.
        </p>
      )}
      <div className="mb-5 flex flex-wrap gap-2">
        {TABS.map(([key, label]) => (
          <Button key={key} variant={tab === key ? "default" : "outline"} onClick={() => setTab(key)} data-testid={`image-tab-${key}`}>
            {label} <Badge className="ml-2" variant="secondary">{data.counts?.[key] ?? 0}</Badge>
          </Button>
        ))}
      </div>
      <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={upload} />
      {data.items.length === 0 ? (
        <p className="rounded-xl border border-dashed border-border py-14 text-center text-sm text-muted-foreground">პროდუქტები არ მოიძებნა</p>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {data.items.map((product) => (
            <div key={product.id} className="flex gap-3 rounded-xl border border-border bg-card p-3" data-testid={`image-row-${product.id}`}>
              <ProductImage image={product.image} name={product.name} category={product.category} alt="" className="h-20 w-20 shrink-0 rounded-lg object-cover" />
              <div className="min-w-0 flex-1">
                <p className="truncate font-semibold">{product.name}</p>
                <p className="truncate text-xs text-muted-foreground">{product.supplier_name} · {product.category}</p>
                <div className="mt-1 flex flex-wrap gap-1">
                  <Badge variant="secondary">{product.image_source === "manual" ? "ხელით" : product.image_source === "auto" ? "ავტომატური" : "—"}</Badge>
                  {product.image_status && <Badge variant="outline">{product.image_status}</Badge>}
                  {product.image_confidence != null && <Badge variant="outline">{Math.round(product.image_confidence * 100)}%</Badge>}
                </div>
                <div className="mt-2 flex gap-2">
                  <Button size="sm" variant="outline" disabled={busy === product.id} onClick={() => retry(product)}><RefreshCw className="mr-1 h-3.5 w-3.5" />ხელახლა</Button>
                  <Button size="sm" variant="outline" disabled={busy === product.id} onClick={() => { setUploadId(product.id); fileRef.current?.click(); }}><Upload className="mr-1 h-3.5 w-3.5" />ატვირთვა</Button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
