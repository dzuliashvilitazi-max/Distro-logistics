import { useEffect, useRef, useState } from "react";
import { API, api } from "@/lib/api";
import ProductImage from "@/components/ProductImage";
import { useAuth } from "@/context/AuthContext";
import { useSupplierWarehouse } from "@/context/SupplierWarehouseContext";
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

const EMPTY = { name: "", category: "Beverages", price_per_unit: "", moq: "", stock: "", image: "", description: "", sku: "", barcode: "", unit: "",
  tier_pricing: [{ min_qty: "", price: "" }, { min_qty: "", price: "" }, { min_qty: "", price: "" }] };
const IMPORT_FIELDS = [
  ["name", "პროდუქტის სახელი"], ["category", "კატეგორია"], ["price_per_unit", "ფასი"],
  ["stock", "მარაგი"], ["moq", "მინიმალური რაოდენობა"], ["unit", "საზომი ერთეული"],
  ["sku", "SKU / კოდი"], ["barcode", "შტრიხკოდი"], ["external_id", "პროდუქტის ID"],
  ["city", "ქალაქი"], ["image", "სურათი"], ["description", "აღწერა"], ["tier_pricing", "მოცულობითი ფასები"],
];
const PRODUCT_IMPORT_API_BASE = API.replace(/\/+$/, "");
const PRODUCT_IMPORT_PREVIEW_URL = `${PRODUCT_IMPORT_API_BASE}/products/import-preview`;
const PRODUCT_UPLOAD_URL = `${PRODUCT_IMPORT_API_BASE}/products/upload-excel`;

export default function Inventory() {
  const { t } = useI18n();
  const { user } = useAuth();
  const { activeWarehouseId } = useSupplierWarehouse();
  const isSupplierOwner = user?.supplier_access_role !== "branch_manager";
  const canEditInventory = !isSupplierOwner || activeWarehouseId !== "all";
  const [products, setProducts] = useState([]);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [deleteId, setDeleteId] = useState(null);
  const [imgLoading, setImgLoading] = useState(false);
  const [cats, setCats] = useState([]);
  const [importFile, setImportFile] = useState(null);
  const [importPreview, setImportPreview] = useState(null);
  const [importMapping, setImportMapping] = useState({});
  const [importBusy, setImportBusy] = useState(false);
  const [stockMode, setStockMode] = useState("add");
  const [importConfirmOpen, setImportConfirmOpen] = useState(false);
  useEffect(() => { api.get("/categories").then((r) => setCats(r.data)); }, []);
  const camRef = useRef(null);
  const galRef = useRef(null);
  const fileInputRef = useRef(null);

const handleExcelUpload = async (e) => {
  const input = e.currentTarget;
  const file = input.files?.[0];
    if (!file) return;

    const formData = new FormData();
    formData.append("file", file);
    setImportFile(file);
    setImportPreview(null);
    setImportMapping({});
    setImportBusy(true);
    try {
      const response = await api.request({
        method: "POST",
        url: PRODUCT_IMPORT_PREVIEW_URL,
        data: formData,
      });
      setImportPreview(response.data);
      setImportMapping(response.data.mapping || {});
    } catch (error) {
      const detail = error.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "ფაილის დამუშავება ვერ მოხერხდა. გადაამოწმეთ და სცადეთ ხელახლა.");
      setImportFile(null);
    } finally {
      input.value = "";
      setImportBusy(false);
    }
  };

  const refreshImportPreview = async () => {
    if (!importFile) return;
    const formData = new FormData();
    formData.append("file", importFile);
    formData.append("mapping", JSON.stringify(importMapping));
    setImportBusy(true);
    try {
      const response = await api.request({
        method: "POST",
        url: PRODUCT_IMPORT_PREVIEW_URL,
        data: formData,
      });
      setImportPreview(response.data);
      setImportMapping(response.data.mapping || {});
    } catch (error) {
      const detail = error.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "ფაილის დამუშავება ვერ მოხერხდა. გადაამოწმეთ და სცადეთ ხელახლა.");
    } finally {
      setImportBusy(false);
    }
  };

  const closeImport = () => {
    if (importBusy) return;
    setImportFile(null);
    setImportPreview(null);
    setImportMapping({});
    setImportConfirmOpen(false);
  };

  const saveImport = async () => {
    if (!importFile) return;
    const formData = new FormData();
    formData.append("file", importFile);
    formData.append("mapping", JSON.stringify(importMapping));
    formData.append("stock_mode", stockMode);
    setImportBusy(true);
    setImportConfirmOpen(false);
    try {
      const response = await api.request({
        method: "POST",
        url: PRODUCT_UPLOAD_URL,
        data: formData,
      });
      toast.success(response.data.message);
      setImportFile(null);
      setImportPreview(null);
      setImportMapping({});
      try {
        await load();
      } catch {
        toast.error("პროდუქტები შეინახა, თუმცა სიის განახლება ვერ მოხერხდა.");
      }
    } catch (error) {
      const detail = error.response?.data?.detail;
      const message = typeof detail === "string" ? detail : detail?.message;
      toast.error(message || "მონაცემების შენახვა ვერ მოხერხდა. გადაამოწმეთ მონაცემები და სცადეთ ხელახლა.");
      if (detail?.errors) setImportPreview((preview) => ({ ...preview, errors: detail.errors }));
    } finally {
      setImportBusy(false);
    }
  };

  const confirmImport = () => setImportConfirmOpen(true);
  const importMappingChanged = importPreview && JSON.stringify(importMapping) !== JSON.stringify(importPreview.mapping);
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
    } catch { toast.error("სურათის დამუშავება ვერ მოხერხდა. სცადეთ სხვა ფაილი."); }
    finally { setImgLoading(false); }
  };

  const load = () => api.get("/auth/me").then((u) => api.get(`/products?supplier_id=${u.data.id}`)).then((r) => setProducts(r.data));
  useEffect(() => { load(); }, []);

  const openNew = () => { setEditing("new"); setForm(EMPTY); };
  const openEdit = (p) => {
    setEditing(p.id);
    setForm({ ...p, price_per_unit: String(p.price_per_unit), moq: String(p.moq), stock: String(p.stock),
      sku: p.sku || "", barcode: p.barcode || "", unit: p.unit || "",
      tier_pricing: [0, 1, 2].map((i) => p.tier_pricing?.[i] ? { min_qty: String(p.tier_pricing[i].min_qty), price: String(p.tier_pricing[i].price) } : { min_qty: "", price: "" }) });
  };

  const save = async () => {
    const tiers = form.tier_pricing.filter((x) => x.min_qty && x.price).map((x) => ({ min_qty: parseInt(x.min_qty), price: parseFloat(x.price) }));
    const payload = { name: form.name, category: form.category, city: form.city || "", price_per_unit: parseFloat(form.price_per_unit) || 0,
      moq: parseInt(form.moq) || 1, stock: parseInt(form.stock) || 0, image: form.image, description: form.description, tier_pricing: tiers };
    payload.sku = form.sku || "";
    payload.barcode = form.barcode || "";
    payload.unit = form.unit || "";
    if (!payload.name) { toast.error("პროდუქტის სახელი სავალდებულოა."); return; }
    try {
      if (editing === "new") await api.post("/products", payload);
      else await api.put(`/products/${editing}`, payload);
      toast.success("პროდუქტი წარმატებით შეინახა.");
      setEditing(null); load();
    } catch { toast.error("პროდუქტის შენახვა ვერ მოხერხდა. გადაამოწმეთ მონაცემები და სცადეთ ხელახლა."); }
  };

  const doDelete = async () => {
    try { await api.delete(`/products/${deleteId}`); toast.success("პროდუქტი წარმატებით წაიშალა."); setDeleteId(null); load(); }
    catch { toast.error("პროდუქტის წაშლა ვერ მოხერხდა. სცადეთ ხელახლა."); }
  };

  const setTier = (i, k, v) => setForm((f) => ({ ...f, tier_pricing: f.tier_pricing.map((x, j) => j === i ? { ...x, [k]: v } : x) }));

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div><h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{t("inv.title")}</h1><p className="mt-1 text-sm text-muted-foreground">{products.length} {t("inv.productsCount")}</p></div>
        {isSupplierOwner && <div className="flex items-center gap-2">
        <Button onClick={openNew} disabled={!canEditInventory} data-testid="add-product-btn"><Plus className="mr-1.5 h-4 w-4" /> {t("inv.addProduct")}</Button>
        {/* დამალული ინფუთი ფაილის ასარჩევად */}
  <input 
    type="file" 
    ref={fileInputRef} 
    style={{ display: 'none' }} 
    accept=".xlsx, .xls, .csv, .txt" 
    onChange={handleExcelUpload} 
  />

  {/* ექსელის ატვირთვის ღილაკი */}
  <Button 
    onClick={() => fileInputRef.current?.click()}
    disabled={!canEditInventory}
    variant="outline"
    className="flex items-center gap-2 ml-2"
  >
  <ImageIcon className="h-4 w-4" /> ფასებისა და მარაგების განახლება
  </Button>
        </div>}
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
                  <td className="px-4 py-3"><div className="flex items-center gap-3"><ProductImage image={p.image} name={p.name} category={p.category} alt="" className="h-10 w-10 rounded border border-border object-cover" /><span className="max-w-xs truncate font-medium">{p.name}</span></div></td>
                  <td className="px-4 py-3 text-muted-foreground">{t(categoryKey(p.category))}</td>
                  <td className="px-4 py-3 font-semibold">₾{(p.price_per_unit ?? p.price ?? 0).toFixed(2)} <span className="text-xs font-normal text-muted-foreground">/ {p.unit || "ერთეული"}</span></td>
                  <td className="px-4 py-3 font-mono">{p.moq}</td>
                  <td className="px-4 py-3"><Badge className={p.stock < 50 ? "bg-processing/15 text-processing" : "bg-delivered/15 text-delivered"}>{p.stock}</Badge></td>
                  <td className="px-4 py-3"><div className="flex justify-end gap-1">
                    <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => openEdit(p)} disabled={!canEditInventory} data-testid={`edit-product-${p.id}`}><Pencil className="h-4 w-4" /></Button>
                    {isSupplierOwner && <Button variant="ghost" size="icon" className="h-8 w-8 text-rose-500 hover:bg-rose-500/10" onClick={() => setDeleteId(p.id)} data-testid={`delete-product-${p.id}`}><Trash2 className="h-4 w-4" /></Button>}
                  </div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Dialog open={!!importFile} onOpenChange={(open) => !open && closeImport()}>
        <DialogContent className="max-h-[90vh] overflow-y-auto bg-card sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>პროდუქტების იმპორტი</DialogTitle>
            <DialogDescription>{importFile?.name}</DialogDescription>
          </DialogHeader>
          {importBusy && !importPreview ? (
            <p className="text-sm text-muted-foreground">ფაილი მუშავდება...</p>
          ) : importPreview && (
            <div className="space-y-4">
              <div className="grid gap-2 text-sm sm:grid-cols-2">
                <p>დასამატებელი პროდუქტი: <strong>{importPreview.new_count}</strong></p>
                <p>განახლდება არსებული პროდუქტი: <strong>{importPreview.update_count}</strong></p>
                <p>ფაილში გამეორებული ჩანაწერი: <strong>{importPreview.duplicate_count}</strong></p>
                <p>აღმოჩენილი შეცდომა: <strong>{importPreview.errors.length}</strong></p>
              </div>
              <div>
                <Label htmlFor="import-stock-mode">არსებული პროდუქტის მარაგი</Label>
                <select id="import-stock-mode" value={stockMode} onChange={(event) => setStockMode(event.target.value)} className="mt-1 h-9 w-full rounded-md border border-input bg-background px-2 text-sm">
                  <option value="add">დაემატოს არსებულ მარაგს</option>
                  <option value="replace">ჩანაცვლდეს ახალი ნაშთით</option>
                  <option value="new_only">მხოლოდ ახალი პროდუქტების დამატება (არსებულს არ შეეხოს)</option>
                </select>
              </div>
              <details open={importPreview.missing_columns.length > 0 || importPreview.unmapped_columns.length > 0} className="rounded-md border border-border p-3">
                <summary className="cursor-pointer text-sm font-medium">სვეტების შესაბამისობის არჩევა</summary>
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  {IMPORT_FIELDS.map(([field, label]) => (
                    <div key={field}>
                      <Label htmlFor={`import-${field}`}>{label}</Label>
                      <select id={`import-${field}`} value={importMapping[field] || ""} onChange={(event) => setImportMapping((current) => ({ ...current, [field]: event.target.value }))} className="mt-1 h-9 w-full rounded-md border border-input bg-background px-2 text-sm">
                        <option value="">არ არის შეხამებული</option>
                        {importPreview.columns.map((column) => <option key={`${field}-${column}`} value={column}>{column}</option>)}
                      </select>
                    </div>
                  ))}
                </div>
                <Button type="button" variant="outline" className="mt-3" onClick={refreshImportPreview} disabled={importBusy}>წინასწარი გადახედვის განახლება</Button>
              </details>
              {importPreview.unmapped_columns.length > 0 && <p className="text-xs text-muted-foreground">შეუხამებელი სვეტები: {importPreview.unmapped_columns.join(", ")}</p>}
              {importPreview.errors.length > 0 && (
                <div className="max-h-48 space-y-2 overflow-y-auto rounded-md border border-destructive/30 p-3" role="alert">
                  <p className="text-sm font-medium">შეცდომები ფაილში</p>
                  {importPreview.errors.map((item, index) => (
                    <p key={`${item.row}-${item.column}-${index}`} className="text-xs text-muted-foreground">
                      სტრიქონი {item.row}, სვეტი „{item.column}“: {item.message}
                    </p>
                  ))}
                </div>
              )}
            </div>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={closeImport} disabled={importBusy}>გაუქმება</Button>
            <Button type="button" onClick={confirmImport} disabled={importBusy || importMappingChanged || !importPreview?.valid_count || importPreview.errors.length > 0 || (stockMode === "new_only" && !importPreview.new_count)}>
              {importBusy ? "იტვირთება..." : "იმპორტი"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={importConfirmOpen} onOpenChange={setImportConfirmOpen}>
        <AlertDialogContent className="bg-card">
          <AlertDialogHeader>
            <AlertDialogTitle>იმპორტის დადასტურება</AlertDialogTitle>
            <AlertDialogDescription>{stockMode === "new_only" ? `დაემატება ${importPreview?.new_count || 0} ახალი პროდუქტი. არსებული ${importPreview?.update_count || 0} პროდუქტი არ შეიცვლება.` : `დაემატება ${importPreview?.new_count || 0} ახალი პროდუქტი და განახლდება ${importPreview?.update_count || 0} არსებული პროდუქტი.`} დუბლიკატი ჩანაწერები: {importPreview?.duplicate_count || 0}. გაგრძელება?</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setImportConfirmOpen(false)}>გაუქმება</AlertDialogCancel>
            <AlertDialogAction onClick={saveImport}>დადასტურება</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <Dialog open={!!editing} onOpenChange={(o) => !o && setEditing(null)}>
        <DialogContent className="max-h-[90vh] overflow-y-auto bg-card sm:max-w-xl">
          <DialogHeader><DialogTitle>{editing === "new" ? t("inv.addProduct") : t("inv.editProduct")}</DialogTitle><DialogDescription>{t("inv.tierPricing")}</DialogDescription></DialogHeader>
          <div className="space-y-3">
            {!isSupplierOwner ? (
              <div><Label>{t("common.stock")}</Label><Input type="number" min="0" value={form.stock} onChange={(e) => setForm({ ...form, stock: e.target.value })} className="mt-1.5" data-testid="product-stock" /></div>
            ) : (
              <>
            <div><Label>{t("inv.productName")}</Label><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="mt-1.5" data-testid="product-name" /></div>
            <div className="grid grid-cols-2 gap-3">
              <div><Label>{t("common.category")}</Label><select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} className="mt-1.5 h-10 w-full rounded-md border border-input bg-background px-3 text-sm" data-testid="product-category">{form.category && !cats.includes(form.category) && !CATEGORY_VALUES.includes(form.category) && <option value={form.category}>{t(categoryKey(form.category))}</option>}{[...new Set(cats.length ? cats : CATEGORY_VALUES)].map((c, index) => <option key={`${c}-${index}`} value={c}>{t(categoryKey(c))}</option>)}</select></div>
              <div><Label>{t("inv.basePrice")}</Label><Input type="number" value={form.price_per_unit} onChange={(e) => setForm({ ...form, price_per_unit: e.target.value })} className="mt-1.5" data-testid="product-price" /></div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div><Label>SKU / კოდი</Label><Input value={form.sku} onChange={(e) => setForm({ ...form, sku: e.target.value })} className="mt-1.5" data-testid="product-sku" /></div>
              <div><Label>შტრიხკოდი</Label><Input value={form.barcode} onChange={(e) => setForm({ ...form, barcode: e.target.value })} className="mt-1.5" data-testid="product-barcode" /></div>
              <div><Label>საზომი ერთეული</Label><Input value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })} className="mt-1.5" placeholder="ცალი, კგ, ლ" data-testid="product-unit" /></div>
            </div>
            <div><Label>{t("reg.city")}</Label><Input value={form.city || ""} onChange={(e) => setForm({ ...form, city: e.target.value })} className="mt-1.5" data-testid="product-city" placeholder="Tbilisi" /></div>
            <div className="grid grid-cols-2 gap-3">
              <div><Label>{t("inv.moqUnits")}</Label><Input type="number" value={form.moq} onChange={(e) => setForm({ ...form, moq: e.target.value })} className="mt-1.5" data-testid="product-moq" /></div>
              <div><Label>{t("common.stock")}</Label><Input type="number" value={form.stock} onChange={(e) => setForm({ ...form, stock: e.target.value })} className="mt-1.5" data-testid="product-stock" /></div>
            </div>
            <div>
              <Label>{t("inv.imageLabel")}</Label>
              <div className="mt-1.5 flex items-start gap-3">
                <div className="flex h-24 w-24 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-dashed border-border bg-secondary" data-testid="image-preview">
                  {imgLoading ? <span className="text-[11px] text-muted-foreground">{t("inv.processing")}</span>
                    : form.image ? <ProductImage image={form.image} name={form.name} category={form.category} alt={t("inv.preview")} className="h-full w-full object-cover" data-testid="image-preview-thumb" />
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
              </>
            )}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setEditing(null)}>{t("common.cancel")}</Button>
            <Button type="button" onClick={save}>{t("common.save")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={!!deleteId} onOpenChange={(o) => !o && setDeleteId(null)}>
        <AlertDialogContent className="bg-card">
          <AlertDialogHeader>
            <AlertDialogTitle>წავშალო პროდუქტი?</AlertDialogTitle>
            <AlertDialogDescription>ამ მოქმედების გაუქმება შეუძლებელია.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>გაუქმება</AlertDialogCancel>
            <AlertDialogAction onClick={doDelete} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">
              წაშლა
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}