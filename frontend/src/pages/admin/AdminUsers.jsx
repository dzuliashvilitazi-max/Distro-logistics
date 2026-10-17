import { useEffect, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";
import { Check, Ban, Users as UsersIcon, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

const TABS = [["all", "All"], ["retailer", "Retailers"], ["supplier", "Suppliers"], ["admin", "Admins"]];

export default function AdminUsers() {
  const [users, setUsers] = useState([]);
  const [tab, setTab] = useState("all");

  const load = () => api.get(`/admin/users?role=${tab}`).then((r) => setUsers(r.data));
  useEffect(() => { load(); }, [tab]);

  const setStatus = async (id, status) => {
    try { await api.put(`/admin/users/${id}/status`, { status }); toast.success(`User ${status === "active" ? "approved / activated" : status}`); load(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const pending = users.filter((u) => u.role === "supplier" && u.status === "pending");

  return (
    <div>
      <h1 className="mb-6 text-2xl font-bold tracking-tight sm:text-3xl">User Management</h1>

      {pending.length > 0 && (
        <div className="mb-6 rounded-xl border border-amber-500/30 bg-amber-500/5 p-5" data-testid="approval-queue">
          <h3 className="text-lg font-semibold text-amber-500">Supplier Approval Queue ({pending.length})</h3>
          <div className="mt-3 space-y-2">
            {pending.map((u) => (
              <div key={u.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-card px-4 py-3">
                <div><p className="font-semibold">{u.business_name}</p><p className="font-mono text-xs text-muted-foreground">{u.email} · {u.address}</p></div>
                <div className="flex gap-2">
                  <Button size="sm" onClick={() => setStatus(u.id, "active")} data-testid={`approve-supplier-${u.id}`}><Check className="mr-1 h-4 w-4" /> Approve</Button>
                  <Button size="sm" variant="outline" className="text-rose-500 hover:bg-rose-500/10" onClick={() => setStatus(u.id, "suspended")} data-testid={`reject-supplier-${u.id}`}><Ban className="mr-1 h-4 w-4" /> Reject</Button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="mb-5 flex flex-wrap gap-2">
        {TABS.map(([v, l]) => (
          <button key={v} onClick={() => setTab(v)} data-testid={`user-tab-${v}`}
            className={cn("rounded-full border px-4 py-1.5 text-sm font-medium transition-colors duration-200", tab === v ? "border-primary bg-primary text-primary-foreground" : "border-border text-muted-foreground hover:text-foreground")}>{l}</button>
        ))}
      </div>

      <div className="overflow-x-auto rounded-xl border border-border bg-card">
        <table className="w-full text-sm">
          <thead className="border-b border-border bg-secondary/50"><tr className="text-left font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
            <th className="px-4 py-3">Business</th><th className="px-4 py-3">Email</th><th className="px-4 py-3">Role</th><th className="px-4 py-3">Status</th><th className="px-4 py-3 text-right">Actions</th>
          </tr></thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} data-testid={`user-row-${u.id}`} className="border-b border-border/50 last:border-0">
                <td className="px-4 py-3 font-medium">{u.business_name}</td>
                <td className="px-4 py-3 text-muted-foreground">{u.email}</td>
                <td className="px-4 py-3"><span className="rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 font-mono text-[10px] font-semibold uppercase text-primary">{u.role}</span></td>
                <td className="px-4 py-3"><StatusBadge status={u.status || "active"} /></td>
                <td className="px-4 py-3"><div className="flex justify-end gap-1.5">
                  {u.role !== "admin" && (u.status === "active"
                    ? <Button size="sm" variant="outline" className="text-rose-500 hover:bg-rose-500/10" onClick={() => setStatus(u.id, "suspended")} data-testid={`suspend-user-${u.id}`}><Ban className="mr-1 h-3.5 w-3.5" /> Suspend</Button>
                    : <Button size="sm" variant="outline" onClick={() => setStatus(u.id, "active")} data-testid={`activate-user-${u.id}`}><RotateCcw className="mr-1 h-3.5 w-3.5" /> Activate</Button>)}
                </div></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
