import { useCallback, useEffect, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { useI18n } from "@/context/I18nContext";
import { CreditCard, Loader2, Trash2, ShieldCheck, Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";

const EMPTY = { number: "", exp: "", cvc: "" };

export function CardForm({ note }) {
  const { user, refreshUser } = useAuth();
  const { t } = useI18n();
  const [cards, setCards] = useState([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ ...EMPTY, name: user.card_name || "" });
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/payments/cards");
      setCards(data.cards || []);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setBusy(true);
    try {
      const { data } = await api.post("/payments/cards", form);
      setCards(data.cards || []);
      await refreshUser();
      setForm({ ...EMPTY, name: form.name });
      setAdding(false);
      toast.success(t("card.saved"));
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  const remove = async (id) => {
    setBusy(true);
    try {
      const { data } = await api.delete(`/payments/cards/${id}`);
      setCards(data.cards || []);
      await refreshUser();
      toast.success(t("card.removed"));
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  return (
    <div className="rounded-lg border border-border p-4" data-testid="card-form">
      <p className="flex items-center gap-2 text-sm font-semibold"><CreditCard className="h-4 w-4 text-primary" /> {t("card.title")}</p>

      <div className="mt-3 space-y-2" data-testid="saved-cards-list">
        {loading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
        {!loading && cards.length === 0 && <p className="text-sm text-muted-foreground">ბარათი ჯერ არ არის მიბმული.</p>}
        {cards.map((c) => (
          <div key={c.id} className="flex items-center justify-between rounded-lg bg-secondary/60 px-3 py-2.5" data-testid={`saved-card-${c.id}`}>
            <span className="flex items-center gap-2 text-sm font-medium" data-testid="card-on-file">
              <ShieldCheck className="h-4 w-4 text-delivered" />
              <span className="rounded bg-background px-1.5 py-0.5 text-xs font-bold tracking-wide">{(c.brand || "card").toUpperCase()}</span>
              ••••{c.last4}{c.exp ? ` · ${c.exp}` : ""}
            </span>
            <Button variant="ghost" size="sm" className="text-rose-500" onClick={() => remove(c.id)} disabled={busy} data-testid={`remove-card-${c.id}`}>
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        ))}
      </div>

      {adding ? (
        <div className="mt-3 space-y-2">
          <Input value={form.number} onChange={(e) => setForm({ ...form, number: e.target.value })} placeholder={t("card.number")} data-testid="card-number-input" inputMode="numeric" />
          <div className="grid grid-cols-2 gap-2">
            <Input value={form.exp} onChange={(e) => setForm({ ...form, exp: e.target.value })} placeholder="MM/YY" data-testid="card-exp-input" />
            <Input value={form.cvc} onChange={(e) => setForm({ ...form, cvc: e.target.value })} placeholder={t("card.cvc")} data-testid="card-cvc-input" />
          </div>
          <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder={t("card.nameOnCard")} data-testid="card-name-input" />
          <div className="flex gap-2">
            <Button onClick={save} disabled={busy} className="flex-1" data-testid="save-card-btn">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : t("card.save")}
            </Button>
            <Button variant="outline" onClick={() => { setAdding(false); setForm({ ...EMPTY, name: form.name }); }} disabled={busy}><X className="h-4 w-4" /></Button>
          </div>
        </div>
      ) : (
        <Button variant="outline" className="mt-3 w-full" onClick={() => setAdding(true)} data-testid="add-card-btn">
          <Plus className="mr-1 h-4 w-4" /> ახალი ბარათის დამატება
        </Button>
      )}
      <p className="mt-2 text-xs text-muted-foreground">{t("card.sandboxNote")}{note ? ` ${note}` : ""}</p>
    </div>
  );
}
