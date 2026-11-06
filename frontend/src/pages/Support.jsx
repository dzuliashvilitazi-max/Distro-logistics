import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, formatApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Bot, Send, LifeBuoy, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";

const GREETING = "გამარჯობა! მე ვარ „დისტრო“ — დაგეხმარებით პლატფორმის გამოყენებაში.";

export default function Support() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [chat, setChat] = useState([{ from: "bot", text: GREETING }]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [suggestAdmin, setSuggestAdmin] = useState(false);
  const [ticketText, setTicketText] = useState("");
  const [tickets, setTickets] = useState([]);
  const endRef = useRef(null);
  const typeLabel = user.role === "supplier" ? "დისტრიბუტორი" : user.role === "retailer" ? "მაღაზია" : "ადმინისტრატორი";

  const loadTickets = () => api.get("/support/tickets").then((r) => setTickets(r.data)).catch(() => {});
  useEffect(() => { loadTickets(); }, []);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [chat]);

  const ask = async (e) => {
    e.preventDefault();
    const msg = text.trim();
    if (!msg) return;
    setChat((c) => [...c, { from: "me", text: msg }]);
    setText(""); setBusy(true);
    try {
      const { data } = await api.post("/support/assistant", { message: msg });
      setChat((c) => [...c, { from: "bot", text: data.reply }]);
      setSuggestAdmin(Boolean(data.suggest_admin));
    } catch (err) { toast.error(formatApiError(err.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  const sendTicket = async () => {
    if (ticketText.trim().length < 3) return;
    try {
      const { data: ticket } = await api.post("/support/tickets", { message: ticketText.trim() });
      setTicketText(""); setSuggestAdmin(false);
      loadTickets();
      if (ticket.admin_id) {
        navigate(`/messages?contactId=${encodeURIComponent(ticket.admin_id)}`);
      } else {
        toast.success("შეტყობინება გაეგზავნა ადმინისტრატორს");
      }
    } catch (err) { toast.error(formatApiError(err.response?.data?.detail)); }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-6" data-testid="support-page">
      <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight sm:text-3xl"><LifeBuoy className="h-6 w-6" /> მხარდაჭერა</h1>

      <div className="rounded-xl border border-border bg-card">
        <div className="flex items-center gap-2 border-b border-border px-4 py-3 text-sm font-semibold"><Bot className="h-4 w-4 text-primary" /> დისტრო · {typeLabel}</div>
        <div className="max-h-96 space-y-2 overflow-y-auto p-4">
          {chat.map((m, i) => (
            <div key={i} className={m.from === "me" ? "flex justify-end" : "flex justify-start"}>
              <div className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${m.from === "me" ? "bg-primary text-primary-foreground" : "bg-secondary"}`}>{m.text}</div>
            </div>
          ))}
          <div ref={endRef} />
        </div>
        <form onSubmit={ask} className="flex gap-2 border-t border-border p-3">
          <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="დასვით კითხვა..." data-testid="support-input" maxLength={1000} />
          <Button type="submit" disabled={busy} data-testid="support-send">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}</Button>
        </form>
      </div>

      <div className="rounded-xl border border-border bg-card p-4">
        <p className="text-sm font-semibold">ადმინისტრატორთან დაკავშირება</p>
        {suggestAdmin && <p className="mt-1 text-xs text-muted-foreground">პასუხი ვერ მოვძებნე — მიწერეთ ადმინისტრატორს.</p>}
        <Textarea value={ticketText} onChange={(e) => setTicketText(e.target.value)} rows={3} className="mt-2" maxLength={2000} placeholder="აღწერეთ პრობლემა" data-testid="ticket-text" />
        <Button className="mt-2" onClick={sendTicket} disabled={ticketText.trim().length < 3} data-testid="ticket-send">გაგზავნა ადმინისტრატორთან</Button>
      </div>

      {tickets.length > 0 && (
        <div className="space-y-3" data-testid="my-tickets">
          <p className="text-sm font-semibold">ჩემი მიმართვები</p>
          {tickets.map((t) => (
            <div key={t.id} className="rounded-lg border border-border p-3 text-sm">
              <p>{t.message}</p>
              <p className="mt-1 text-xs text-muted-foreground">{new Date(t.created_at).toLocaleString()} · {t.status}</p>
              {t.replies?.map((r, i) => <p key={i} className="mt-2 rounded bg-secondary px-2 py-1"><b>{r.by}:</b> {r.text}</p>)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
