import { useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { useI18n } from "@/context/I18nContext";
import { Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { StatusBadge } from "@/components/StatusBadge";
import { CardForm } from "@/components/CardForm";
import { GEORGIAN_BANKS, normalizeIban, isValidGeIban } from "@/lib/banks";
import { LogoUpload } from "@/components/BusinessLogo";
import { ApiIntegrations } from "@/components/ApiIntegrations";
import { BusinessSectorCheckboxes } from "@/components/BusinessSectorCheckboxes";
import { normalizeEntityType } from "@/lib/businessEntity";
import { CityMultiSelect } from "@/components/CityMultiSelect";
import { canonCity } from "@/lib/cities";
import { useStoreBranch } from "@/context/StoreBranchContext";
import { toast } from "sonner";

export default function Profile() {
  const { user, refreshUser, setUser } = useAuth();
  const { refreshBranches } = useStoreBranch();
  const { t } = useI18n();
  const [form, setForm] = useState({ name: user.name || "", business_name: user.business_name || "", address: user.address || "", phone: user.phone || "", accountant_email: user.accountant_email || "", city: canonCity(user.city), cities: user.cities?.length ? user.cities.map(canonCity) : (user.city ? [canonCity(user.city)] : []), category_ids: user.category_ids || [], business_sectors: user.servedSectors || user.served_sectors || user.business_sectors || [], identification_number: user.identification_number || "", establishment_type: user.entityType || user.entity_type || user.businessType || user.business_type || user.establishment_type || "grocery", establishment_type_other: user.establishment_type_other || "", card_name: user.card_name || "", card_number: "", card_expiry: user.card_expiry || "", bank_name: user.bank_name || "", iban: user.iban || "", vat_registered: Boolean(user.vat_registered) });
  const [saving, setSaving] = useState(false);
  const [extraBanks, setExtraBanks] = useState(() => (user.bank_accounts || []).filter((a) => a.iban && a.iban !== user.iban).map((a) => ({ bank_name: a.bank_name || "", iban: a.iban })));
  const currentEntityType = user.entityType || user.entity_type || user.businessType || user.business_type || user.establishment_type || "grocery";
  const entityTypeLabel = form.establishment_type === "other"
    ? (form.establishment_type_other || user.entityTypeLabel || t("est.other"))
    : ((form.establishment_type === currentEntityType || normalizeEntityType(form.establishment_type) === normalizeEntityType(currentEntityType)) && user.entityTypeLabel
      ? user.entityTypeLabel
      : t(`est.${normalizeEntityType(form.establishment_type)}`));

  const save = async (e) => {
    e.preventDefault();
    if (user.role === "supplier" && !isValidGeIban(form.iban)) { toast.error("IBAN: GE + 20 სიმბოლო (მაგ. GE29TB1234567890123456)"); return; }
    if (user.role === "supplier" && !isValidGeIban(form.iban)) { toast.error("IBAN: GE + 20 სიმბოლო (მაგ. GE29TB1234567890123456)"); return; }
    if (user.role === "supplier" && extraBanks.some((a) => a.iban && !isValidGeIban(a.iban))) { toast.error("IBAN: GE + 20 სიმბოლო (მაგ. GE29TB1234567890123456)"); return; }
    setSaving(true);
    const payload = { ...form };
    if (user.role === "supplier") payload.bank_accounts = [{ bank_name: form.bank_name, iban: form.iban }, ...extraBanks].filter((a) => a.iban);
    if (user.role !== "retailer") { delete payload.card_name; delete payload.card_number; delete payload.card_expiry; }
    if (user.role !== "supplier") { delete payload.cities; delete payload.category_ids; delete payload.business_sectors; }
    else delete payload.category_ids;
    delete payload.establishment_type; delete payload.establishment_type_other;
    try {
      const { data } = await api.put("/profile", payload);
      setUser((current) => ({ ...current, ...data }));
      await refreshUser();
      if (user.role === "retailer") await refreshBranches();
      toast.success(t("prof.updated"));
    }
    catch (err) { toast.error(formatApiError(err.response?.data?.detail)); }
    finally { setSaving(false); }
  };

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-6 text-2xl font-bold tracking-tight sm:text-3xl">{t("prof.title")}</h1>
      <div className="rounded-xl border border-border bg-card p-6">
        <div className="mb-6 flex items-center gap-4">
          <LogoUpload />
          <div>
            <div className="flex items-center gap-2"><h2 className="text-lg font-semibold">{user.business_name}</h2><StatusBadge status={user.status || "active"} /></div>
            <p className="mt-1 text-sm text-muted-foreground">{user.role === "retailer" ? entityTypeLabel : t(`roles.${user.role}`)}</p>
            <p className="font-mono text-xs text-muted-foreground">{user.email}</p>
          </div>
        </div>

        <form onSubmit={save} className="space-y-4">
          <div><Label htmlFor="bn">{t("prof.businessName")}</Label><Input id="bn" value={form.business_name} onChange={(e) => setForm({ ...form, business_name: e.target.value })} className="mt-1.5" data-testid="profile-business" /></div>
          <div><Label htmlFor="cn">{t("prof.contactName")}</Label><Input id="cn" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="mt-1.5" data-testid="profile-name" /></div>
          {user.role === "retailer" && (
            <div>
              <Label htmlFor="establishment-type">{t("reg.establishmentType")}</Label>
              <Input id="establishment-type" value={entityTypeLabel} disabled readOnly className="mt-1.5" data-testid="profile-establishment-type" />
            </div>
          )}
          <div><Label htmlFor="acc-email">ბუღალტრის ელ.ფოსტა</Label><Input id="acc-email" type="email" value={form.accountant_email} onChange={(e) => setForm({ ...form, accountant_email: e.target.value })} className="mt-1.5" placeholder={user.email} data-testid="profile-accountant-email" /></div>
          <div><Label htmlFor="ph">{t("prof.phone")}</Label><Input id="ph" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} className="mt-1.5" data-testid="profile-phone" /></div>
          <div className="grid grid-cols-2 gap-3">
            <div><Label>{t("prof.city")}</Label>
              <div className="mt-1.5"><CityMultiSelect single value={form.city ? [canonCity(form.city)] : []} onChange={([city]) => setForm({ ...form, city: city || "" })} idPrefix="profile-city" placeholder="—" /></div></div>
            <div><Label htmlFor="idn">{t("prof.identification")}</Label><Input id="idn" value={form.identification_number} onChange={(e) => setForm({ ...form, identification_number: e.target.value })} className="mt-1.5" data-testid="profile-identification" /></div>
          </div>
          <div className="rounded-lg border border-border p-3">
            <div className="flex items-start gap-2">
              <Checkbox id="vat-registered" checked={form.vat_registered} onCheckedChange={(checked) => setForm({ ...form, vat_registered: checked === true })} data-testid="profile-vat-registered" />
              <div>
                <Label htmlFor="vat-registered">{t("prof.vatRegistered")}</Label>
                <p className="mt-1 text-xs text-muted-foreground">{t("prof.vatRegisteredNote")}</p>
              </div>
            </div>
          </div>
          {user.role === "retailer" && (
            <CardForm />
          )}
          {user.role === "supplier" && (
            <>
              <BusinessSectorCheckboxes value={form.business_sectors} onChange={(sectors) => setForm({ ...form, business_sectors: sectors })} idPrefix="profile-sector" />
              <div className="space-y-2">
                <Label>{t("prof.serviceCities")}</Label>
                <CityMultiSelect value={form.cities} onChange={(cities) => setForm({ ...form, cities })} idPrefix="profile-cities" />
              </div>
              <div className="rounded-lg border border-border p-3">
                <p className="mb-2 text-sm font-semibold">{t("prof.banking")}</p>
                <div className="space-y-2">
                  <select value={form.bank_name} onChange={(e) => setForm({ ...form, bank_name: e.target.value })} className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm" data-testid="profile-bank-name">
                    <option value="">{t("reg.bankName")}</option>
                    {form.bank_name && !GEORGIAN_BANKS.includes(form.bank_name) && <option value={form.bank_name}>{form.bank_name}</option>}
                    {GEORGIAN_BANKS.map((b) => <option key={b} value={b}>{b}</option>)}
                  </select>
                  <Input value={form.iban} onChange={(e) => setForm({ ...form, iban: normalizeIban(e.target.value) })} placeholder={t("reg.iban")} maxLength={22} data-testid="profile-iban" />
                  {extraBanks.map((acc, i) => (
                    <div key={i} className="flex gap-2" data-testid={`profile-extra-bank-${i}`}>
                      <select value={acc.bank_name} onChange={(e) => setExtraBanks(extraBanks.map((a, j) => j === i ? { ...a, bank_name: e.target.value } : a))} className="h-10 w-1/2 rounded-md border border-input bg-background px-2 text-sm">
                        <option value="">{t("reg.bankName")}</option>
                        {GEORGIAN_BANKS.map((b) => <option key={b} value={b}>{b}</option>)}
                      </select>
                      <Input value={acc.iban} onChange={(e) => setExtraBanks(extraBanks.map((a, j) => j === i ? { ...a, iban: normalizeIban(e.target.value) } : a))} placeholder={t("reg.iban")} maxLength={22} />
                      <Button type="button" variant="outline" onClick={() => setExtraBanks(extraBanks.filter((_, j) => j !== i))}>×</Button>
                    </div>
                  ))}
                  {extraBanks.length < 4 && <Button type="button" variant="outline" size="sm" onClick={() => setExtraBanks([...extraBanks, { bank_name: "", iban: "" }])} data-testid="profile-add-bank">+ {t("reg.bankName")}</Button>}
                </div>
              </div>
            </>
          )}
          <div><Label htmlFor="ad">{user.role === "supplier" ? t("prof.warehouseAddress") : t("prof.deliveryAddress")}</Label><Textarea id="ad" value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} className="mt-1.5" rows={2} data-testid="profile-address" /></div>
          <Button type="submit" disabled={saving} data-testid="save-profile-btn"><Save className="mr-1.5 h-4 w-4" /> {saving ? t("common.saving") : t("prof.saveChanges")}</Button>
        </form>
      </div>
      {user.role === "supplier" && (user.supplier_access_role || "global_admin") === "global_admin" && <ApiIntegrations />}
    </div>
  );
}
