import { useCallback, useEffect, useState } from "react";
import { AlertCircle, Check, Clock3, Loader2, Megaphone, RefreshCw, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { api, formatApiError } from "@/lib/api";
import { toast } from "sonner";

const AUDIENCES = [
  { value: "all", label: "ყველა მომხმარებელი" },
  { value: "stores", label: "მხოლოდ მაღაზიები" },
  { value: "distributors", label: "მხოლოდ დისტრიბუტორები" },
];

const STATUS = {
  queued: { label: "რიგშია", className: "text-amber-700 bg-amber-500/10", icon: Clock3 },
  sending: { label: "იგზავნება", className: "text-sky-700 bg-sky-500/10", icon: Loader2 },
  completed: { label: "დასრულდა", className: "text-emerald-700 bg-emerald-500/10", icon: Check },
  partial: { label: "ნაწილობრივ", className: "text-amber-700 bg-amber-500/10", icon: AlertCircle },
  failed: { label: "შეცდომა", className: "text-destructive bg-destructive/10", icon: AlertCircle },
};

const AUDIENCE_LABEL = Object.fromEntries(AUDIENCES.map(({ value, label }) => [value, label]));

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("ka-GE");
}

export default function AdminBroadcast() {
  const [text, setText] = useState("");
  const [audience, setAudience] = useState("all");
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);

  const loadHistory = useCallback(async () => {
    try {
      const { data } = await api.get("/admin/broadcast-notification/history", { params: { limit: 50 } });
      setHistory(data);
    } catch (error) {
      toast.error(formatApiError(error.response?.data?.detail));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadHistory();
    const timer = window.setInterval(loadHistory, 5000);
    return () => window.clearInterval(timer);
  }, [loadHistory]);

  const send = async (event) => {
    event.preventDefault();
    const message = text.trim();
    if (!message || sending) return;
    const audienceName = AUDIENCE_LABEL[audience];
    if (!window.confirm(`გაიგზავნოს შეტყობინება სეგმენტზე „${audienceName}“?`)) return;

    setSending(true);
    try {
      const { data } = await api.post("/admin/broadcast-notification", { text: message, audience });
      setText("");
      toast.success(`გაგზავნა რიგშია · ${data.recipient_count} მიმღები`);
      await loadHistory();
    } catch (error) {
      toast.error(formatApiError(error.response?.data?.detail));
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="space-y-7" data-testid="admin-broadcast-page">
      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-border pb-5">
        <div>
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase text-muted-foreground">
            <span className="h-2 w-2 bg-primary" /> Admin communications
          </div>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-foreground">
            <Megaphone className="h-6 w-6 text-primary" /> მასობრივი შეტყობინება
          </h1>
        </div>
        <Button type="button" variant="outline" size="icon" onClick={loadHistory} aria-label="ისტორიის განახლება" title="განახლება">
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
        </Button>
      </header>

      <form onSubmit={send} className="grid gap-5 rounded-md border border-border bg-card p-5 md:grid-cols-[minmax(0,1fr)_260px]">
        <div className="space-y-2">
          <label htmlFor="broadcast-text" className="text-sm font-semibold">შეტყობინების ტექსტი</label>
          <Textarea
            id="broadcast-text"
            value={text}
            onChange={(event) => setText(event.target.value.slice(0, 500))}
            maxLength={500}
            rows={5}
            placeholder="შეიყვანეთ შეტყობინება..."
            required
            data-testid="broadcast-text"
          />
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>აპის inbox + Web Push</span>
            <span>{text.length} / 500</span>
          </div>
        </div>
        <div className="flex flex-col justify-between gap-5">
          <label className="space-y-2 text-sm font-semibold">
            <span>აუდიტორია</span>
            <select
              value={audience}
              onChange={(event) => setAudience(event.target.value)}
              className="h-10 w-full rounded-md border border-input bg-background px-3 font-normal text-foreground"
              data-testid="broadcast-audience"
            >
              {AUDIENCES.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
          <Button type="submit" disabled={sending || !text.trim()} className="w-full" data-testid="broadcast-send">
            {sending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Send className="mr-2 h-4 w-4" />}
            გაგზავნა
          </Button>
        </div>
      </form>

      <section aria-labelledby="broadcast-history-heading" className="space-y-3">
        <div className="flex items-center justify-between border-b border-border pb-3">
          <h2 id="broadcast-history-heading" className="text-lg font-semibold">გაგზავნის ისტორია</h2>
          <span className="font-mono text-xs text-muted-foreground">{history.length} / 50</span>
        </div>
        <div className="overflow-x-auto border border-border bg-card">
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead className="bg-secondary/70 text-xs uppercase text-muted-foreground">
              <tr>
                <th className="px-4 py-3 font-semibold">დრო / ავტორი</th>
                <th className="px-4 py-3 font-semibold">აუდიტორია</th>
                <th className="px-4 py-3 font-semibold">შეტყობინება</th>
                <th className="px-4 py-3 font-semibold">მიწოდება</th>
                <th className="px-4 py-3 font-semibold">სტატუსი</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {history.map((item) => {
                const status = STATUS[item.status] || STATUS.failed;
                const Icon = status.icon;
                return (
                  <tr key={item.id} className="align-top">
                    <td className="whitespace-nowrap px-4 py-3">
                      <div>{formatDate(item.created_at)}</div>
                      <div className="mt-1 text-xs text-muted-foreground">{item.actor?.name || "Admin"}</div>
                    </td>
                    <td className="px-4 py-3">{AUDIENCE_LABEL[item.audience] || item.audience}</td>
                    <td className="max-w-[360px] px-4 py-3">
                      <p className="line-clamp-2 whitespace-pre-wrap">{item.text}</p>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 font-mono text-xs">
                      {item.sent_count} / {item.recipient_count}
                      {item.failed_count > 0 && <span className="ml-2 text-destructive">({item.failed_count} ვერ გაიგზავნა)</span>}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center gap-1.5 rounded-sm px-2 py-1 text-xs font-semibold ${status.className}`}>
                        <Icon className={`h-3.5 w-3.5 ${item.status === "sending" ? "animate-spin" : ""}`} />
                        {status.label}
                      </span>
                    </td>
                  </tr>
                );
              })}
              {!loading && history.length === 0 && (
                <tr><td colSpan={5} className="px-4 py-12 text-center text-sm text-muted-foreground">შეტყობინებების ისტორია ცარიელია.</td></tr>
              )}
              {loading && history.length === 0 && (
                <tr><td colSpan={5} className="px-4 py-12 text-center"><Loader2 className="mx-auto h-5 w-5 animate-spin text-muted-foreground" /></td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}