import { useEffect, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { useI18n } from "@/context/I18nContext";
import { StatusBadge } from "@/components/StatusBadge";
import { Check, Ban, RotateCcw, Percent, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

const TABS = [["all", "usr.all"], ["retailer", "usr.retailers"], ["supplier", "usr.suppliers"], ["admin", "usr.admins"]];
const PAYERS = [["", "ზოგადი პარამეტრი"], ["supplier", "დისტრიბუტორი"], ["retailer", "მაღაზია"], ["split", "ორივე (50/50)"]];

export default function AdminUsers() {
  const { t } = useI18n();
  const [users, setUsers] = useState([]);
  const [tab, setTab] = useState("all");
  const [commissionUser, setCommissionUser] = useState(null);
  const [form, setForm] = useState({ enabled: false, type: "percent", value: "", payer: "" });
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState(null);

  const load = () => api.get(`/admin/users?role=${tab}`).then((r) => setUsers(r.data));
  useEffect(() => { load(); }, [tab]);

  const openCommission = (u) => {
    setCommissionUser(u);
    setForm({
      enabled: !!u.customCommissionType,
      type: u.customCommissionType || "percent",
      value: u.customCommissionValue ?? "",
      payer: u.commissionPayer || "",
    });
  };

  const saveCommission = async () => {
    const value = parseFloat(form.value);
    if (form.enabled && (Number.isNaN(value) || value < 0)) { toast.error("მიუთითეთ საკომისიოს სწორი ოდენობა."); return; }
    if (form.enabled && form.type === "percent" && value > 100) { toast.error("პროცენტი არ უნდა აღემატებოდეს 100-ს."); return; }
    setSaving(true);
    try {
      await api.put(`/admin/users/${commissionUser.id}/commission`, {
        enabled: form.enabled, customCommissionType: form.type, customCommissionValue: form.enabled ? value : null,
        commissionPayer: form.payer || null,
      });
      toast.success("ინდივიდუალური საკომისიო შენახულია.");
      setCommissionUser(null);
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setSaving(false); }
  };

  const setStatus = async (id, status) => {
    try { await api.put(`/admin/users/${id}/status`, { status }); toast.success(status === "active" ? t("usr.approved") : t("usr.updated")); load(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const deleteUser = async (user) => {
    if (!window.confirm("ნამდვილად გსურთ მომხმარებლის წაშლა?")) return;
    setDeletingId(user.id);
    try {
      await api.delete(`/admin/users/${encodeURIComponent(user.id)}`);
      setUsers((current) => current.filter((item) => item.id !== user.id));
      toast.success("მომხმარებელი წაიშალა.");
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setDeletingId(null); }
  };

  const pending = users.filter((u) => u.role === "supplier" && u.status === "pending");

  return (
    <div>
      <h1 className="mb-6 text-2xl font-bold tracking-tight sm:text-3xl">{t("usr.title")}</h1>

      {pending.length > 0 && (
        <div className="mb-6 rounded-xl border border-processing/30 bg-processing/5 p-5" data-testid="approval-queue">
          <h3 className="text-lg font-semibold text-processing">{t("usr.approvalQueue")} ({pending.length})</h3>
          <div className="mt-3 space-y-2">
            {pending.map((u) => (
              <div key={u.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-card px-4 py-3">
                <div><p className="font-semibold">{u.business_name}</p><p className="font-mono text-xs text-muted-foreground">{u.email} · {u.address}</p></div>
                <div className="flex gap-2">
                  <Button size="sm" onClick={() => setStatus(u.id, "active")} data-testid={`approve-supplier-${u.id}`}><Check className="mr-1 h-4 w-4" /> {t("usr.approve")}</Button>
                  <Button size="sm" variant="outline" className="text-rose-500 hover:bg-rose-500/10" onClick={() => setStatus(u.id, "suspended")} data-testid={`reject-supplier-${u.id}`}><Ban className="mr-1 h-4 w-4" /> {t("usr.reject")}</Button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="mb-5 flex flex-wrap gap-2">
        {TABS.map(([v, lk]) => (
          <button key={v} onClick={() => setTab(v)} data-testid={`user-tab-${v}`}
            className={cn("rounded-full border px-4 py-1.5 text-sm font-medium transition-colors duration-200", tab === v ? "border-primary bg-primary text-primary-foreground" : "border-border text-muted-foreground hover:text-foreground")}>{t(lk)}</button>
        ))}
      </div>

      <div className="overflow-x-auto rounded-xl border border-border bg-card">
        <table className="w-full text-sm">
          <thead className="border-b border-border bg-secondary/50"><tr className="text-left font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
            <th className="px-4 py-3">{t("common.business")}</th><th className="px-4 py-3">{t("common.email")}</th><th className="px-4 py-3">{t("common.role")}</th><th className="px-4 py-3">{t("common.status")}</th><th className="px-4 py-3 text-right">{t("common.actions")}</th>
          </tr></thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} data-testid={`user-row-${u.id}`} className="border-b border-border/50 last:border-0">
                <td className="px-4 py-3 font-medium">
                  {u.business_name}
                  {u.customCommissionType && (
                    <span className="ml-2 rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold text-amber-500">
                      საკომისიო: {u.customCommissionValue}{u.customCommissionType === "percent" ? "%" : " ₾"}
                    </span>
                  )}
                </td>
                <td className="px-4 py-3 text-muted-foreground">{u.email}</td>
                <td className="px-4 py-3"><span className="rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 font-mono text-[10px] font-semibold text-primary">{t(`roles.${u.role}`)}</span></td>
                <td className="px-4 py-3"><StatusBadge status={u.status || "active"} /></td>
                <td className="px-4 py-3"><div className="flex justify-end gap-1.5">
                  {(u.role === "retailer" || u.role === "supplier") && (
                    <Button size="sm" variant="outline" onClick={() => openCommission(u)} data-testid={`commission-user-${u.id}`}><Percent className="mr-1 h-3.5 w-3.5" /> საკომისიო</Button>
                  )}                  {u.role !== "admin" && (u.status === "active"
                    ? <Button size="sm" variant="outline" className="text-rose-500 hover:bg-rose-500/10" onClick={() => setStatus(u.id, "suspended")} data-testid={`suspend-user-${u.id}`}><Ban className="mr-1 h-3.5 w-3.5" /> {t("usr.suspend")}</Button>
                    : <Button size="sm" variant="outline" onClick={() => setStatus(u.id, "active")} data-testid={`activate-user-${u.id}`}><RotateCcw className="mr-1 h-3.5 w-3.5" /> {t("usr.activate")}</Button>)}
                  <Button type="button" size="icon" variant="ghost" className="h-8 w-8 text-destructive hover:bg-destructive/10" onClick={() => deleteUser(u)} disabled={deletingId === u.id} aria-label="მომხმარებლის წაშლა" title="მომხმარებლის წაშლა" data-testid={`delete-user-${u.id}`}><Trash2 className="h-4 w-4" /></Button>
                </div></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={!!commissionUser} onOpenChange={(open) => !open && setCommissionUser(null)}>
        <DialogContent className="bg-card sm:max-w-md">
          <DialogHeader>
            <DialogTitle>ინდივიდუალური საკომისიო</DialogTitle>
            <DialogDescription>{commissionUser?.business_name}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <label className="flex items-center justify-between gap-3 rounded-lg border border-border p-3 text-sm font-medium">
              <span>ინდივიდუალური საკომისიოს გამოყენება</span>
              <input type="checkbox" role="switch" className="h-5 w-5" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} data-testid="commission-toggle" />
            </label>
            {!form.enabled && <p className="text-xs text-muted-foreground">გამორთვისას გამოიყენება პლატფორმის ზოგადი საკომისიო.</p>}
            {form.enabled && (
              <>
                <div className="grid grid-cols-2 gap-2">
                  {[["percent", "პროცენტული (%)"], ["fixed", "ფიქსირებული (₾)"]].map(([v, label]) => (
                    <button key={v} type="button" onClick={() => setForm({ ...form, type: v })}
                      className={cn("rounded-lg border-2 px-2 py-2 text-xs font-medium", form.type === v ? "border-primary bg-primary/5 text-foreground" : "border-border text-muted-foreground")}>{label}</button>
                  ))}
                </div>
                <label className="block space-y-1 text-xs text-muted-foreground">
                  <span>ოდენობა ({form.type === "percent" ? "%" : "₾ / შეკვეთაზე"})</span>
                  <input type="number" min="0" step="0.01" className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm text-foreground" value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} data-testid="commission-value" />
                </label>
                <label className="block space-y-1 text-xs text-muted-foreground">
                  <span>ვინ იხდის საკომისიოს</span>
                  <select className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm text-foreground" value={form.payer} onChange={(e) => setForm({ ...form, payer: e.target.value })}>
                    {PAYERS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
                  </select>
                </label>
              </>
            )}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setCommissionUser(null)} disabled={saving}>გაუქმება</Button>
            <Button type="button" onClick={saveCommission} disabled={saving} data-testid="commission-save">შენახვა</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
