import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { Truck, Package, ShieldCheck, TrendingUp, BarChart3, MessageSquare, ArrowRight, Boxes, Globe } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/context/AuthContext";
import { useI18n } from "@/context/I18nContext";
import { LANGUAGES } from "@/lib/i18n";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";

export function PublicLangSwitcher() {
  const { lang, setLang } = useI18n();
  const current = LANGUAGES.find((l) => l.code === lang) || LANGUAGES[1];
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" className="gap-1.5" data-testid="language-switcher"><Globe className="h-4 w-4" /> {current.short}</Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-40 bg-popover">
        {LANGUAGES.map((l) => (
          <DropdownMenuItem key={l.code} onClick={() => setLang(l.code)} data-testid={`lang-option-${l.code}`} className={l.code === lang ? "bg-primary/10 font-semibold text-primary" : ""}>{l.label}</DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export default function Landing() {
  const { user } = useAuth();
  const { t } = useI18n();
  const FEATURES = [
    { icon: Package, t: "land.f1t", d: "land.f1d" },
    { icon: Truck, t: "land.f2t", d: "land.f2d" },
    { icon: Boxes, t: "land.f3t", d: "land.f3d" },
    { icon: BarChart3, t: "land.f4t", d: "land.f4d" },
    { icon: MessageSquare, t: "land.f5t", d: "land.f5d" },
    { icon: ShieldCheck, t: "land.f6t", d: "land.f6d" },
  ];
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-40 border-b border-border bg-background/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3.5 sm:px-6 lg:px-8">
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary"><Truck className="h-5 w-5 text-primary-foreground" /></div>
            <p className="text-lg font-extrabold tracking-tight">Distro<span className="text-primary">Logistics</span></p>
          </div>
          <div className="flex items-center gap-2">
            <PublicLangSwitcher />
            {user ? (
              <Link to="/"><Button data-testid="go-dashboard-btn">{t("land.goToDashboard")} <ArrowRight className="ml-1.5 h-4 w-4" /></Button></Link>
            ) : (
              <>
                <Link to="/login"><Button variant="ghost" data-testid="nav-login-btn">{t("land.signIn")}</Button></Link>
                <Link to="/register"><Button data-testid="nav-register-btn">{t("land.getStarted")}</Button></Link>
              </>
            )}
          </div>
        </div>
      </header>

      <section className="relative overflow-hidden">
        <div className="mx-auto grid max-w-7xl items-center gap-10 px-4 py-16 sm:px-6 lg:grid-cols-2 lg:gap-8 lg:px-8 lg:py-24">
          <motion.div initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6 }}>
            <span className="inline-flex items-center gap-2 rounded-full border border-primary/30 bg-primary/10 px-3 py-1 font-mono text-xs font-semibold uppercase tracking-wider text-primary">
              <TrendingUp className="h-3.5 w-3.5" /> {t("land.badge")}
            </span>
            <h1 className="mt-5 text-4xl font-extrabold leading-none tracking-tight sm:text-5xl lg:text-6xl">
              {t("land.heroPre")} <span className="text-primary">{t("land.heroEm")}</span>{t("land.heroPost")}
            </h1>
            <p className="mt-6 max-w-lg text-base leading-relaxed text-muted-foreground sm:text-lg">{t("land.heroSubtitle")}</p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link to="/register"><Button size="lg" className="h-12 px-6 text-base" data-testid="hero-start-btn">{t("land.startDistributing")} <ArrowRight className="ml-1.5 h-4.5 w-4.5" /></Button></Link>
              <Link to="/login"><Button size="lg" variant="outline" className="h-12 px-6 text-base" data-testid="hero-demo-btn">{t("land.viewDemo")}</Button></Link>
            </div>
            <div className="mt-10 flex gap-8">
              {[["3", "land.statRoles"], ["8+", "land.statProducts"], ["5", "land.statStates"]].map(([n, l]) => (
                <div key={l}><p className="text-3xl font-extrabold text-foreground">{n}</p><p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">{t(l)}</p></div>
              ))}
            </div>
          </motion.div>
          <motion.div initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.6, delay: 0.15 }} className="relative">
            <div className="overflow-hidden rounded-2xl border border-border shadow-2xl">
              <img src="https://images.unsplash.com/photo-1553413077-190dd305871c?crop=entropy&cs=srgb&fm=jpg&q=85&w=1000" alt="Warehouse logistics" className="h-full w-full object-cover" />
            </div>
          </motion.div>
        </div>
      </section>

      <section className="border-t border-border bg-secondary/30">
        <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8 lg:py-20">
          <h2 className="text-2xl font-bold tracking-tight sm:text-3xl lg:text-4xl">{t("land.featuresTitle")}</h2>
          <p className="mt-3 max-w-xl text-muted-foreground">{t("land.featuresSubtitle")}</p>
          <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((f, i) => (
              <motion.div key={f.t} initial={{ opacity: 0, y: 20 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ delay: i * 0.05 }}
                className="rounded-xl border border-border bg-card p-6 transition-colors duration-200 hover:border-primary/40">
                <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-primary/10"><f.icon className="h-5.5 w-5.5 text-primary" style={{ width: 22, height: 22 }} /></div>
                <h3 className="mt-4 text-lg font-semibold">{t(f.t)}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{t(f.d)}</p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      <footer className="border-t border-border">
        <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-4 px-4 py-8 sm:flex-row sm:px-6 lg:px-8">
          <div className="flex flex-col gap-1.5">
            <p className="font-mono text-xs text-muted-foreground">{t("land.footer")}</p>
            <div className="flex gap-4 text-xs">
              <Link to="/terms" className="text-muted-foreground transition-colors hover:text-primary hover:underline" data-testid="footer-terms-link">{t("auth.terms")}</Link>
              <Link to="/privacy" className="text-muted-foreground transition-colors hover:text-primary hover:underline" data-testid="footer-privacy-link">{t("auth.privacy")}</Link>
            </div>
          </div>
          <Link to="/register"><Button variant="outline" data-testid="footer-cta-btn">{t("land.createAccount")}</Button></Link>
        </div>
      </footer>
    </div>
  );
}
