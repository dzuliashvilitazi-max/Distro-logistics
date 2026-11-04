import { Fragment, useEffect, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { useStoreBranch } from "@/context/StoreBranchContext";
import { useI18n } from "@/context/I18nContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Loader2, Users } from "lucide-react";
import { toast } from "sonner";
import { PermissionMatrix, DEFAULT_PERMISSIONS } from "@/components/PermissionMatrix";

const EMPTY_FORM = { name: "", email: "", branch_id: "", role: "staff", permissions: DEFAULT_PERMISSIONS };

export default function StoreStaff() {
  const { t } = useI18n();
  const { branches } = useStoreBranch();
  const [staff, setStaff] = useState([]);
  const [form, setForm] = useState(EMPTY_FORM);
  const [temporaryPassword, setTemporaryPassword] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(null);
  const [editPermissions, setEditPermissions] = useState({});
  const [savingPermissions, setSavingPermissions] = useState(false);

  const startEdit = (member) => {
    setEditing(member.id);
    setEditPermissions({ ...DEFAULT_PERMISSIONS, ...member.permissions });
  };

  const savePermissions = async (member) => {
    setSavingPermissions(true);
    try {
      const { data } = await api.put(`/store/staff/${encodeURIComponent(member.id)}`, { permissions: editPermissions });
      setStaff((current) => current.map((entry) => entry.id === member.id ? { ...entry, permissions: data.permissions } : entry));
      setEditing(null);
      toast.success(t("perm.saved"));
    } catch (error) {
      toast.error(formatApiError(error.response?.data?.detail));
    } finally {
      setSavingPermissions(false);
    }
  };
  const loadStaff = async () => {
    try {
      const { data } = await api.get("/store/staff");
      setStaff(data);
    } catch (error) {
      toast.error(formatApiError(error.response?.data?.detail));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadStaff(); }, []);
  useEffect(() => {
    if (branches.length && !branches.some((branch) => branch.id === form.branch_id)) {
      setForm((current) => ({ ...current, branch_id: branches[0].id }));
    }
  }, [branches, form.branch_id]);

  const createStaff = async (event) => {
    event.preventDefault();
    setSaving(true);
    setTemporaryPassword("");
    try {
      const { data } = await api.post("/store/staff", form);
      setTemporaryPassword(data.temporary_password);
      setForm((current) => ({ ...EMPTY_FORM, branch_id: current.branch_id }));
      toast.success(t("storeStaff.created"));
      await loadStaff();
    } catch (error) {
      toast.error(formatApiError(error.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  };

  const setActive = async (member, active) => {
    try {
      await api.put(`/store/staff/${encodeURIComponent(member.id)}`, { active });
      setStaff((current) => current.map((entry) => entry.id === member.id ? { ...entry, active } : entry));
      toast.success(t(active ? "staff.activated" : "staff.deactivated"));
    } catch (error) {
      toast.error(formatApiError(error.response?.data?.detail));
    }
  };

  return (
    <div className="space-y-6" data-testid="store-staff-page">
      <header>
        <div className="flex items-center gap-2"><Users className="h-6 w-6 text-primary" /><h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{t("storeStaff.title")}</h1></div>
        <p className="mt-1 text-sm text-muted-foreground">{t("storeStaff.subtitle")}</p>
      </header>

      <form onSubmit={createStaff} className="grid gap-4 rounded-xl border border-border bg-card p-5 md:grid-cols-2">
        <div><Label htmlFor="staff-name">{t("staff.name")}</Label><Input id="staff-name" required minLength={2} maxLength={120} value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} className="mt-1" /></div>
        <div><Label htmlFor="staff-email">{t("common.email")}</Label><Input id="staff-email" type="email" required value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} className="mt-1" /></div>
        <div><Label htmlFor="staff-branch">{t("storeStaff.branch")}</Label>
          <select id="staff-branch" required value={form.branch_id} onChange={(event) => setForm({ ...form, branch_id: event.target.value })} className="mt-1 h-10 w-full rounded-md border border-input bg-background px-3 text-sm">
            {branches.filter((branch) => branch.active !== false).map((branch) => <option key={branch.id} value={branch.id}>{branch.name}</option>)}
          </select>
        </div>
        <div><Label htmlFor="staff-role">{t("common.role")}</Label>
          <select id="staff-role" value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value })} className="mt-1 h-10 w-full rounded-md border border-input bg-background px-3 text-sm">
            <option value="branch_manager">{t("storeStaff.branchManager")}</option>
            <option value="staff">{t("storeStaff.staffRole")}</option>
          </select>
        </div>
        <div className="md:col-span-2"><PermissionMatrix idPrefix="new-staff" value={form.permissions} onChange={(permissions) => setForm({ ...form, permissions })} /></div>
        <div className="md:col-span-2"><Button type="submit" disabled={saving || branches.every((branch) => branch.active === false)}>{saving && <Loader2 className="h-4 w-4 animate-spin" />}{t("storeStaff.create")}</Button></div>
      </form>

      {temporaryPassword && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4" role="status">
          <p className="font-semibold">{t("storeStaff.temporaryPassword")}</p>
          <p className="mt-1 text-sm text-muted-foreground">{t("storeStaff.passwordInstruction")}</p>
          <code className="mt-2 block select-all rounded bg-background px-3 py-2 font-mono text-sm">{temporaryPassword}</code>
        </div>
      )}

      <section className="overflow-x-auto rounded-xl border border-border bg-card">
        <table className="w-full min-w-[600px] text-sm">
          <thead className="bg-secondary/60 text-left text-xs uppercase tracking-wider text-muted-foreground">
            <tr><th className="px-4 py-3">{t("staff.name")}</th><th className="px-4 py-3">{t("common.email")}</th><th className="px-4 py-3">{t("storeStaff.branch")}</th><th className="px-4 py-3">{t("common.role")}</th><th className="px-4 py-3">{t("common.status")}</th><th className="px-4 py-3 text-right">{t("common.actions")}</th></tr>
          </thead>
          <tbody>
            {staff.map((member) => (
              <Fragment key={member.id}>
              <tr className="border-t border-border">
                <td className="px-4 py-3 font-medium">{member.name}</td>
                <td className="px-4 py-3">{member.email}</td>
                <td className="px-4 py-3">{branches.find((branch) => branch.id === member.branch_id)?.name || "—"}</td>
                <td className="px-4 py-3">{t(member.role === "branch_manager" ? "storeStaff.branchManager" : "storeStaff.staffRole")}</td>
                <td className="px-4 py-3">{t(member.active ? "status.active" : "status.suspended")}</td>
                <td className="space-x-2 px-4 py-3 text-right">
                  <Button size="sm" variant="outline" onClick={() => editing === member.id ? setEditing(null) : startEdit(member)}>{t("perm.edit")}</Button>
                  <Button size="sm" variant="outline" onClick={() => setActive(member, !member.active)}>{t(member.active ? "storeStaff.deactivate" : "storeStaff.activate")}</Button>
                </td>
              </tr>
              {editing === member.id && (
                <tr className="border-t border-border bg-secondary/20">
                  <td colSpan={6} className="space-y-3 px-4 py-4">
                    <PermissionMatrix idPrefix={`edit-${member.id}`} value={editPermissions} onChange={setEditPermissions} />
                    <div className="flex gap-2">
                      <Button size="sm" disabled={savingPermissions} onClick={() => savePermissions(member)}>{savingPermissions && <Loader2 className="h-4 w-4 animate-spin" />}{t("perm.save")}</Button>
                      <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>{t("perm.cancel")}</Button>
                    </div>
                  </td>
                </tr>
              )}
              </Fragment>
            ))}
            {!loading && staff.length === 0 && <tr><td colSpan={6} className="px-4 py-10 text-center text-muted-foreground">{t("storeStaff.empty")}</td></tr>}
            {loading && <tr><td colSpan={6} className="px-4 py-10 text-center"><Loader2 className="mx-auto h-5 w-5 animate-spin" /></td></tr>}
          </tbody>
        </table>
      </section>
    </div>
  );
}
