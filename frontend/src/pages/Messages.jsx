import { useEffect, useRef, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { useI18n } from "@/context/I18nContext";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { MessageSquare, Plus, Search, Send, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

export default function Messages() {
  const { user } = useAuth();
  const i18n = useI18n();
  const t = i18n?.t || ((key) => key);
  const QUICK = [t("msg.q1"), t("msg.q2"), t("msg.q3"), t("msg.q4")];
  const [contacts, setContacts] = useState([]);
  const [active, setActive] = useState(null);
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const [contactDialogOpen, setContactDialogOpen] = useState(false);
  const [contactQuery, setContactQuery] = useState("");
  const [contactResults, setContactResults] = useState([]);
  const [searchingContacts, setSearchingContacts] = useState(false);
  const [savingContact, setSavingContact] = useState(false);
  const [manualContact, setManualContact] = useState({ name: "", phone: "", role: "store" });
  const endRef = useRef(null);

  const loadContacts = async () => {
    try {
      const { data } = await api.get("/contacts");
      setContacts(data);
      setActive((current) => current
        ? data.find((contact) => contact.id === current.id) || null
        : data[0] || null);
    } catch (error) {
      console.error("Could not load messaging contacts:", error);
      toast.error(formatApiError(error.response?.data?.detail) || t("msg.contactsLoadError"));
    }
  };

  useEffect(() => { loadContacts(); }, []);

  useEffect(() => {
    if (!contactDialogOpen || !contactQuery.trim()) {
      setContactResults([]);
      return undefined;
    }
    let activeRequest = true;
    const timeout = setTimeout(async () => {
      setSearchingContacts(true);
      try {
        const { data } = await api.get("/contacts/search", { params: { query: contactQuery } });
        if (activeRequest) setContactResults(data);
      } catch (error) {
        console.error("Could not search registered contacts:", error);
        if (activeRequest) toast.error(formatApiError(error.response?.data?.detail) || t("msg.contactSearchError"));
      } finally {
        if (activeRequest) setSearchingContacts(false);
      }
    }, 250);
    return () => {
      activeRequest = false;
      clearTimeout(timeout);
    };
  }, [contactDialogOpen, contactQuery, t]);

  const loadMsgs = (id) => api.get(`/messages/${id}`).then((r) => setMessages(r.data));
  useEffect(() => {
    if (!active) return;
    if (active.is_external_contact) {
      setMessages([]);
      return undefined;
    }
    loadMsgs(active.id).catch((error) => {
      console.error("Could not load conversation:", error);
      toast.error(formatApiError(error.response?.data?.detail) || t("msg.messagesLoadError"));
    });
    const iv = setInterval(() => loadMsgs(active.id), 5000);
    return () => clearInterval(iv);
  }, [active, t]);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  const send = async (body) => {
    const val = (body ?? text).trim();
    if (!val || !active) return;
    if (active.is_external_contact) {
      if (!active.phone) {
        toast.error(t("msg.contactPhoneRequired"));
        return;
      }
      window.location.href = `sms:${active.phone.replace(/[^\d+]/g, "")}?body=${encodeURIComponent(val)}`;
      return;
    }
    try {
      await api.post("/messages", { to_id: active.id, text: val });
    } catch (error) {
      console.error("Could not send chat message:", error);
      toast.error(formatApiError(error.response?.data?.detail) || t("msg.sendError"));
      return;
    }
    setText("");
    loadMsgs(active.id);
  };

  const addContact = async (contact) => {
    setSavingContact(true);
    try {
      const { data } = await api.post("/contacts", {
        contact_id: contact.id,
        name: contact.name || contact.business_name,
        phone: contact.phone || "",
        role: contact.role || "other",
        kind: contact.kind || "registered",
      });
      setContacts((current) => [data, ...current.filter((item) => item.id !== data.id)]);
      setActive(data);
      setMessages([]);
      setContactDialogOpen(false);
      setContactQuery("");
      toast.success(t("msg.contactAdded"));
      return true;
    } catch (error) {
      console.error("Could not add selected contact:", error);
      toast.error(formatApiError(error.response?.data?.detail) || t("msg.contactAddError"));
      return false;
    } finally {
      setSavingContact(false);
    }
  };

  const addManualContact = async (event) => {
    event.preventDefault();
    if (await addContact({ ...manualContact, kind: "manual" })) {
      setManualContact({ name: "", phone: "", role: "store" });
    }
  };

  const contactName = (contact) => contact.business_name || contact.name || contact.email || t("msg.unnamedContact");
  const roleLabel = (contact) => {
    const role = contact.contact_kind === "driver" ? "driver" : contact.role;
    return t(["store", "driver", "other"].includes(role) ? `msg.role${role[0].toUpperCase()}${role.slice(1)}` : `roles.${role}`);
  };

  return (
    <div>
      <h1 className="mb-6 text-2xl font-bold tracking-tight sm:text-3xl">{t("msg.title")}</h1>
      <div className="grid gap-4 lg:grid-cols-12">
        <div className="rounded-xl border border-border bg-card lg:col-span-4">
          <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
            <p className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-wider text-muted-foreground"><Users className="h-4 w-4" /> {t("msg.contacts")}</p>
            <Button type="button" variant="outline" size="sm" onClick={() => setContactDialogOpen(true)} data-testid="add-contact-button">
              <Plus className="mr-1.5 h-4 w-4" />{t("msg.addContact")}
            </Button>
          </div>
          {contacts.length === 0 ? <p className="px-4 py-10 text-center text-sm text-muted-foreground">{t("msg.noContacts")}</p> : (
            <div className="max-h-[60vh] overflow-y-auto">
              {contacts.map((c) => (
                <button key={c.id} onClick={() => setActive(c)} data-testid={`contact-${c.id}`}
                  className={cn("flex w-full items-center gap-3 border-b border-border/50 px-4 py-3 text-left transition-colors duration-200 hover:bg-secondary", active?.id === c.id && "bg-secondary")}>
                  <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary/15 font-bold text-primary">{contactName(c)[0]?.toUpperCase()}</div>
                  <div className="min-w-0"><p className="truncate text-sm font-semibold">{contactName(c)}</p><p className="truncate font-mono text-[11px] text-muted-foreground">{roleLabel(c)}{c.phone ? ` · ${c.phone}` : ""}</p></div>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="flex h-[65vh] flex-col rounded-xl border border-border bg-card lg:col-span-8">
          {!active ? (
            <div className="flex flex-1 flex-col items-center justify-center text-center"><MessageSquare className="h-12 w-12 text-muted-foreground" /><p className="mt-3 text-sm text-muted-foreground">{t("msg.selectContact")}</p></div>
          ) : (
            <>
              <div className="border-b border-border px-4 py-3"><p className="font-semibold">{contactName(active)}</p><p className="font-mono text-[11px] text-muted-foreground">{roleLabel(active)}{active.phone ? ` · ${active.phone}` : ""}</p></div>
              <div className="flex-1 space-y-3 overflow-y-auto p-4" data-testid="message-thread">
                {active.is_external_contact && (
                  <p className="rounded-lg border border-info/20 bg-info/5 p-3 text-xs text-muted-foreground">{t("msg.externalContactHint")}</p>
                )}
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
                  {QUICK.map((q, i) => <button key={i} onClick={() => send(q)} data-testid={`quick-reply-${i}`} className="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground transition-colors duration-200 hover:border-primary/40 hover:text-foreground">{q}</button>)}
                </div>
                <form onSubmit={(e) => { e.preventDefault(); send(); }} className="flex gap-2">
                  <Input value={text} onChange={(e) => setText(e.target.value)} placeholder={t("msg.typeMessage")} data-testid="message-input" />
                  <Button type="submit" size="icon" disabled={active.is_external_contact && !active.phone} aria-label={active.is_external_contact ? t("msg.openSms") : t("msg.send")} data-testid="send-message-btn">
                    <Send className="h-4 w-4" />
                  </Button>
                </form>
              </div>
            </>
          )}
        </div>
      </div>
      <Dialog open={contactDialogOpen} onOpenChange={setContactDialogOpen}>
        <DialogContent className="border-border bg-card text-foreground sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>{t("msg.addContactTitle")}</DialogTitle>
            <DialogDescription>{t("msg.addContactDescription")}</DialogDescription>
          </DialogHeader>
          <section className="space-y-3">
            <label className="block space-y-1.5 text-xs font-medium text-muted-foreground">
              <span>{t("msg.searchContact")}</span>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input value={contactQuery} onChange={(event) => setContactQuery(event.target.value)} className="pl-9" placeholder={t("msg.searchContactPlaceholder")} data-testid="contact-search-input" />
              </div>
            </label>
            {searchingContacts ? (
              <div className="h-20 animate-pulse rounded-lg bg-secondary" />
            ) : contactQuery.trim() ? (
              <ul className="max-h-48 space-y-2 overflow-y-auto">
                {contactResults.length ? contactResults.map((contact) => (
                  <li key={`${contact.kind}-${contact.id}`}>
                    <button type="button" onClick={() => addContact(contact)} disabled={savingContact} className="flex w-full items-center gap-3 rounded-lg border border-border bg-secondary/30 p-3 text-left hover:bg-secondary" data-testid={`select-contact-${contact.id}`}>
                      <span className="flex h-9 w-9 items-center justify-center rounded-full bg-primary/15 font-bold text-primary">{(contact.name || contact.business_name || "?")[0]?.toUpperCase()}</span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-semibold">{contact.name || contact.business_name}</span>
                        <span className="block truncate text-xs text-muted-foreground">{roleLabel(contact)}{contact.phone ? ` · ${contact.phone}` : ""}</span>
                      </span>
                    </button>
                  </li>
                )) : <li className="py-3 text-center text-xs text-muted-foreground">{t("msg.noSearchResults")}</li>}
              </ul>
            ) : null}
          </section>
          <form onSubmit={addManualContact} className="space-y-3 border-t border-border pt-4" data-testid="manual-contact-form">
            <h3 className="text-sm font-semibold">{t("msg.manualContact")}</h3>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="space-y-1 text-xs text-muted-foreground">
                <span>{t("msg.contactName")}</span>
                <Input required maxLength={160} value={manualContact.name} onChange={(event) => setManualContact((current) => ({ ...current, name: event.target.value }))} data-testid="manual-contact-name" />
              </label>
              <label className="space-y-1 text-xs text-muted-foreground">
                <span>{t("msg.contactPhone")}</span>
                <Input required type="tel" maxLength={40} value={manualContact.phone} onChange={(event) => setManualContact((current) => ({ ...current, phone: event.target.value }))} data-testid="manual-contact-phone" />
              </label>
              <label className="space-y-1 text-xs text-muted-foreground sm:col-span-2">
                <span>{t("msg.contactRole")}</span>
                <select value={manualContact.role} onChange={(event) => setManualContact((current) => ({ ...current, role: event.target.value }))} className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground" data-testid="manual-contact-role">
                  <option value="store">{t("msg.roleStore")}</option>
                  <option value="driver">{t("msg.roleDriver")}</option>
                  <option value="other">{t("msg.roleOther")}</option>
                </select>
              </label>
            </div>
            <DialogFooter>
              <Button type="submit" disabled={savingContact} data-testid="save-manual-contact-button">
                <Plus className="mr-2 h-4 w-4" />{savingContact ? t("msg.addingContact") : t("msg.addContact")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
