import { useEffect, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { useI18n } from "@/context/I18nContext";
import { Plus, Save, Percent, Tags } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

export default function AdminSettings() {
  const { t } = useI18n();
  const [s, setS] = useState(null);
  const [cats, setCats] = useState([]);
  const [newCat, setNewCat] = useState("");

  useEffect(() => {
    api.get("/settings").then((r) => setS(r.data));
    api.get("/categories").then((r) => setCats(r.data));
  }, []);

  const saveFee = async () => {
    try { const { data } = await api.put("/admin/settings", { fee_type: s.fee_type, fee_value: parseFloat(s.fee_value) || 0, fee_payer: s.fee_payer }); setS(data); toast.success(t("adm.feeSaved")); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const addCat = async () => {
    if (!newCat.trim()) return;
    try { const { data } = await api.post("/categories", { name: newCat.trim() }); setCats(data); setNewCat(""); toast.success(t("cat.added")); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  if (!s) return <div className="h-64 animate-pulse rounded-xl bg-secondary" />;

  return (
    <div className="max-w-2xl space-y-6">
      <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{t("nav.settings")}</h1>

      <div className="rounded-xl border border-border bg-card p-6">
        <h3 className="flex items-center gap-2 text-lg font-semibold"><Percent className="h-5 w-5 text-primary" /> {t("adm.feeSettings")}</h3>
        <div className="mt-4 space-y-4">
          <div>
            <Label>{t("adm.feeType")}</Label>
            <div className="mt-1.5 flex gap-2">
              {[["percent", "adm.feePercent"], ["fixed", "adm.feeFixed"]].map(([v, k]) => (
                <button key={v} onClick={() => setS({ ...s, fee_type: v })} data-testid={`fee-type-${v}`}
                  className={cn("flex-1 rounded-lg border-2 px-3 py-2 text-sm font-medium transition-colors duration-200", s.fee_type === v ? "border-primary bg-primary/5 text-foreground" : "border-border text-muted-foreground")}>{t(k)}</button>
              ))}
            </div>
          </div>
          <div><Label htmlFor="fv">{t("adm.feeValue")}</Label><Input id="fv" type="number" value={s.fee_value} onChange={(e) => setS({ ...s, fee_value: e.target.value })} className="mt-1.5" data-testid="fee-value" /></div>
          <div>
            <Label>{t("adm.feePayer")}</Label>
            <div className="mt-1.5 grid grid-cols-3 gap-2">
              {[["supplier", "adm.payerSupplier"], ["retailer", "adm.payerRetailer"], ["split", "adm.paySplit"]].map(([v, k]) => (
                <button key={v} onClick={() => setS({ ...s, fee_payer: v })} data-testid={`fee-payer-${v}`}
                  className={cn("rounded-lg border-2 px-2 py-2 text-xs font-medium transition-colors duration-200", s.fee_payer === v ? "border-primary bg-primary/5 text-foreground" : "border-border text-muted-foreground")}>{t(k)}</button>
              ))}
            </div>
          </div>
          <Button onClick={saveFee} data-testid="save-fee-btn"><Save className="mr-1.5 h-4 w-4" /> {t("adm.saveFee")}</Button>
        </div>
      </div>

      <div className="rounded-xl border border-border bg-card p-6">
        <h3 className="flex items-center gap-2 text-lg font-semibold"><Tags className="h-5 w-5 text-primary" /> {t("cat.manage")}</h3>
        <div className="mt-4 flex flex-wrap gap-2">
          {cats.map((c) => <Badge key={c} className="bg-secondary text-secondary-foreground" data-testid={`category-chip-${c}`}>{c}</Badge>)}
        </div>
        <div className="mt-4 flex gap-2">
          <Input value={newCat} onChange={(e) => setNewCat(e.target.value)} placeholder={t("cat.addNew")} data-testid="new-category-input" onKeyDown={(e) => e.key === "Enter" && addCat()} />
          <Button onClick={addCat} data-testid="add-category-btn"><Plus className="mr-1.5 h-4 w-4" /> {t("cat.addNew")}</Button>
        </div>
      </div>
    </div>
  );
}
