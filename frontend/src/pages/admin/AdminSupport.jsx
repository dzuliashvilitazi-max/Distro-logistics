import { useCallback, useEffect, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { LifeBuoy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";

const TYPE_KA = { store: "მაღაზია", distributor: "დისტრიბუტორი" };

export default function AdminSupport() {
  const [tickets, setTickets] = useState([]);
  const [filter, setFilter] = useState("");
  const [drafts, setDrafts] = useState({});

  const load = useCallback(() => {
    api.get("/admin/support/tickets", { params: filter ? { user_type: filter } : {} })
      .then((r) => setTickets(r.data)).catch((e) => toast.error(formatApiError(e.response?.data?.detail)));
  }, [filter]);
  useEffect(() => { load(); }, [load]);

  const reply = async (id) => {
    const text = (drafts[id] || "").trim();
    if (!text) return;
    try {
      await api.post(`/admin/support/tickets/${id}/reply`, { reply: text });
      setDrafts((d) => ({ ...d, [id]: "" }));
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const close = async (id) => {
    try { await api.post(`/admin/support/tickets/${id}/close`); load(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  return (
    <div data-testid="admin-support">
      <h1 className="mb-4 flex items-center gap-2 text-2xl font-bold tracking-tight"><LifeBuoy className="h-6 w-6" /> მხარდაჭერა</h1>
      <div className="mb-4 flex gap-2">
        {[["", "ყველა"], ["store", "მაღაზიები"], ["distributor", "დისტრიბუტორები"]].map(([v, l]) => (
          <Button key={v} size="sm" variant={filter === v ? "default" : "outline"} onClick={() => setFilter(v)}>{l}</Button>
        ))}
      </div>
      <div className="space-y-3">
        {tickets.length === 0 && <p className="text-sm text-muted-foreground">მიმართვები არ არის.</p>}
        {tickets.map((t) => (
          <div key={t.id} className="rounded-lg border border-border bg-card p-4 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded bg-primary/10 px-2 py-0.5 text-xs font-semibold text-primary" data-testid="ticket-user-type">{TYPE_KA[t.user_type] || t.user_type}</span>
              <span className="font-semibold">{t.user_name}</span>
              <span className="text-xs text-muted-foreground">{t.user_email} · {new Date(t.created_at).toLocaleString()} · {t.status}</span>
            </div>
            <p className="mt-2">{t.message}</p>
            {t.replies?.map((r, i) => <p key={i} className="mt-2 rounded bg-secondary px-2 py-1"><b>{r.by}:</b> {r.text}</p>)}
            {t.status !== "closed" && (
              <div className="mt-3 flex gap-2">
                <Textarea rows={2} value={drafts[t.id] || ""} onChange={(e) => setDrafts({ ...drafts, [t.id]: e.target.value })} placeholder="პასუხი" />
                <div className="flex flex-col gap-2">
                  <Button size="sm" onClick={() => reply(t.id)}>პასუხი</Button>
                  <Button size="sm" variant="outline" onClick={() => close(t.id)}>დახურვა</Button>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
