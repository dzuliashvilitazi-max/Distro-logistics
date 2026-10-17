import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { MessageSquare, Send, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const QUICK = ["What's the lead time?", "Can you confirm stock?", "Please update delivery status.", "Thanks!"];

export default function Messages() {
  const { user } = useAuth();
  const [contacts, setContacts] = useState([]);
  const [active, setActive] = useState(null);
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const endRef = useRef(null);

  useEffect(() => { api.get("/contacts").then((r) => { setContacts(r.data); if (r.data[0]) setActive(r.data[0]); }); }, []);

  const loadMsgs = (id) => api.get(`/messages/${id}`).then((r) => setMessages(r.data));
  useEffect(() => {
    if (!active) return;
    loadMsgs(active.id);
    const t = setInterval(() => loadMsgs(active.id), 5000);
    return () => clearInterval(t);
  }, [active]);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  const send = async (body) => {
    const t = (body ?? text).trim();
    if (!t || !active) return;
    await api.post("/messages", { to_id: active.id, text: t });
    setText("");
    loadMsgs(active.id);
  };

  return (
    <div>
      <h1 className="mb-6 text-2xl font-bold tracking-tight sm:text-3xl">Messages</h1>
      <div className="grid gap-4 lg:grid-cols-12">
        <div className="rounded-xl border border-border bg-card lg:col-span-4">
          <div className="border-b border-border px-4 py-3"><p className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-wider text-muted-foreground"><Users className="h-4 w-4" /> Contacts</p></div>
          {contacts.length === 0 ? <p className="px-4 py-10 text-center text-sm text-muted-foreground">No contacts yet. Place or receive an order to start chatting.</p> : (
            <div className="max-h-[60vh] overflow-y-auto">
              {contacts.map((c) => (
                <button key={c.id} onClick={() => setActive(c)} data-testid={`contact-${c.id}`}
                  className={cn("flex w-full items-center gap-3 border-b border-border/50 px-4 py-3 text-left transition-colors duration-200 hover:bg-secondary", active?.id === c.id && "bg-secondary")}>
                  <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary/15 font-bold text-primary">{c.business_name?.[0]?.toUpperCase()}</div>
                  <div className="min-w-0"><p className="truncate text-sm font-semibold">{c.business_name}</p><p className="truncate font-mono text-[11px] uppercase text-muted-foreground">{c.role}</p></div>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="flex h-[65vh] flex-col rounded-xl border border-border bg-card lg:col-span-8">
          {!active ? (
            <div className="flex flex-1 flex-col items-center justify-center text-center"><MessageSquare className="h-12 w-12 text-muted-foreground" /><p className="mt-3 text-sm text-muted-foreground">Select a contact to start messaging.</p></div>
          ) : (
            <>
              <div className="border-b border-border px-4 py-3"><p className="font-semibold">{active.business_name}</p><p className="font-mono text-[11px] uppercase text-muted-foreground">{active.role}</p></div>
              <div className="flex-1 space-y-3 overflow-y-auto p-4" data-testid="message-thread">
                {messages.map((m) => {
                  const mine = m.from_id === user.id;
                  return (
                    <div key={m.id} className={cn("flex", mine ? "justify-end" : "justify-start")}>
                      <div className={cn("max-w-[75%] rounded-2xl px-4 py-2 text-sm", mine ? "bg-primary text-primary-foreground" : "bg-secondary text-foreground")}>
                        <p>{m.text}</p>
                        <p className={cn("mt-1 font-mono text-[10px]", mine ? "text-primary-foreground/70" : "text-muted-foreground")}>{new Date(m.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</p>
                      </div>
                    </div>
                  );
                })}
                <div ref={endRef} />
              </div>
              <div className="border-t border-border p-3">
                <div className="mb-2 flex flex-wrap gap-1.5">
                  {QUICK.map((q) => <button key={q} onClick={() => send(q)} data-testid={`quick-reply-${q.slice(0, 6)}`} className="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground transition-colors duration-200 hover:border-primary/40 hover:text-foreground">{q}</button>)}
                </div>
                <form onSubmit={(e) => { e.preventDefault(); send(); }} className="flex gap-2">
                  <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Type a message..." data-testid="message-input" />
                  <Button type="submit" size="icon" data-testid="send-message-btn"><Send className="h-4 w-4" /></Button>
                </form>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
