import { useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { useStoreBranch } from "@/context/StoreBranchContext";
import { useI18n } from "@/context/I18nContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { MapPin, Pencil, Plus, Store } from "lucide-react";
import { toast } from "sonner";

const EMPTY = { name: "", address: "", phone: "", active: true };

export default function StoreBranches() {
  const { t } = useI18n();
  const { branches, activeBranchId, selectBranch, refreshBranches } = useStoreBranch();
  const [branchDialog, setBranchDialog] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);

  const openNew = () => { setEditing(null); setForm(EMPTY); setBranchDialog(true); };
  const openEdit = (branch) => {
    setEditing(branch);
    setForm({ name: branch.name, address: branch.address || "", phone: branch.phone || "", active: branch.active !== false });
    setBranchDialog(true);
  };

  const save = async (event) => {
    event.preventDefault();
    setSaving(true);
    try {
      if (editing) await api.put(`/store/branches/${encodeURIComponent(editing.id)}`, form);
      else await api.post("/store/branches", form);
      await refreshBranches();
      toast.success(t("branch.saved"));
      setBranchDialog(false);
    } catch (error) {
      toast.error(formatApiError(error.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6" data-testid="store-branches-page">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2"><Store className="h-6 w-6 text-primary" /><h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{t("branch.title")}</h1></div>
          <p className="mt-1 text-sm text-muted-foreground">{t("branch.subtitle")}</p>
        </div>
        <Button onClick={openNew}><Plus className="mr-1.5 h-4 w-4" />{t("branch.add")}</Button>
      </header>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {branches.map((branch) => (
          <article key={branch.id} className={`rounded-xl border bg-card p-5 ${branch.id === activeBranchId ? "border-primary/50 ring-1 ring-primary/20" : "border-border"}`} data-testid={`store-branch-${branch.id}`}>
            <div className="flex items-start justify-between gap-2">
              <div>
                <h2 className="font-semibold">{branch.name}</h2>
                <div className="mt-2 flex items-start gap-2 text-sm text-muted-foreground"><MapPin className="mt-0.5 h-4 w-4 shrink-0" /><span>{branch.address || t("branch.noAddress")}</span></div>
                {branch.phone && <p className="mt-2 text-sm text-muted-foreground">{branch.phone}</p>}
              </div>
              {branch.is_default && <span className="rounded-full border border-primary/30 bg-primary/10 px-2 py-1 text-[10px] font-semibold text-primary">{t("branch.default")}</span>}
            </div>
            <div className="mt-5 flex gap-2">
              <Button className="flex-1" size="sm" variant={branch.id === activeBranchId ? "secondary" : "outline"} disabled={branch.active === false} onClick={() => selectBranch(branch.id)}>
                {branch.id === activeBranchId ? t("branch.active") : t("branch.switchTo")}
              </Button>
              <Button size="sm" variant="outline" onClick={() => openEdit(branch)} aria-label={t("branch.edit")}><Pencil className="h-4 w-4" /></Button>
            </div>
          </article>
        ))}
        {branches.length === 0 && <div className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground md:col-span-2 xl:col-span-3">{t("branch.empty")}</div>}
      </div>

      <Dialog open={branchDialog} onOpenChange={setBranchDialog}>
        <DialogContent>
          <DialogHeader><DialogTitle>{editing ? t("branch.edit") : t("branch.add")}</DialogTitle><DialogDescription>{t("branch.subtitle")}</DialogDescription></DialogHeader>
          <form className="space-y-4" onSubmit={save}>
            <div><Label htmlFor="branch-name">{t("branch.name")}</Label><Input id="branch-name" className="mt-1" required maxLength={120} value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></div>
            <div><Label htmlFor="branch-address">{t("branch.address")}</Label><Input id="branch-address" className="mt-1" required maxLength={500} value={form.address} onChange={(event) => setForm({ ...form, address: event.target.value })} /></div>
            <div><Label htmlFor="branch-phone">{t("branch.phone")}</Label><Input id="branch-phone" className="mt-1" maxLength={40} value={form.phone} onChange={(event) => setForm({ ...form, phone: event.target.value })} /></div>
            {editing && !editing.is_default && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.active} onChange={(event) => setForm({ ...form, active: event.target.checked })} />{t("branch.active")}</label>}
            <DialogFooter><Button type="submit" disabled={saving}>{saving ? t("common.saving") : t("common.save")}</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
