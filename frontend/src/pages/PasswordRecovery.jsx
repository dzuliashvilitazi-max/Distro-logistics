import { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, KeyRound, Loader2, Mail } from "lucide-react";
import { api, formatApiError } from "@/lib/api";
import { useI18n } from "@/context/I18nContext";
import { PublicLangSwitcher } from "@/pages/Landing";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";

function RecoveryFrame({ icon: Icon, title, description, children }) {
  const { t } = useI18n();
  return (
    <div className="grid min-h-screen place-items-center bg-background p-6">
      <div className="w-full max-w-md">
        <div className="mb-5 flex justify-end"><PublicLangSwitcher /></div>
        <div className="rounded-xl border border-border bg-card p-6 sm:p-8">
          <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-lg bg-primary/10">
            <Icon className="h-6 w-6 text-primary" />
          </div>
          <h1 className="text-2xl font-bold">{title}</h1>
          <p className="mt-2 text-sm text-muted-foreground">{description}</p>
          {children}
          <Link to="/login" className="mt-6 inline-flex items-center gap-2 text-sm font-semibold text-primary hover:underline">
            <ArrowLeft className="h-4 w-4" />{t("passwordReset.backToLogin")}
          </Link>
        </div>
      </div>
    </div>
  );
}

export function ForgotPassword() {
  const { t } = useI18n();
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState("email");

  const requestCode = async (event) => {
    event.preventDefault();
    setLoading(true);
    try {
      const { data } = await api.post("/forgot-password", { email });
      setStep("code");
      toast.success(data.message || t("passwordReset.sent"));
    } catch (error) {
      toast.error(formatApiError(error.response?.data?.detail) || error.message);
    } finally {
      setLoading(false);
    }
  };

  const resetPassword = async (event) => {
    event.preventDefault();
    if (password !== confirmation) {
      toast.error(t("passwordReset.passwordMismatch"));
      return;
    }
    setLoading(true);
    try {
      const { data } = await api.post("/reset-password", { email, code, password });
      setStep("done");
      toast.success(data.message || t("passwordReset.resetSuccess"));
    } catch (error) {
      toast.error(formatApiError(error.response?.data?.detail) || error.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <RecoveryFrame icon={step === "email" ? Mail : KeyRound}
      title={step === "email" ? t("passwordReset.forgotTitle") : t("passwordReset.resetTitle")}
      description={step === "email" ? t("passwordReset.forgotDescription") : t("passwordReset.resetDescription")}>
      {step === "email" && (
        <form onSubmit={requestCode} className="mt-6 space-y-4">
          <div>
            <Label htmlFor="recovery-email">{t("auth.email")}</Label>
            <Input id="recovery-email" type="email" autoComplete="email" required value={email}
              onChange={(event) => setEmail(event.target.value)} className="mt-1.5" data-testid="recovery-email" />
          </div>
          <Button type="submit" className="h-11 w-full" disabled={loading} data-testid="recovery-submit">
            {loading ? <Loader2 className="h-5 w-5 animate-spin" /> : t("passwordReset.sendCode")}
          </Button>
        </form>
      )}
      {step === "code" && (
        <form onSubmit={resetPassword} className="mt-6 space-y-4">
          <div>
            <Label htmlFor="recovery-email-confirm">{t("auth.email")}</Label>
            <Input id="recovery-email-confirm" type="email" autoComplete="email" required value={email} readOnly
              className="mt-1.5" data-testid="recovery-email-confirm" />
            <button type="button" onClick={() => setStep("email")} className="mt-1 text-xs font-semibold text-primary hover:underline">
              {t("passwordReset.changeEmail")}
            </button>
          </div>
          <div>
            <Label htmlFor="recovery-code">{t("passwordReset.codeLabel")}</Label>
            <Input id="recovery-code" inputMode="numeric" autoComplete="one-time-code" required maxLength={6}
              value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
              className="mt-1.5 text-center font-mono text-xl tracking-[0.3em]" data-testid="recovery-code" />
          </div>
          <div>
            <Label htmlFor="new-password">{t("passwordReset.newPassword")}</Label>
            <Input id="new-password" type="password" autoComplete="new-password" required minLength={8} maxLength={72}
              value={password} onChange={(event) => setPassword(event.target.value)} className="mt-1.5" data-testid="new-password" />
          </div>
          <div>
            <Label htmlFor="confirm-password">{t("passwordReset.confirmPassword")}</Label>
            <Input id="confirm-password" type="password" autoComplete="new-password" required minLength={8} maxLength={72}
              value={confirmation} onChange={(event) => setConfirmation(event.target.value)} className="mt-1.5" data-testid="confirm-password" />
          </div>
          <Button type="submit" className="h-11 w-full" disabled={loading || code.length !== 6} data-testid="reset-password-submit">
            {loading ? <Loader2 className="h-5 w-5 animate-spin" /> : t("passwordReset.resetButton")}
          </Button>
        </form>
      )}
      {step === "done" && <div className="mt-6 space-y-4">
        <p role="status" className="rounded-md border border-border bg-secondary/50 p-3 text-sm" data-testid="password-reset-complete">{t("passwordReset.resetSuccess")}</p>
        <Link to="/login" className="inline-flex h-11 w-full items-center justify-center rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground hover:opacity-90">{t("passwordReset.backToLogin")}</Link>
      </div>}
    </RecoveryFrame>
  );
}

export function ResetPassword() {
  return <ForgotPassword />;
}