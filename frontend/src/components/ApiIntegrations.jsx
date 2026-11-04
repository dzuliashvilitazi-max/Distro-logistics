import { useEffect, useState } from "react";
import { API, api, formatApiError } from "@/lib/api";
import { useI18n } from "@/context/I18nContext";
import { Copy, KeyRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";

export function ApiIntegrations({ compact = false }) {
  const { t } = useI18n();
  const [info, setInfo] = useState(null);
  const [newKey, setNewKey] = useState("");
  const [busy, setBusy] = useState(false);
  const webhookUrl = `${API}/v1/sync/external-sale`;

  useEffect(() => {
    let active = true;
    const load = () => api.get("/supplier/integrations")
      .then(({ data }) => { if (active) setInfo(data); })
      .catch(() => { if (active) setInfo((current) => current || { has_key: false }); });
    load();
    const timer = setInterval(load, 15000);
    return () => { active = false; clearInterval(timer); };
  }, []);

  const copy = async (value) => {
    try {
      await navigator.clipboard.writeText(value);
      toast.success(t("int.copied"));
    } catch {
      toast.error(t("int.failed"));
    }
  };

  const generate = async () => {
    if (info?.has_key && !window.confirm(t("int.regenWarn"))) return;
    setBusy(true);
    try {
      const { data } = await api.post("/supplier/integrations/api-key");
      setNewKey(data.api_key);
      setInfo(data);
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || t("int.failed"));
    } finally {
      setBusy(false);
    }
  };

  const revoke = async () => {
    if (!window.confirm(t("int.revokeWarn"))) return;
    setBusy(true);
    try {
      await api.delete("/supplier/integrations/api-key");
      setNewKey("");
      setInfo({ has_key: false });
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || t("int.failed"));
    } finally {
      setBusy(false);
    }
  };

  const example = `curl -X POST ${webhookUrl} \\\n  -H "X-API-Key: ${newKey || "dk_..."}" -H "Content-Type: application/json" \\\n  -d '{"storeName":"Nikora","items":[{"productId":"SKU-1","quantity":5,"price":4.5}]}'`;

  const Wrapper = compact ? "div" : "section";
  const active = !!info?.has_key;

  return (
    <Wrapper className={compact ? "space-y-1" : "mt-6 rounded-xl border border-border bg-card p-6"} data-testid="api-integrations">
      {!compact && <h2 className="flex items-center gap-2 text-lg font-semibold"><KeyRound className="h-5 w-5" /> {t("int.title")}</h2>}
      <div className="mt-2 flex flex-wrap items-center gap-2" data-testid="auto-sync-status">
        <span className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold ${active ? "border-green-500/40 bg-green-500/10 text-green-600" : "border-border bg-secondary text-muted-foreground"}`}>
          <span className={`h-2 w-2 rounded-full ${active ? "bg-green-500" : "bg-muted-foreground"}`} />
          {active ? t("int.active") : t("int.inactive")}
        </span>
        {active && (
          <span className="text-xs text-muted-foreground">
            {info.last_used_at ? `${t("int.lastSync")}: ${new Date(info.last_used_at).toLocaleString()}` : t("int.neverSynced")}
          </span>
        )}
      </div>
      <p className="mt-2 text-sm text-muted-foreground">{t("int.desc")}</p>

      <p className="mt-4 text-sm font-medium">{t("int.webhook")}</p>
      <div className="mt-1 flex gap-2">
        <Input readOnly value={webhookUrl} className="font-mono text-xs" data-testid="webhook-url" />
        <Button type="button" variant="outline" onClick={() => copy(webhookUrl)} data-testid="copy-webhook-btn" className="shrink-0">
          <Copy className="mr-1.5 h-4 w-4" /> {t("int.copyWebhook")}
        </Button>
      </div>

      <p className="mt-4 text-sm font-medium">{t("int.apiKey")}</p>
      {newKey ? (
        <>
          <div className="mt-1 flex gap-2">
            <Input readOnly value={newKey} className="font-mono text-xs" data-testid="api-key-value" />
            <Button type="button" variant="outline" onClick={() => copy(newKey)} aria-label={t("int.copy")}><Copy className="h-4 w-4" /></Button>
          </div>
          <p className="mt-1 text-xs font-medium text-processing">{t("int.showOnce")}</p>
        </>
      ) : (
        <p className="mt-1 font-mono text-sm text-muted-foreground" data-testid="api-key-masked">
          {info?.has_key ? `${info.key_prefix}${"•".repeat(24)}` : t("int.noKey")}
        </p>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        <Button type="button" onClick={generate} disabled={busy || !info} data-testid="generate-api-key-btn">
          {info?.has_key ? t("int.regenerate") : t("int.generate")}
        </Button>
        {info?.has_key && <Button type="button" variant="outline" onClick={revoke} disabled={busy}>{t("int.revoke")}</Button>}
      </div>

      <p className="mt-4 text-xs text-muted-foreground">{t("int.header")}</p>
      <p className="mt-2 text-xs font-medium">{t("int.example")}</p>
      <pre className="mt-1 overflow-x-auto rounded-md bg-secondary p-3 text-xs">{example}</pre>
    </Wrapper>
  );
}
