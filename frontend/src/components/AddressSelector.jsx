import { useState } from "react";
import { MapPin, Plus, Loader2 } from "lucide-react";
import { api, formatApiError } from "@/lib/api";
import { useStoreBranch } from "@/context/StoreBranchContext";
import { useI18n } from "@/context/I18nContext";
import AddressMapPicker from "@/components/AddressMapPicker";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { toast } from "sonner";

const branchLocation = (branch) => ({
  address: branch?.address || "",
  city: branch?.city || "",
  label: [branch?.address, branch?.city].filter(Boolean).join(", "),
  lat: branch?.lat ?? branch?.route_coordinates?.lat ?? null,
  lng: branch?.lng ?? branch?.route_coordinates?.lng ?? branch?.route_coordinates?.lon ?? null,
});

export default function AddressSelector({ canManage = false }) {
  const { branches, activeBranch, activeBranchId, selectBranch, refreshBranches } = useStoreBranch();
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [draftBranchId, setDraftBranchId] = useState("");
  const [draftLocation, setDraftLocation] = useState(branchLocation(activeBranch));
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);

  const openSelector = () => {
    setAdding(false);
    setDraftBranchId(activeBranch?.id || activeBranchId);
    setDraftLocation(branchLocation(activeBranch));
    setName(activeBranch?.name || "");
    setOpen(true);
  };

  const chooseBranch = (branch) => {
    if (branch.active === false) return;
    selectBranch(branch.id);
    setAdding(false);
    setDraftBranchId(branch.id);
    setDraftLocation(branchLocation(branch));
    setName(branch.name || "");
  };

  const startAdding = () => {
    setAdding(true);
    setDraftBranchId("");
    setDraftLocation({ address: "", city: "", lat: null, lng: null });
    setName(`${t("address.newAddress")} ${branches.length + 1}`);
  };

  const saveLocation = async () => {
    if (!draftLocation.address || !Number.isFinite(draftLocation.lat) || !Number.isFinite(draftLocation.lng)) {
      toast.error(t("address.pinRequired"));
      return;
    }
    setSaving(true);
    const selected = branches.find((branch) => branch.id === draftBranchId);
    const payload = {
      name: (name || draftLocation.address).trim(),
      address: draftLocation.address,
      city: draftLocation.city || "",
      phone: selected?.phone || "",
      lat: draftLocation.lat,
      lng: draftLocation.lng,
      active: selected?.active !== false,
    };
    try {
      const response = adding
        ? await api.post("/store/branches", payload)
        : await api.put(`/store/branches/${encodeURIComponent(draftBranchId)}`, payload);
      await refreshBranches(response.data.id);
      setOpen(false);
      toast.success(t(adding ? "address.added" : "address.saved"));
    } catch (error) {
      toast.error(formatApiError(error.response?.data?.detail) || t("address.saveError"));
    } finally {
      setSaving(false);
    }
  };

  if (!activeBranch) return null;
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button type="button" variant="outline" onClick={openSelector} className="h-10 max-w-56 justify-start gap-2 px-2.5 sm:max-w-72" data-testid="address-selector-trigger" aria-label={t("address.title")}>
          <MapPin className="h-4 w-4 shrink-0 text-primary" />
          <span className="truncate text-left text-xs font-medium sm:text-sm">{[activeBranch.address || activeBranch.name, activeBranch.city].filter(Boolean).join(", ")}</span>
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[92vh] w-[calc(100%-1rem)] max-w-5xl overflow-x-hidden overflow-y-auto sm:w-full">
        <DialogHeader>
          <DialogTitle>{t("address.title")}</DialogTitle>
          <DialogDescription>{t("address.description")}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 md:grid-cols-[minmax(190px,0.65fr)_minmax(0,1.35fr)]">
          <section className="space-y-2" aria-label={t("address.savedAddresses")}>
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-sm font-semibold">{t("address.savedAddresses")}</h3>
              {canManage && <Button type="button" size="sm" variant="outline" onClick={startAdding} data-testid="address-add-new"><Plus className="h-4 w-4" />{t("address.add")}</Button>}
            </div>
            <div className="max-h-48 space-y-1 overflow-y-auto md:max-h-[420px]">
              {branches.filter((branch) => branch.active !== false).map((branch) => (
                <button key={branch.id} type="button" onClick={() => chooseBranch(branch)} className={`w-full rounded-md border px-3 py-2 text-left ${branch.id === draftBranchId && !adding ? "border-primary bg-primary/5" : "border-border hover:bg-secondary/60"}`} data-testid={`address-option-${branch.id}`}>
                  <span className="block truncate text-sm font-medium">{branch.name}</span>
                  <span className="mt-0.5 block break-words text-xs text-muted-foreground">{[branch.address, branch.city].filter(Boolean).join(", ") || t("branch.noAddress")}</span>
                </button>
              ))}
            </div>
            {adding && <div className="space-y-1"><Label htmlFor="new-address-name">{t("address.name")}</Label><Input id="new-address-name" value={name} onChange={(event) => setName(event.target.value)} maxLength={120} data-testid="address-new-name" /></div>}
          </section>
          <section className="min-w-0 space-y-3 overflow-hidden">
            {!adding && <div className="space-y-1"><Label htmlFor="selected-address-name">{t("address.name")}</Label><Input id="selected-address-name" value={name} onChange={(event) => setName(event.target.value)} disabled={!canManage} maxLength={120} /></div>}
            <AddressMapPicker value={draftLocation} onChange={setDraftLocation} disabled={!canManage} />
          </section>
        </div>
        {canManage && (
          <DialogFooter>
            <Button type="button" onClick={saveLocation} disabled={saving || !draftBranchId && !adding} data-testid="address-save-pin">
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <MapPin className="h-4 w-4" />}{t(adding ? "address.add" : "address.savePin")}
            </Button>
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}