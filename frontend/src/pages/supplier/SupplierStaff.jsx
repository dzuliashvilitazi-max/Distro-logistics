import { useCallback, useEffect, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { useI18n } from "@/context/I18nContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { KeyRound, Pencil, Plus, ShieldCheck, Users } from "lucide-react";
import { toast } from "sonner";

const PERMISSION_KEYS = ["orders", "inventory", "transfers", "deliveries"];
const EMPTY_PERMISSIONS = { orders: false, inventory: false, transfers: false, deliveries: false };
const EMPTY_STAFF = {
  name: "", email: "", phone: "", branch_id: "", active: true, permissions: EMPTY_PERMISSIONS,
};
const asList = (value, keys = []) => {
  if (Array.isArray(value)) return value;
  for (const key of keys) if (Array.isArray(value?.[key])) return value[key];
  return [];
};
const staffPermissions = (permissions) => {
  if (Array.isArray(permissions)) return Object.fromEntries(PERMISSION_KEYS.map((key) => [key, permissions.includes(key)]));
  return Object.fromEntries(PERMISSION_KEYS.map((key) => [key, Boolean(permissions?.[key])]));
};

export default function SupplierStaff() {
  const { t } = useI18n();
  const [staff, setStaff] = useState([]);
  const [branches, setBranches] = useState([]);
  const [form, setForm] = useState(EMPTY_STAFF);
  const [editingId, setEditingId] = useState("");
  const [credentialOutput, setCredentialOutput] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [staffResponse, branchResponse] = await Promise.all([
        api.get("/supplier/staff"),
        api.get("/supplier/warehouses"),
      ]);
      setStaff(asList(staffResponse.data, ["staff", "items"]));
      setBranches(asList(branchResponse.data, ["warehouses", "branches", "items"]));
      setError("");
    } catch (requestError) {
      setError(formatApiError(requestError.response?.data?.detail) || t("staff.loadError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { load(); }, [load]);

  const setField = (field, value) => setForm((current) => ({ ...current, [field]: value }));
  const resetForm = () => {
    setEditingId("");
    setForm(EMPTY_STAFF);
  };
  const editStaff = (member) => {
    setCredentialOutput(null);
    setEditingId(member.id);
    setForm({
      name: member.name || "",
      email: member.email || "",
      phone: member.phone || "",
      branch_id: member.branch_id || member.warehouse_id || "",
      active: member.active !== false,
      permissions: staffPermissions(member.permissions),
    });
  };
  const saveStaff = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    setCredentialOutput(null);
    const payload = { ...form, permissions: { ...form.permissions } };
    try {
      const { data } = editingId
        ? await api.put(`/supplier/staff/${encodeURIComponent(editingId)}`, payload)
        : await api.post("/supplier/staff", payload);
      const savedMember = data.staff || data.user || data;
      setStaff((current) => editingId
        ? current.map((member) => member.id === editingId ? { ...member, ...savedMember } : member)
        : [...current, savedMember]);
      if (!editingId) {
        const credentials = data.credentials || data.activation || {};
        const temporaryPassword = data.temporary_password || data.temp_password || credentials.temporary_password || credentials.password;
        const activationUrl = data.activation_url || data.activation_link || credentials.activation_url || credentials.url;
        const activationCode = data.activation_code || data.activation_token
          || credentials.activation_code || credentials.activation_token || credentials.code;
        if (temporaryPassword || activationUrl || activationCode) {
          setCredentialOutput({ temporaryPassword, activationUrl, activationCode });
        }
      }
      toast.success(t(editingId ? "staff.updated" : "staff.created"));
      resetForm();
      await load();
    } catch (requestError) {
      setError(formatApiError(requestError.response?.data?.detail) || t("staff.saveError"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6" data-testid="supplier-staff-page">
      <header>
        <div className="flex items-center gap-2">
          <Users className="h-6 w-6 text-primary" />
          <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{t("staff.title")}</h1>
        </div>
        <p className="mt-1 text-sm text-muted-foreground">{t("staff.subtitle")}</p>
      </header>

      {error && <div role="alert" className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-600">{error}</div>}
      {credentialOutput && (
        <section role="status" className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-5" data-testid="staff-activation-output">
          <div className="flex items-center gap-2 font-semibold text-emerald-700 dark:text-emerald-400">
            <KeyRound className="h-4 w-4" />{t("staff.credentialsTitle")}
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{t("staff.credentialsHint")}</p>
          <dl className="mt-3 space-y-2 text-sm">
            {credentialOutput.temporaryPassword && <Credential label={t("staff.temporaryPassword")} value={credentialOutput.temporaryPassword} />}
            {credentialOutput.activationCode && <Credential label={t("staff.activationCode")} value={credentialOutput.activationCode} />}
            {credentialOutput.activationUrl && (
              <div className="break-all">
                <dt className="text-xs text-muted-foreground">{t("staff.activationLink")}</dt>
                <dd><a className="font-medium text-primary underline" href={credentialOutput.activationUrl}>{credentialOutput.activationUrl}</a></dd>
              </div>
            )}
          </dl>
        </section>
      )}

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)]">
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">{t("staff.listTitle")}</h2>
            <span className="text-sm text-muted-foreground">{staff.length}</span>
          </div>
          {loading && staff.length === 0 ? (
            <div className="h-32 animate-pulse rounded-xl bg-secondary" />
          ) : staff.length === 0 ? (
            <div className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">{t("staff.empty")}</div>
          ) : (
            <div className="space-y-3">
              {staff.map((member) => {
                const branchName = member.branch_name || member.warehouse_name
                  || branches.find((branch) => branch.id === (member.branch_id || member.warehouse_id))?.name;
                const permissions = staffPermissions(member.permissions);
                return (
                  <article key={member.id} className="rounded-xl border border-border bg-card p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="font-semibold">{member.name || member.email}</h3>
                          <Badge variant={member.active === false ? "secondary" : "outline"}>
                            {t(member.active === false ? "staff.inactive" : "staff.active")}
                          </Badge>
                        </div>
                        <p className="mt-1 text-sm text-muted-foreground">{member.email}{member.phone ? ` · ${member.phone}` : ""}</p>
                        <p className="mt-1 text-xs text-muted-foreground">{t("staff.branch")}: {branchName || t("staff.unassigned")}</p>
                      </div>
                      <Button type="button" variant="ghost" size="sm" onClick={() => editStaff(member)}>
                        <Pencil className="mr-1 h-4 w-4" />{t("staff.edit")}
                      </Button>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {PERMISSION_KEYS.filter((key) => permissions[key]).map((key) => (
                        <Badge key={key} variant="secondary">{t(`staff.permission.${key}`)}</Badge>
                      ))}
                      {!PERMISSION_KEYS.some((key) => permissions[key]) && <span className="text-xs text-muted-foreground">{t("staff.noPermissions")}</span>}
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </section>

        <form onSubmit={saveStaff} className="space-y-4 rounded-xl border border-border bg-card p-5">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-primary" />
            <div>
              <h2 className="font-semibold">{t(editingId ? "staff.editTitle" : "staff.addTitle")}</h2>
              <p className="mt-1 text-xs text-muted-foreground">{t("staff.formHint")}</p>
            </div>
          </div>
          <label className="block space-y-1 text-xs text-muted-foreground">{t("staff.name")}
            <Input required maxLength={160} value={form.name} onChange={(event) => setField("name", event.target.value)} />
          </label>
          <label className="block space-y-1 text-xs text-muted-foreground">{t("staff.email")}
            <Input required type="email" maxLength={254} value={form.email} onChange={(event) => setField("email", event.target.value)} />
          </label>
          <label className="block space-y-1 text-xs text-muted-foreground">{t("staff.phone")}
            <Input type="tel" maxLength={40} value={form.phone} onChange={(event) => setField("phone", event.target.value)} />
          </label>
          <label className="block space-y-1 text-xs text-muted-foreground">{t("staff.branch")}
            <select value={form.branch_id} onChange={(event) => setField("branch_id", event.target.value)} className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground">
              <option value="">{t("staff.unassigned")}</option>
              {branches.map((branch) => <option key={branch.id} value={branch.id}>{branch.name}{branch.city ? ` · ${branch.city}` : ""}</option>)}
            </select>
          </label>
          <fieldset className="space-y-2">
            <legend className="mb-2 text-xs font-medium text-muted-foreground">{t("staff.permissions")}</legend>
            {PERMISSION_KEYS.map((key) => (
              <label key={key} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={Boolean(form.permissions[key])}
                  onChange={(event) => setForm((current) => ({
                    ...current,
                    permissions: { ...current.permissions, [key]: event.target.checked },
                  }))}
                  className="h-4 w-4 accent-primary"
                />
                {t(`staff.permission.${key}`)}
              </label>
            ))}
          </fieldset>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.active} onChange={(event) => setField("active", event.target.checked)} className="h-4 w-4 accent-primary" />
            {t("staff.active")}
          </label>
          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={saving}>{saving ? t("common.saving") : t("common.save")}</Button>
            {editingId && <Button type="button" variant="outline" onClick={resetForm}>{t("common.cancel")}</Button>}
            {!editingId && <Button type="button" variant="outline" onClick={() => setForm(EMPTY_STAFF)}>{t("staff.clear")}</Button>}
          </div>
        </form>
      </div>
    </div>
  );
}

function Credential({ label, value }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="break-all font-mono font-medium">{value}</dd>
    </div>
  );
}
