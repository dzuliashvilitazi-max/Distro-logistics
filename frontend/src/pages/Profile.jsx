import { useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { useI18n } from "@/context/I18nContext";
import { Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { StatusBadge } from "@/components/StatusBadge";
import { CardForm } from "@/components/CardForm";
import { toast } from "sonner";

export default function Profile() {
  const { user, refreshUser } = useAuth();
  const { t } = useI18n();
  const [form, setForm] = useState({ name: user.name || "", business_name: user.business_name || "", address: user.address || "", phone: user.phone || "", city: user.city || "", category: user.category || "", identification_number: user.identification_number || "", card_name: user.card_name || "", card_number: "", card_expiry: user.card_expiry || "", bank_name: user.bank_name || "", iban: user.iban || "" });
  const [saving, setSaving] = useState(false);

  const save = async (e) => {
    e.preventDefault();
    setSaving(true);
    try { await api.put("/profile", form); await refreshUser(); toast.success(t("prof.updated")); }
    catch (err) { toast.error(formatApiError(err.response?.data?.detail)); }
    finally { setSaving(false); }
  };

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-6 text-2xl font-bold tracking-tight sm:text-3xl">{t("prof.title")}</h1>
      <div className="rounded-xl border border-border bg-card p-6">
        <div className="mb-6 flex items-center gap-4">
          <div className="flex h-16 w-16 items-center justify-center rounded-xl bg-primary/15 text-2xl font-extrabold text-primary">{user.business_name?.[0]?.toUpperCase()}</div>
          <div>
            <div className="flex items-center gap-2"><h2 className="text-lg font-semibold">{user.business_name}</h2><StatusBadge status={user.status || "active"} /></div>
            <p className="font-mono text-xs text-muted-foreground">{t(`roles.${user.role}`)} · {user.email}</p>
          </div>
        </div>

        <form onSubmit={save} className="space-y-4">
          <div><Label htmlFor="bn">{t("prof.businessName")}</Label><Input id="bn" value={form.business_name} onChange={(e) => setForm({ ...form, business_name: e.target.value })} className="mt-1.5" data-testid="profile-business" /></div>
          <div><Label htmlFor="cn">{t("prof.contactName")}</Label><Input id="cn" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="mt-1.5" data-testid="profile-name" /></div>
          <div><Label htmlFor="ph">{t("prof.phone")}</Label><Input id="ph" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} className="mt-1.5" data-testid="profile-phone" /></div>
          <div className="grid grid-cols-2 gap-3">
            <div><Label htmlFor="city">{t("prof.city")}</Label><Input id="city" value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} className="mt-1.5" data-testid="profile-city" /></div>
            <div><Label htmlFor="idn">{t("prof.identification")}</Label><Input id="idn" value={form.identification_number} onChange={(e) => setForm({ ...form, identification_number: e.target.value })} className="mt-1.5" data-testid="profile-identification" /></div>
          </div>
          {user.role === "retailer" && (
            <CardForm />
          )}
          {user.role === "supplier" && (
            <>
              <CardForm note={t("card.autoDebitNote")} />
              <div><Label htmlFor="cat">{t("auth.category")}</Label><Input id="cat" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} className="mt-1.5" data-testid="profile-category" /></div>
              <div className="rounded-lg border border-border p-3">
                <p className="mb-2 text-sm font-semibold">{t("prof.banking")}</p>
                <div className="space-y-2">
                  <Input value={form.bank_name} onChange={(e) => setForm({ ...form, bank_name: e.target.value })} placeholder={t("reg.bankName")} data-testid="profile-bank-name" />
                  <Input value={form.iban} onChange={(e) => setForm({ ...form, iban: e.target.value })} placeholder={t("reg.iban")} data-testid="profile-iban" />
                </div>
              </div>
            </>
          )}
          <div><Label htmlFor="ad">{user.role === "supplier" ? t("prof.warehouseAddress") : t("prof.storeAddress")}</Label><Textarea id="ad" value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} className="mt-1.5" rows={2} data-testid="profile-address" /></div>
          <Button type="submit" disabled={saving} data-testid="save-profile-btn"><Save className="mr-1.5 h-4 w-4" /> {saving ? t("common.saving") : t("prof.saveChanges")}</Button>
        </form>
      </div>
    </div>
  );
}
