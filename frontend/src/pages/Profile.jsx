import { useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Save, Building2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { StatusBadge } from "@/components/StatusBadge";
import { toast } from "sonner";

export default function Profile() {
  const { user, refreshUser } = useAuth();
  const [form, setForm] = useState({ name: user.name || "", business_name: user.business_name || "", address: user.address || "", phone: user.phone || "" });
  const [saving, setSaving] = useState(false);

  const save = async (e) => {
    e.preventDefault();
    setSaving(true);
    try { await api.put("/profile", form); await refreshUser(); toast.success("Profile updated"); }
    catch (err) { toast.error(formatApiError(err.response?.data?.detail)); }
    finally { setSaving(false); }
  };

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-6 text-2xl font-bold tracking-tight sm:text-3xl">Profile Settings</h1>
      <div className="rounded-xl border border-border bg-card p-6">
        <div className="mb-6 flex items-center gap-4">
          <div className="flex h-16 w-16 items-center justify-center rounded-xl bg-primary/15 text-2xl font-extrabold text-primary">{user.business_name?.[0]?.toUpperCase()}</div>
          <div>
            <div className="flex items-center gap-2"><h2 className="text-lg font-semibold">{user.business_name}</h2><StatusBadge status={user.status || "active"} /></div>
            <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">{user.role} · {user.email}</p>
          </div>
        </div>

        <form onSubmit={save} className="space-y-4">
          <div><Label htmlFor="bn">Business name</Label><Input id="bn" value={form.business_name} onChange={(e) => setForm({ ...form, business_name: e.target.value })} className="mt-1.5" data-testid="profile-business" /></div>
          <div><Label htmlFor="cn">Contact name</Label><Input id="cn" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="mt-1.5" data-testid="profile-name" /></div>
          <div><Label htmlFor="ph">Phone</Label><Input id="ph" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} className="mt-1.5" data-testid="profile-phone" /></div>
          <div><Label htmlFor="ad">{user.role === "supplier" ? "Warehouse / business address" : "Store / delivery address"}</Label><Textarea id="ad" value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} className="mt-1.5" rows={2} data-testid="profile-address" /></div>
          <Button type="submit" disabled={saving} data-testid="save-profile-btn"><Save className="mr-1.5 h-4 w-4" /> {saving ? "Saving..." : "Save Changes"}</Button>
        </form>
      </div>
    </div>
  );
}
