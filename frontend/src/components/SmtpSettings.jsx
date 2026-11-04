import { useEffect, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { Mail, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";

export function SmtpSettings() {
  const [form, setForm] = useState({ smtp_user: "", smtp_password: "", smtp_host: "smtp.gmail.com", smtp_port: 587 });
  const [passwordSet, setPasswordSet] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get("/profile/smtp").then(({ data }) => {
      setForm((f) => ({ ...f, smtp_user: data.smtp_user, smtp_host: data.smtp_host, smtp_port: data.smtp_port }));
      setPasswordSet(data.smtp_password_set);
    }).catch(() => {});
  }, []);

  const save = async () => {
    setBusy(true);
    try {
      const { data } = await api.put("/profile/smtp", { ...form, smtp_port: Number(form.smtp_port) || 587 });
      setPasswordSet(data.smtp_password_set);
      setForm((f) => ({ ...f, smtp_password: "" }));
      toast.success("SMTP პარამეტრები შენახულია");
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  return (
    <div className="rounded-lg border border-border p-4" data-testid="smtp-settings">
      <p className="flex items-center gap-2 text-sm font-semibold"><Mail className="h-4 w-4 text-primary" /> ინვოისების გაგზავნის ელ.ფოსტა (SMTP)</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2"><Label htmlFor="smtp-user">გამგზავნის ელფოსტა</Label>
          <Input id="smtp-user" type="email" value={form.smtp_user} onChange={(e) => setForm({ ...form, smtp_user: e.target.value })} className="mt-1.5" autoComplete="off" data-testid="smtp-user" /></div>
        <div className="sm:col-span-2"><Label htmlFor="smtp-pass">აპლიკაციის პაროლი (App Password)</Label>
          <Input id="smtp-pass" type="password" value={form.smtp_password} onChange={(e) => setForm({ ...form, smtp_password: e.target.value })} className="mt-1.5" autoComplete="new-password"
            placeholder={passwordSet ? "••••••••  (შენახულია; შესაცვლელად ჩაწერეთ ახალი)" : ""} data-testid="smtp-password" /></div>
        <div><Label htmlFor="smtp-host">SMTP ჰოსტი</Label>
          <Input id="smtp-host" value={form.smtp_host} onChange={(e) => setForm({ ...form, smtp_host: e.target.value })} className="mt-1.5" data-testid="smtp-host" /></div>
        <div><Label htmlFor="smtp-port">SMTP პორტი</Label>
          <Input id="smtp-port" type="number" value={form.smtp_port} onChange={(e) => setForm({ ...form, smtp_port: e.target.value })} className="mt-1.5" data-testid="smtp-port" /></div>
      </div>
      <Button type="button" onClick={save} disabled={busy} className="mt-3" data-testid="smtp-save">
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "SMTP-ის შენახვა"}
      </Button>
      <p className="mt-2 text-xs text-muted-foreground">პაროლი ბაზაში დაშიფრულად ინახება და უკან აღარ ბრუნდება. Gmail-ისთვის საჭიროა App Password.</p>
    </div>
  );
}
