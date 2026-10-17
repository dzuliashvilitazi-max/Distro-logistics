import { useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { useI18n } from "@/context/I18nContext";
import { CreditCard, Loader2, Trash2, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";

export function CardForm({ note }) {
  const { user, refreshUser } = useAuth();
  const { t } = useI18n();
  const [form, setForm] = useState({ number: "", exp: "", cvc: "", name: user.card_name || "" });
  const [busy, setBusy] = useState(false);
  const hasCard = user.card_verified;

  const save = async () => {
    setBusy(true);
    try {
      await api.post("/payments/cards", form);
      await refreshUser();
      setForm({ number: "", exp: "", cvc: "", name: form.name });
      toast.success(t("card.saved"));
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  const remove = async () => {
    setBusy(true);
    try { await api.delete("/payments/cards"); await refreshUser(); toast.success(t("card.removed")); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  return (
    <div className="rounded-lg border border-border p-4" data-testid="card-form">
      <p className="flex items-center gap-2 text-sm font-semibold"><CreditCard className="h-4 w-4 text-primary" /> {t("card.title")}</p>
      {hasCard ? (
        <div className="mt-3 flex items-center justify-between rounded-lg bg-secondary/60 px-3 py-2.5">
          <span className="flex items-center gap-2 text-sm font-medium" data-testid="card-on-file">
            <ShieldCheck className="h-4 w-4 text-emerald-500" />
            {(user.card_brand || "card").toUpperCase()} ••••{user.card_last4} · {user.card_expiry}
          </span>
          <Button variant="ghost" size="sm" className="text-rose-500" onClick={remove} disabled={busy} data-testid="remove-card-btn"><Trash2 className="h-4 w-4" /></Button>
        </div>
      ) : (
        <div className="mt-3 space-y-2">
          <Input value={form.number} onChange={(e) => setForm({ ...form, number: e.target.value })} placeholder={t("card.number")} data-testid="card-number-input" inputMode="numeric" />
          <div className="grid grid-cols-2 gap-2">
            <Input value={form.exp} onChange={(e) => setForm({ ...form, exp: e.target.value })} placeholder="MM/YY" data-testid="card-exp-input" />
            <Input value={form.cvc} onChange={(e) => setForm({ ...form, cvc: e.target.value })} placeholder={t("card.cvc")} data-testid="card-cvc-input" />
          </div>
          <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder={t("card.nameOnCard")} data-testid="card-name-input" />
          <Button onClick={save} disabled={busy} className="w-full" data-testid="save-card-btn">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : t("card.save")}
          </Button>
        </div>
      )}
      <p className="mt-2 text-xs text-muted-foreground">{t("card.sandboxNote")}{note ? ` ${note}` : ""}</p>
    </div>
  );
}
