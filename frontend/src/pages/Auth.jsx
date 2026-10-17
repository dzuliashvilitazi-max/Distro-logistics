import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { useI18n } from "@/context/I18nContext";
import { formatApiError } from "@/lib/api";
import { PublicLangSwitcher } from "@/pages/Landing";
import { Truck, Store, Warehouse, Loader2, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

const DEMO = [
  { email: "cornerstore@distro.com", role: "retailer", label: "Corner Store Market" },
  { email: "metro@distro.com", role: "supplier", label: "Metro Bev Distributors" },
  { email: "mgv67mk2j5@privaterelay.appleid.com", role: "admin", label: "Platform Admin", pw: "Admin@123" },
];

export default function Auth({ mode }) {
  const isRegister = mode === "register";
  const { login, register } = useAuth();
  const { t } = useI18n();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [role, setRole] = useState("retailer");
  const [form, setForm] = useState({ email: "", password: "", name: "", business_name: "", address: "" });

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      let user;
      if (isRegister) {
        user = await register({ ...form, role });
        toast.success(role === "supplier" ? t("auth.supplierCreated") : t("auth.welcomeMsg"));
      } else {
        user = await login(form.email, form.password);
        toast.success(`${t("auth.welcomeBack")}, ${user.business_name}`);
      }
      navigate("/");
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || err.message);
    } finally {
      setLoading(false);
    }
  };

  const quickLogin = async (d) => {
    setLoading(true);
    try {
      const user = await login(d.email, d.pw || "Password@123");
      toast.success(`${t("auth.signedInAs")} ${user.business_name}`);
      navigate("/");
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail));
    } finally { setLoading(false); }
  };

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="relative hidden flex-col justify-between overflow-hidden bg-primary p-12 text-primary-foreground lg:flex">
        <img src="https://images.unsplash.com/photo-1587293852726-70cdb56c2866?crop=entropy&cs=srgb&fm=jpg&q=85&w=1000" alt="Warehouse" className="absolute inset-0 h-full w-full object-cover opacity-20" />
        <Link to="/" className="relative flex items-center gap-2.5">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-white/15 backdrop-blur"><Truck className="h-5 w-5" /></div>
          <p className="text-xl font-extrabold">Distro<span className="opacity-80">Logistics</span></p>
        </Link>
        <div className="relative">
          <h2 className="text-3xl font-bold leading-tight">{t("auth.sidebarTitle")}</h2>
          <p className="mt-4 max-w-sm text-primary-foreground/80">{t("auth.sidebarSubtitle")}</p>
        </div>
        <p className="relative font-mono text-xs uppercase tracking-wider text-primary-foreground/70">© 2026 Distro Logistics</p>
      </div>

      <div className="flex items-center justify-center p-6 sm:p-12">
        <div className="w-full max-w-md">
          <div className="mb-4 flex justify-end"><PublicLangSwitcher /></div>
          <h1 className="text-3xl font-extrabold tracking-tight">{isRegister ? t("auth.createYourAccount") : t("auth.signIn")}</h1>
          <p className="mt-2 text-sm text-muted-foreground">{isRegister ? t("auth.registerSubtitle") : t("auth.signInSubtitle")}</p>

          <form onSubmit={submit} className="mt-8 space-y-4">
            {isRegister && (
              <div className="grid grid-cols-2 gap-3">
                {[{ v: "retailer", i: Store }, { v: "supplier", i: Warehouse }].map((r) => (
                  <button type="button" key={r.v} onClick={() => setRole(r.v)} data-testid={`role-select-${r.v}`}
                    className={cn("flex flex-col items-center gap-2 rounded-xl border-2 p-4 transition-colors duration-200",
                      role === r.v ? "border-primary bg-primary/5" : "border-border hover:border-primary/40")}>
                    <r.i className={cn("h-6 w-6", role === r.v ? "text-primary" : "text-muted-foreground")} />
                    <span className="text-center text-sm font-semibold">{t(`roles.${r.v}`)}</span>
                  </button>
                ))}
              </div>
            )}
            {isRegister && (
              <>
                <div><Label htmlFor="name">{t("auth.contactName")}</Label><Input id="name" required value={form.name} onChange={set("name")} className="mt-1.5" data-testid="register-name" /></div>
                <div><Label htmlFor="business">{t("auth.businessName")}</Label><Input id="business" required value={form.business_name} onChange={set("business_name")} className="mt-1.5" data-testid="register-business" /></div>
                <div><Label htmlFor="address">{t("auth.businessAddress")}</Label><Input id="address" value={form.address} onChange={set("address")} className="mt-1.5" data-testid="register-address" /></div>
              </>
            )}
            <div><Label htmlFor="email">{t("auth.email")}</Label><Input id="email" type="email" required value={form.email} onChange={set("email")} className="mt-1.5" data-testid="auth-email" placeholder="you@business.com" /></div>
            <div><Label htmlFor="password">{t("auth.password")}</Label><Input id="password" type="password" required value={form.password} onChange={set("password")} className="mt-1.5" data-testid="auth-password" placeholder="••••••••" /></div>
            <Button type="submit" className="h-11 w-full text-base" disabled={loading} data-testid="auth-submit">
              {loading ? <Loader2 className="h-5 w-5 animate-spin" /> : <>{isRegister ? t("auth.createAccount") : t("auth.signIn")} <ArrowRight className="ml-1.5 h-4 w-4" /></>}
            </Button>
          </form>

          {!isRegister && (
            <div className="mt-6">
              <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">{t("auth.quickDemo")}</p>
              <div className="mt-2 space-y-2">
                {DEMO.map((d) => (
                  <button key={d.email} onClick={() => quickLogin(d)} disabled={loading} data-testid={`demo-login-${d.role}`}
                    className="flex w-full items-center justify-between rounded-lg border border-border bg-card px-3 py-2.5 text-left transition-colors duration-200 hover:border-primary/50 hover:bg-secondary">
                    <span><span className="text-sm font-semibold">{d.label}</span><span className="ml-2 font-mono text-[11px] text-muted-foreground">{d.email}</span></span>
                    <span className="rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 font-mono text-[10px] font-semibold text-primary">{t(`roles.${d.role}`)}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          <p className="mt-6 text-center text-sm text-muted-foreground">
            {isRegister ? t("auth.alreadyHave") : t("auth.newToDistro")}
            <Link to={isRegister ? "/login" : "/register"} className="font-semibold text-primary hover:underline" data-testid="auth-switch-link">
              {isRegister ? t("auth.signIn") : t("auth.createOne")}
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
