import { useEffect, useRef, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { useI18n } from "@/context/I18nContext";
import { CATEGORY_VALUES, categoryKey } from "@/lib/i18n";
import { Plus, Pencil, Trash2, Boxes, Camera, ImageIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { toast } from "sonner";

const EMPTY = { name: "", category: "Beverages", price_per_unit: "", moq: "", stock: "", image: "", description: "",
  tier_pricing: [{ min_qty: "", price: "" }, { min_qty: "", price: "" }, { min_qty: "", price: "" }] };

export default function Inventory() {
  const { t } = useI18n();
  const [products, setProducts] = useState([]);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [deleteId, setDeleteId] = useState(null);
  const [imgLoading, setImgLoading] = useState(false);
  const camRef = useRef(null);
  const galRef = useRef(null);

  const processFile = (file) => new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = reject;
    reader.onload = (e) => {
      const img = new Image();
      img.onload = () => {
        const max = 900;
        let { width, height } = img;
        if (width > max || height > max) { const r = Math.min(max / width, max / height); width = Math.round(width * r); height = Math.round(height * r); }
        const canvas = document.createElement("canvas");
        canvas.width = width; canvas.height = height;
        canvas.getContext("2d").drawImage(img, 0, 0, width, height);
        resolve(canvas.toDataURL("image/jpeg", 0.75));
      };
      img.onerror = reject;
      img.src = e.target.result;
    };
    reader.readAsDataURL(file);
  });

  const onPickImage = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setImgLoading(true);
    try {
      const dataUrl = await processFile(file);
      setForm((f) => ({ ...f, image: dataUrl }));
    } catch { toast.error(t("inv.nameRequired")); }
    finally { setImgLoading(false); }
  };

  const load = () => api.get("/auth/me").then((u) => api.get(`/products?supplier_id=${u.data.id}`)).then((r) => setProducts(r.data));
  useEffect(() => { load(); }, []);

  const openNew = () => { setEditing("new"); setForm(EMPTY); };
  const openEdit = (p) => {
    setEditing(p.id);
    setForm({ ...p, price_per_unit: String(p.price_per_unit), moq: String(p.moq), stock: String(p.stock),
      tier_pricing: [0, 1, 2].map((i) => p.tier_pricing?.[i] ? { min_qty: String(p.tier_pricing[i].min_qty), price: String(p.tier_pricing[i].price) } : { min_qty: "", price: "" }) });
  };

  const save = async () => {
    const tiers = form.tier_pricing.filter((x) => x.min_qty && x.price).map((x) => ({ min_qty: parseInt(x.min_qty), price: parseFloat(x.price) }));
    const payload = { name: form.name, category: form.category, price_per_unit: parseFloat(form.price_per_unit) || 0,
      moq: parseInt(form.moq) || 1, stock: parseInt(form.stock) || 0, image: form.image, description: form.description, tier_pricing: tiers };
    if (!payload.name) { toast.error(t("inv.nameRequired")); return; }
    try {
      if (editing === "new") await api.post("/products", payload);
      else await api.put(`/products/${editing}`, payload);
      toast.success(t("inv.productSaved"));
      setEditing(null); load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const doDelete = async () => {
    try { await api.delete(`/products/${deleteId}`); toast.success(t("inv.productDeleted")); setDeleteId(null); load(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const setTier = (i, k, v) => setForm((f) => ({ ...f, tier_pricing: f.tier_pricing.map((x, j) => j === i ? { ...x, [k]: v } : x) }));

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div><h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{t("inv.title")}</h1><p className="mt-1 text-sm text-muted-foreground">{products.length} {t("inv.productsCount")}</p></div>
        <Button onClick={openNew} data-testid="add-product-btn"><Plus className="mr-1.5 h-4 w-4" /> {t("inv.addProduct")}</Button>
      </div>

      {products.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border py-20 text-center"><Boxes className="h-10 w-10 text-muted-foreground" /><p className="mt-3 text-sm text-muted-foreground">{t("inv.noProducts")}</p></div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border bg-card">
          <table className="w-full text-sm">
            <thead className="border-b border-border bg-secondary/50"><tr className="text-left font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
              <th className="px-4 py-3">{t("common.product")}</th><th className="px-4 py-3">{t("common.category")}</th><th className="px-4 py-3">{t("common.price")}</th><th className="px-4 py-3">{t("catalog.moq")}</th><th className="px-4 py-3">{t("common.stock")}</th><th className="px-4 py-3 text-right">{t("common.actions")}</th>
            </tr></thead>
            <tbody>
              {products.map((p) => (
                <tr key={p.id} data-testid={`inventory-row-${p.id}`} className="border-b border-border/50 last:border-0">
                  <td className="px-4 py-3"><div className="flex items-center gap-3"><img src={p.image || undefined} alt="" className="h-10 w-10 rounded border border-border object-cover" /><span className="max-w-xs truncate font-medium">{p.name}</span></div></td>
                  <td className="px-4 py-3 text-muted-foreground">{t(categoryKey(p.category))}</td>
                  <td className="px-4 py-3 font-semibold">₾{p.price_per_unit.toFixed(2)}</td>
                  <td className="px-4 py-3 font-mono">{p.moq}</td>
                  <td className="px-4 py-3"><Badge className={p.stock < 50 ? "bg-amber-500/15 text-amber-500" : "bg-emerald-500/15 text-emerald-500"}>{p.stock}</Badge></td>
                  <td className="px-4 py-3"><div className="flex justify-end gap-1">
                    <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => openEdit(p)} data-testid={`edit-product-${p.id}`}><Pencil className="h-4 w-4" /></Button>
                    <Button variant="ghost" size="icon" className="h-8 w-8 text-rose-500 hover:bg-rose-500/10" onClick={() => setDeleteId(p.id)} data-testid={`delete-product-${p.id}`}><Trash2 className="h-4 w-4" /></Button>
                  </div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Dialog open={!!editing} onOpenChange={(o) => !o && setEditing(null)}>
        <DialogContent className="max-h-[90vh] overflow-y-auto bg-card sm:max-w-xl">
          <DialogHeader><DialogTitle>{editing === "new" ? t("inv.addProduct") : t("inv.editProduct")}</DialogTitle><DialogDescription>{t("inv.tierPricing")}</DialogDescription></DialogHeader>
          <div className="space-y-3">
            <div><Label>{t("inv.productName")}</Label><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="mt-1.5" data-testid="product-name" /></div>
            <div className="grid grid-cols-2 gap-3">
              <div><Label>{t("common.category")}</Label><select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} className="mt-1.5 h-10 w-full rounded-md border border-input bg-background px-3 text-sm" data-testid="product-category">{CATEGORY_VALUES.map((c) => <option key={c} value={c}>{t(categoryKey(c))}</option>)}</select></div>
              <div><Label>{t("inv.basePrice")}</Label><Input type="number" value={form.price_per_unit} onChange={(e) => setForm({ ...form, price_per_unit: e.target.value })} className="mt-1.5" data-testid="product-price" /></div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div><Label>{t("inv.moqUnits")}</Label><Input type="number" value={form.moq} onChange={(e) => setForm({ ...form, moq: e.target.value })} className="mt-1.5" data-testid="product-moq" /></div>
              <div><Label>{t("common.stock")}</Label><Input type="number" value={form.stock} onChange={(e) => setForm({ ...form, stock: e.target.value })} className="mt-1.5" data-testid="product-stock" /></div>
            </div>
            <div>
              <Label>{t("inv.imageLabel")}</Label>
              <div className="mt-1.5 flex items-start gap-3">
                <div className="flex h-24 w-24 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-dashed border-border bg-secondary" data-testid="image-preview">
                  {imgLoading ? <span className="text-[11px] text-muted-foreground">{t("inv.processing")}</span>
                    : form.image ? <img src={form.image} alt={t("inv.preview")} className="h-full w-full object-cover" data-testid="image-preview-thumb" />
                    : <ImageIcon className="h-7 w-7 text-muted-foreground" />}
                </div>
                <div className="flex flex-1 flex-col gap-2">
                  <input ref={camRef} type="file" accept="image/*" capture="environment" className="hidden" onChange={onPickImage} data-testid="camera-input" />
                  <input ref={galRef} type="file" accept="image/*" className="hidden" onChange={onPickImage} data-testid="gallery-input" />
                  <div className="flex gap-2">
                    <Button type="button" variant="outline" className="flex-1" onClick={() => camRef.current?.click()} data-testid="take-photo-btn"><Camera className="mr-1.5 h-4 w-4" /> {t("inv.takePhoto")}</Button>
                    <Button type="button" variant="outline" className="flex-1" onClick={() => galRef.current?.click()} data-testid="choose-gallery-btn"><ImageIcon className="mr-1.5 h-4 w-4" /> {t("inv.chooseGallery")}</Button>
                  </div>
                  <Input value={form.image?.startsWith("data:") ? "" : form.image} onChange={(e) => setForm({ ...form, image: e.target.value })} placeholder={t("inv.orPasteUrl")} data-testid="product-image" />
                </div>
              </div>
            </div>
            <div><Label>{t("inv.description")}</Label><Textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className="mt-1.5" rows={2} data-testid="product-desc" /></div>
            <div>
              <Label>{t("inv.tierPricing")}</Label>
              <div className="mt-1.5 space-y-2">
                {form.tier_pricing.map((x, i) => (
                  <div key={i} className="flex gap-2">
                    <Input type="number" placeholder={t("inv.minQty")} value={x.min_qty} onChange={(e) => setTier(i, "min_qty", e.target.value)} data-testid={`tier-qty-${i}`} />
                    <Input type="number" placeholder={t("inv.priceDollar")} value={x.price} onChange={(e) => setTier(i, "price", e.target.value)} data-testid={`tier-price-${i}`} />
                  </div>
                ))}
              </div>
            </div>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setEditing(null)}>{t("common.cancel")}</Button><Button onClick={save} data-testid="save-product-btn">{t("inv.saveProduct")}</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={!!deleteId} onOpenChange={(o) => !o && setDeleteId(null)}>
        <AlertDialogContent className="bg-card">
          <AlertDialogHeader><AlertDialogTitle>{t("inv.deleteTitle")}</AlertDialogTitle><AlertDialogDescription>{t("inv.deleteDesc")}</AlertDialogDescription></AlertDialogHeader>
          <AlertDialogFooter><AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel><AlertDialogAction onClick={doDelete} className="bg-rose-500 hover:bg-rose-600" data-testid="confirm-delete-btn">{t("common.delete")}</AlertDialogAction></AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
