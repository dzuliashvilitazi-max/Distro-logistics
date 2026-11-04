import { useCallback, useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { toast } from "sonner";
import { api, formatApiError } from "@/lib/api";
import { useI18n } from "@/context/I18nContext";
import { categoryKey } from "@/lib/i18n";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function CategoryCheckboxes({ value = [], onChange, idPrefix = "cat" }) {
  const { t } = useI18n();
  const [options, setOptions] = useState([]);
  const [newName, setNewName] = useState("");
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api.get("/categories/options");
      setOptions(r.data || []);
      return r.data || [];
    } catch {
      setOptions([]);
      return [];
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const toggle = (id, checked) => {
    onChange(checked ? [...new Set([...value, id])] : value.filter((v) => v !== id));
  };

  const addCategory = async () => {
    const name = newName.trim();
    if (!name) return;
    setAdding(true);
    try {
      await api.post("/categories", { name });
      const list = await load();
      const lower = name.toLowerCase();
      const created = list.find((o) => o.name.toLowerCase() === lower)
        || list.find((o) => t(categoryKey(o.name)).toLowerCase() === lower);
      if (created) onChange([...new Set([...value, created.id])]);
      setNewName("");
      toast.success(t("cat.added"));
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail));
    } finally {
      setAdding(false);
    }
  };

  return (
    <section className="rounded-lg border border-border p-4" data-testid="category-checkboxes">
      <Label className="text-sm font-semibold">{t("auth.category")}</Label>
      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
        {options.map((o) => (
          <div key={o.id} className="flex items-center gap-2">
            <Checkbox id={`${idPrefix}-${o.id}`} checked={value.includes(o.id)} onCheckedChange={(c) => toggle(o.id, c === true)} data-testid={`category-${o.name}`} />
            <Label htmlFor={`${idPrefix}-${o.id}`} className="font-normal">{t(categoryKey(o.name))}</Label>
          </div>
        ))}
      </div>
      <div className="mt-4 flex gap-2 border-t border-border pt-3">
        <Input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addCategory(); } }}
          placeholder={t("cat.addNew")}
          data-testid="new-category-input"
        />
        <Button type="button" variant="outline" onClick={addCategory} disabled={adding || !newName.trim()} data-testid="add-category-btn">
          <Plus className="mr-1 h-4 w-4" /> {t("cat.addNew")}
        </Button>
      </div>
    </section>
  );
}
