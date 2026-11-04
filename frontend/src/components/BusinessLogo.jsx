import { useRef, useState } from "react";
import { Upload, Trash2, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { api, API, logoSrc, requestErrorMessage } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { useI18n } from "@/context/I18nContext";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// Logo image, or the business initial when no logo is uploaded or it fails to load.
// Pass `entity` (user/distributor with logo_url) or an explicit `logo` path plus `name`.
export function LogoAvatar({ entity, logo, name, className }) {
  const path = logo ?? entity?.logo_url ?? entity?.logo ?? entity?.supplier_logo;
  const src = path ? `${API}${path}` : null;
  const [failedSrc, setFailedSrc] = useState(null);
  const initial = (name || entity?.business_name || entity?.name || entity?.supplier_name || "?")[0]?.toUpperCase();
  return src && failedSrc !== src ? (
    <img src={src} alt="" onError={() => setFailedSrc(src)} className={cn("rounded-xl bg-white object-contain", className)} />
  ) : (
    <div className={cn("flex items-center justify-center rounded-xl bg-primary/15 font-extrabold text-primary", className)}>{initial}</div>
  );
}

const MAX_BYTES = 2 * 1024 * 1024;

export function LogoUpload() {
  const { user, setUser } = useAuth();
  const { t } = useI18n();
  const inputRef = useRef(null);
  const [busy, setBusy] = useState(false);

  const onPick = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (!file.type.startsWith("image/")) { toast.error(t("logo.invalidType")); return; }
    if (file.size > MAX_BYTES) { toast.error(t("logo.tooLarge")); return; }
    const body = new FormData();
    body.append("file", file);
    setBusy(true);
    try {
      const { data } = await api.post("/profile/logo", body);
      setUser((u) => ({ ...u, ...data }));
      toast.success(t("logo.updated"));
    } catch (err) {
      toast.error(requestErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const onRemove = async () => {
    setBusy(true);
    try {
      const { data } = await api.delete("/profile/logo");
      setUser((u) => {
        const next = { ...u, ...data };
        if (!data.logo_url) delete next.logo_url;
        return next;
      });
      toast.success(t("logo.removed"));
    } catch (err) {
      toast.error(requestErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex items-center gap-4" data-testid="logo-upload">
      <LogoAvatar entity={user} className="h-16 w-16 shrink-0 text-2xl" />
      <div className="flex flex-wrap items-center gap-2">
        <input ref={inputRef} type="file" accept="image/png,image/jpeg,image/webp,image/gif" className="hidden" onChange={onPick} data-testid="logo-input" />
        <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => inputRef.current?.click()}>
          {busy ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Upload className="mr-1.5 h-4 w-4" />}
          {user?.logo_url ? t("logo.change") : t("logo.upload")}
        </Button>
        {user?.logo_url && (
          <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={onRemove}>
            <Trash2 className="mr-1.5 h-4 w-4" />{t("logo.remove")}
          </Button>
        )}
        <p className="w-full text-xs text-muted-foreground">{t("logo.hint")}</p>
      </div>
    </div>
  );
}
