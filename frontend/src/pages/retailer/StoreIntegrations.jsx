import { useEffect, useState } from "react";
import { API, api, formatApiError } from "@/lib/api";
import { useI18n } from "@/context/I18nContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Cable, Check, Copy, KeyRound, Loader2, Plus, RotateCw, Trash2 } from "lucide-react";
import { toast } from "sonner";

const SOFTWARES = ["1C", "Apex", "Fina", "Custom POS / ERP"];

export default function StoreIntegrations() {
  const { t } = useI18n();
  const [integrations, setIntegrations] = useState(null);
  const [software, setSoftware] = useState(SOFTWARES[0]);
  const [locationName, setLocationName] = useState("");
  const [creating, setCreating] = useState(false);
  const [busyId, setBusyId] = useState("");
  const [freshToken, setFreshToken] = useState("");

  const load = async () => {
    try {
      const { data } = await api.get("/store/integrations");
      setIntegrations(data);
    } catch (error) {
      toast.error(formatApiError(error.response?.data?.detail));
      setIntegrations([]);
    }
  };
  useEffect(() => { load(); }, []);

  const create = async (event) => {
    event.preventDefault();
    setCreating(true);
    try {
      const { data } = await api.post("/store/integrations", { software, location_name: locationName });
      setFreshToken(data.token);
      setLocationName("");
      toast.success(t("integration.created"));
      await load();
    } catch (error) {
      toast.error(formatApiError(error.response?.data?.detail));
    } finally {
      setCreating(false);
    }
  };

  const rotate = async (integration) => {
    setBusyId(integration.id);
    try {
      const { data } = await api.post(`/store/integrations/${encodeURIComponent(integration.id)}/rotate`);
      setFreshToken(data.token);
      toast.success(t("integration.rotated"));
      await load();
    } catch (error) {
      toast.error(formatApiError(error.response?.data?.detail));
    } finally {
      setBusyId("");
    }
  };

  const disable = async (integration) => {
    setBusyId(integration.id);
    try {
      await api.delete(`/store/integrations/${encodeURIComponent(integration.id)}`);
      toast.success(t("integration.disabled"));
      await load();
    } catch (error) {
      toast.error(formatApiError(error.response?.data?.detail));
    } finally {
      setBusyId("");
    }
  };

  const copy = async (value) => {
    try {
      await navigator.clipboard.writeText(value);
      toast.success(t("integration.copied"));
    } catch {
      toast.error(t("integration.copyFailed"));
    }
  };

  if (!integrations) return <div className="h-72 animate-pulse rounded-xl bg-secondary" />;

  return (
    <div className="mx-auto max-w-5xl space-y-6" data-testid="store-integrations-page">
      <header>
        <div className="flex items-center gap-2"><Cable className="h-6 w-6 text-primary" /><h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{t("integration.title")}</h1></div>
        <p className="mt-1 text-sm text-muted-foreground">{t("integration.subtitle")}</p>
      </header>

      <form onSubmit={create} className="grid gap-3 rounded-xl border border-border bg-card p-5 md:grid-cols-[1fr_1fr_auto] md:items-end">
        <label className="space-y-1 text-sm">
          <span>{t("integration.software")}</span>
          <select className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground" value={software} onChange={(event) => setSoftware(event.target.value)}>
            {SOFTWARES.map((name) => <option key={name}>{name}</option>)}
          </select>
        </label>
        <label className="space-y-1 text-sm">
          <span>{t("integration.location")}</span>
          <Input maxLength={120} value={locationName} onChange={(event) => setLocationName(event.target.value)} placeholder={t("integration.locationPlaceholder")} />
        </label>
        <Button type="submit" disabled={creating}>
          {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="mr-1.5 h-4 w-4" />}{t("integration.connect")}
        </Button>
      </form>

      {freshToken && (
        <section className="space-y-3 rounded-xl border border-amber-500/40 bg-amber-500/5 p-5" role="alert">
          <div className="flex items-center gap-2 font-semibold text-amber-500"><KeyRound className="h-4 w-4" />{t("integration.tokenTitle")}</div>
          <p className="text-sm text-muted-foreground">{t("integration.tokenDescription")}</p>
          <div className="flex flex-wrap gap-2">
            <code className="min-w-0 flex-1 break-all rounded-md border border-border bg-background p-3 font-mono text-xs">{freshToken}</code>
            <Button variant="outline" onClick={() => copy(freshToken)}><Copy className="mr-1.5 h-4 w-4" />{t("integration.copyToken")}</Button>
            <Button variant="ghost" onClick={() => setFreshToken("")}>{t("common.cancel")}</Button>
          </div>
        </section>
      )}

      <div className="space-y-3">
        {integrations.map((integration) => (
          <article key={integration.id} className="rounded-xl border border-border bg-card p-5" data-testid={`store-integration-${integration.id}`}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="font-semibold">{integration.software}{integration.location_name ? ` · ${integration.location_name}` : ""}</h2>
                <p className="mt-1 text-xs text-muted-foreground">{t("integration.tokenPrefix")}: <code>{integration.token_prefix}…</code> · {integration.active ? t("integration.active") : t("integration.disabled")}</p>
                <p className="mt-1 text-xs text-muted-foreground">{t("integration.lastSync")}: {integration.last_sync_at ? new Date(integration.last_sync_at).toLocaleString() : t("integration.never")}</p>
              </div>
              <div className="flex gap-2">
                <Button size="sm" variant="outline" disabled={busyId === integration.id} onClick={() => rotate(integration)}>
                  {busyId === integration.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCw className="mr-1.5 h-4 w-4" />}{t("integration.rotate")}
                </Button>
                {integration.active && <Button size="sm" variant="outline" className="text-rose-500" disabled={busyId === integration.id} onClick={() => disable(integration)}><Trash2 className="mr-1.5 h-4 w-4" />{t("integration.revoke")}</Button>}
              </div>
            </div>
          </article>
        ))}
        {integrations.length === 0 && <p className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">{t("integration.empty")}</p>}
      </div>

      <section className="space-y-3 rounded-xl border border-border bg-card p-5">
        <h2 className="font-semibold">{t("integration.apiTitle")}</h2>
        <p className="text-sm text-muted-foreground">{t("integration.apiDescription")}</p>
        <div className="rounded-lg border border-border bg-background p-4">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">{t("integration.pullOrders")}</p>
          <code className="block break-all font-mono text-xs">GET {API}/store/integrations/orders?branch_id=BRANCH_ID&amp;updated_since=ISO8601</code>
          <pre className="mt-2 overflow-x-auto text-xs text-muted-foreground">Authorization: Bearer YOUR_TOKEN</pre>
        </div>
        <div className="rounded-lg border border-border bg-background p-4">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">{t("integration.pushSales")}</p>
          <code className="block break-all font-mono text-xs">POST {API}/store/integrations/sales</code>
          <pre className="mt-2 overflow-x-auto text-xs text-muted-foreground">{`Authorization: Bearer YOUR_TOKEN
Content-Type: application/json

[{"sale_id":"POS-1001","branch_id":"BRANCH_ID","sold_at":"2026-10-21T09:30:00+04:00","items":[{"product_id":"PRODUCT_ID","quantity":2,"retail_price":12.5}]}]`}</pre>
        </div>
        <p className="text-xs text-muted-foreground"><Check className="mr-1 inline h-3.5 w-3.5 text-emerald-500" />{t("integration.securityNote")}</p>
      </section>
    </div>
  );
}
