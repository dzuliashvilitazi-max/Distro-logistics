import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { useI18n } from "@/context/I18nContext";
import { requestErrorMessage } from "@/lib/api";
import { PublicLangSwitcher } from "@/pages/Landing";
import { Truck, Store, Warehouse, Loader2, ArrowRight, Mail, Phone, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { BusinessSectorCheckboxes } from "@/components/BusinessSectorCheckboxes";
import { CityMultiSelect } from "@/components/CityMultiSelect";
import { GEORGIAN_BANKS, normalizeIban, isValidGeIban } from "@/lib/banks";
import { cn } from "@/lib/utils";

export default function Auth({ mode }) {
  const isRegister = mode === "register";
  const { login, register, verifyOtp, resendOtp, requestPhoneOtp, verifyPhoneOtp, completeStaffPasswordReset } = useAuth();
  const { t } = useI18n();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [role, setRole] = useState("retailer");
  const [agreed, setAgreed] = useState(false);
  const [verifyEmail, setVerifyEmail] = useState(null);
  const [code, setCode] = useState("");
  const [verifying, setVerifying] = useState(false);
  const [mustChangePassword, setMustChangePassword] = useState(false);
  const [phoneOtpRequested, setPhoneOtpRequested] = useState(false);
  const [phoneOtpPhone, setPhoneOtpPhone] = useState("");
  const [phoneOtpCode, setPhoneOtpCode] = useState("");
  const [phoneOtpDeadline, setPhoneOtpDeadline] = useState(null);
  const [phoneOtpRemaining, setPhoneOtpRemaining] = useState(0);
  const [phoneOtpLoading, setPhoneOtpLoading] = useState(false);
  const [phoneVerified, setPhoneVerified] = useState(false);
  const [phoneVerificationToken, setPhoneVerificationToken] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [form, setForm] = useState({ email: "", password: "", name: "", business_name: "", address: "", city: "", cities: [], phone: "", category: "", category_ids: [], business_sectors: [], identification_number: "", vat_registered: null, establishment_type: "grocery", establishment_type_other: "", card_name: "", card_number: "", card_expiry: "", bank_name: "", iban: "" });

  useEffect(() => {
    if (!phoneOtpDeadline) return undefined;
    const updateRemaining = () => setPhoneOtpRemaining(Math.max(0, Math.ceil((phoneOtpDeadline - Date.now()) / 1000)));
    updateRemaining();
    const timer = window.setInterval(updateRemaining, 1000);
    return () => window.clearInterval(timer);
  }, [phoneOtpDeadline]);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const clearPhoneVerification = () => {
    setPhoneOtpRequested(false);
    setPhoneOtpPhone("");
    setPhoneOtpCode("");
    setPhoneOtpDeadline(null);
    setPhoneOtpRemaining(0);
    setPhoneVerified(false);
    setPhoneVerificationToken("");
  };

  const setPhone = (event) => {
    setForm((current) => ({ ...current, phone: event.target.value }));
    clearPhoneVerification();
  };

  const sendPhoneCode = async () => {
    const phone = form.phone.replace(/[\s()-]/g, "");
    if (!/^\+9955\d{8}$/.test(phone)) {
      toast.error(t("auth.phoneFormatInvalid"));
      return;
    }
    setPhoneOtpLoading(true);
    try {
      const result = await requestPhoneOtp(phone);
      setForm((current) => ({ ...current, phone: result.phone }));
      setPhoneOtpPhone(result.phone);
      setPhoneOtpCode("");
      setPhoneOtpRequested(true);
      setPhoneVerified(false);
      setPhoneVerificationToken("");
      setPhoneOtpDeadline(Date.now() + result.expires_in * 1000);
      toast.success(t("auth.phoneOtpSent"));
    } catch (requestError) {
      toast.error(requestErrorMessage(requestError));
    } finally {
      setPhoneOtpLoading(false);
    }
  };

  const confirmPhoneCode = async () => {
    setPhoneOtpLoading(true);
    try {
      const result = await verifyPhoneOtp(phoneOtpPhone, phoneOtpCode);
      setPhoneVerificationToken(result.verification_token);
      setPhoneVerified(true);
      setPhoneOtpDeadline(null);
      setPhoneOtpRemaining(0);
      toast.success(t("auth.phoneOtpVerified"));
    } catch (requestError) {
      toast.error(requestErrorMessage(requestError));
    } finally {
      setPhoneOtpLoading(false);
    }
  };

  const submit = async (e) => {
    e.preventDefault();
    if (isRegister && !agreed) { toast.error(t("auth.mustAgree")); return; }
    if (isRegister && (!phoneVerified || !phoneVerificationToken)) { toast.error(t("auth.phoneOtpRequired")); return; }
    if (isRegister && form.vat_registered === null) { toast.error(t("vat.required")); return; }
    if (isRegister && role === "supplier" && !isValidGeIban(form.iban)) { toast.error("IBAN: GE + 20 სიმბოლო (მაგ. GE29TB1234567890123456)"); return; }
    setLoading(true);
    try {
      if (isRegister) {
        const extra = role === "supplier" ? { card_name: "", card_number: "", card_expiry: "" } : {};
        const res = await register({ ...form, ...extra, role, accept_terms: true, phone_verification_token: phoneVerificationToken });
        if (res.verification_required) {
          setVerifyEmail(res.email);
          toast.success(`${t("verify.sentTo")} ${res.email}`);
        } else {
          toast.success(role === "supplier" ? t("auth.supplierCreated") : t("auth.welcomeMsg"));
          navigate("/");
        }
      } else {
        let user;
        if (mustChangePassword) {
          if (newPassword !== confirmPassword) {
            toast.error(t("auth.passwordMismatch"));
            setLoading(false);
            return;
          }
          user = await completeStaffPasswordReset(form.email, form.password, newPassword);
        } else {
          user = await login(form.email, form.password);
        }
        toast.success(`${t("auth.welcomeBack")}, ${user?.business_name}`);
        navigate("/");
      }
    } catch (err) {
      const detail = err.response?.data?.detail;
      if (detail === "EMAIL_NOT_VERIFIED") {
        setVerifyEmail(form.email);
        toast.message(t("verify.notVerified"));
      } else if (detail?.code === "PASSWORD_RESET_REQUIRED") {
        setMustChangePassword(true);
        setNewPassword("");
        setConfirmPassword("");
      } else {
        toast.error(requestErrorMessage(err));
      }
    } finally {
      setLoading(false);
    }
  };

  const doVerify = async (e) => {
    e.preventDefault();
    setVerifying(true);
    try {
      await verifyOtp(verifyEmail, code);
      toast.success(t("verify.success"));
      navigate("/");
    } catch (err) {
      toast.error(requestErrorMessage(err));
    } finally {
      setVerifying(false);
    }
  };

  const doResend = async () => {
    try { await resendOtp(verifyEmail); toast.success(t("verify.resent")); }
    catch (err) { toast.error(requestErrorMessage(err)); }
  };

  if (verifyEmail) {
    return (
      <div className="grid min-h-screen place-items-center bg-background p-6">
        <div className="w-full max-w-md text-center" data-testid="verify-screen">
          <div className="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-2xl bg-primary/15"><Mail className="h-8 w-8 text-primary" /></div>
          <h1 className="text-2xl font-extrabold tracking-tight">{t("verify.title")}</h1>
          <p className="mt-2 text-sm text-muted-foreground">{t("verify.sentTo")} <span className="font-semibold text-foreground" data-testid="verify-email">{verifyEmail}</span>. {t("verify.instruction")}</p>
          <form onSubmit={doVerify} className="mt-6 space-y-4">
            <Input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))} inputMode="numeric" maxLength={6} placeholder="------" className="h-14 text-center text-2xl font-bold tracking-[0.5em]" data-testid="verify-code-input" />
            <Button type="submit" className="h-11 w-full text-base" disabled={verifying || code.length !== 6} data-testid="verify-submit">
              {verifying ? <Loader2 className="h-5 w-5 animate-spin" /> : <>{t("verify.verifyBtn")} <ArrowRight className="ml-1.5 h-4 w-4" /></>}
            </Button>
          </form>
          <button onClick={doResend} className="mt-4 text-sm font-semibold text-primary hover:underline" data-testid="verify-resend">{t("verify.resend")}</button>
          <button onClick={() => { setVerifyEmail(null); setCode(""); }} className="mt-6 block w-full text-xs text-muted-foreground hover:underline" data-testid="verify-back">← {t("auth.signIn")}</button>
        </div>
      </div>
    );
  }

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
          <p className="mt-2 text-sm text-muted-foreground">{mustChangePassword ? t("auth.temporaryPasswordInstruction") : isRegister ? t("auth.registerSubtitle") : t("auth.signInSubtitle")}</p>

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
                <div className="space-y-2">
                  <div><Label htmlFor="phone">{t("auth.phone")}</Label><Input id="phone" type="tel" required value={form.phone} onChange={setPhone} className="mt-1.5" data-testid="register-phone" placeholder="+995 5XX XXX XXX" /></div>
                  <Button type="button" variant="outline" className="w-full" onClick={sendPhoneCode} disabled={phoneOtpLoading || phoneVerified || phoneOtpRemaining > 0} data-testid="register-phone-send-code">
                    {phoneOtpLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Phone className="h-4 w-4" />}
                    {phoneOtpRequested ? t("auth.phoneOtpResend") : t("auth.phoneOtpSend")}
                  </Button>
                  {phoneOtpRequested && !phoneVerified && (
                    <div className="space-y-2 rounded-lg border border-border p-3">
                      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
                        <Label htmlFor="phone-otp-code">{t("auth.phoneOtpCode")}</Label>
                        <span role="status" data-testid="register-phone-otp-timer">{phoneOtpRemaining > 0
                          ? `${t("auth.phoneOtpExpires")} ${String(Math.floor(phoneOtpRemaining / 60)).padStart(2, "0")}:${String(phoneOtpRemaining % 60).padStart(2, "0")}`
                          : t("auth.phoneOtpExpired")}</span>
                      </div>
                      <Input id="phone-otp-code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={phoneOtpCode} onChange={(event) => setPhoneOtpCode(event.target.value.replace(/\D/g, "").slice(0, 6))} data-testid="register-phone-otp-code" />
                      <Button type="button" className="w-full" onClick={confirmPhoneCode} disabled={phoneOtpLoading || phoneOtpCode.length !== 6 || phoneOtpRemaining === 0} data-testid="register-phone-otp-verify">
                        {phoneOtpLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}{t("auth.phoneOtpVerify")}
                      </Button>
                    </div>
                  )}
                  {phoneVerified && <p className="flex items-center gap-1.5 text-sm font-medium text-emerald-600" role="status" data-testid="register-phone-verified"><CheckCircle2 className="h-4 w-4" />{t("auth.phoneOtpVerified")}</p>}
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div><Label>{t("reg.city")}</Label>
                    <div className="mt-1.5"><CityMultiSelect single value={form.city ? [form.city] : []} onChange={([city]) => setForm((f) => ({ ...f, city: city || "" }))} idPrefix="register-city" placeholder="—" /></div></div>
                  <div><Label htmlFor="idn">{role === "supplier" ? t("reg.idSupplier") : t("reg.identification")}</Label><Input id="idn" required value={form.identification_number} onChange={set("identification_number")} className="mt-1.5" data-testid="register-identification" placeholder="ს/კ" /></div>
                </div>
                {role === "supplier" && (
                  <div><Label>{t("prof.serviceCities")}</Label>
                    <div className="mt-1.5"><CityMultiSelect value={form.cities} onChange={(cities) => setForm((f) => ({ ...f, cities }))} idPrefix="register-cities" /></div></div>
                )}
                <fieldset className="rounded-lg border border-border p-3" data-testid="register-vat">
                  <legend className="px-1 text-sm font-medium">{t("vat.label")} *</legend>
                  <div className="flex gap-6">
                    {[[true, "vat.yes"], [false, "vat.no"]].map(([value, key]) => (
                      <label key={key} className="flex cursor-pointer items-center gap-2 text-sm">
                        <input type="radio" name="vat_registered" required checked={form.vat_registered === value} onChange={() => setForm((f) => ({ ...f, vat_registered: value }))} data-testid={`register-vat-${value ? "yes" : "no"}`} />
                        {t(key)}
                      </label>
                    ))}
                  </div>
                </fieldset>
                {role === "retailer" && (
                  <>
                    <div><Label htmlFor="est">{t("reg.establishmentType")}</Label>
                      <select id="est" value={form.establishment_type} onChange={set("establishment_type")} data-testid="register-establishment" className="mt-1.5 h-10 w-full rounded-md border border-input bg-background px-3 text-sm">
                        {["grocery", "zoo", "household", "laundry", "restaurant_cafe_bar", "hotel_hostel", "office_company", "other"].map((e) => <option key={e} value={e}>{t(`est.${e}`)}</option>)}
                      </select>
                    </div>
                    {form.establishment_type === "other" && (
                      <div>
                        <Label htmlFor="establishment-type-other">{t("reg.establishmentTypeOther")}</Label>
                        <Input id="establishment-type-other" value={form.establishment_type_other} onChange={set("establishment_type_other")} required data-testid="register-establishment-other" />
                      </div>
                    )}
                    <div className="rounded-lg border border-border p-3">
                      <p className="mb-2 text-sm font-semibold">{t("reg.cardSection")}</p>
                      <div className="space-y-2">
                        <Input value={form.card_name} onChange={set("card_name")} placeholder={t("reg.cardName")} data-testid="register-card-name" />
                        <Input value={form.card_number} onChange={set("card_number")} placeholder={t("reg.cardNumber")} data-testid="register-card-number" />
                        <div className="grid grid-cols-2 gap-2">
                          <Input value={form.card_expiry} onChange={set("card_expiry")} placeholder={t("reg.expiry")} data-testid="register-card-expiry" />
                          <Input placeholder={t("reg.cvc")} data-testid="register-card-cvc" />
                        </div>
                        <p className="text-[11px] text-muted-foreground">{t("reg.saveCard")}</p>
                      </div>
                    </div>
                  </>
                )}
                {role === "supplier" && (
                  <>
                    <BusinessSectorCheckboxes value={form.business_sectors} onChange={(sectors) => setForm((f) => ({ ...f, business_sectors: sectors }))} idPrefix="reg-sector" />
                    <div className="rounded-lg border border-border p-3">
                      <p className="mb-2 text-sm font-semibold">{t("reg.bankSection")}</p>
                      <div className="space-y-2">
                        <select value={form.bank_name} onChange={set("bank_name")} className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm" data-testid="register-bank-name">
                          <option value="">{t("reg.bankName")}</option>
                          {GEORGIAN_BANKS.map((b) => <option key={b} value={b}>{b}</option>)}
                        </select>
                        <Input value={form.iban} onChange={(e) => setForm((f) => ({ ...f, iban: normalizeIban(e.target.value) }))} placeholder={t("reg.iban")} maxLength={22} data-testid="register-iban" />
                      </div>
                    </div>
                  </>
                )}
              </>
            )}
            <div><Label htmlFor="email">{t("auth.email")}</Label><Input id="email" type="email" required value={form.email} onChange={set("email")} className="mt-1.5" data-testid="auth-email" placeholder="you@business.com" /></div>
            <div><Label htmlFor="password">{t("auth.password")}</Label><Input id="password" type="password" required value={form.password} onChange={set("password")} className="mt-1.5" data-testid="auth-password" placeholder="••••••••" /></div>
            {mustChangePassword && (
              <>
                <div><Label htmlFor="new-password">{t("auth.newPassword")}</Label><Input id="new-password" type="password" required minLength={8} maxLength={72} value={newPassword} onChange={(event) => setNewPassword(event.target.value)} className="mt-1.5" data-testid="staff-new-password" /></div>
                <div><Label htmlFor="confirm-password">{t("auth.confirmPassword")}</Label><Input id="confirm-password" type="password" required minLength={8} maxLength={72} value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} className="mt-1.5" data-testid="staff-confirm-password" /></div>
              </>
            )}
            {isRegister && (
              <label className="flex items-start gap-2.5 text-sm" data-testid="register-terms-label">
                <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} data-testid="register-terms-checkbox" className="mt-0.5 h-4 w-4 shrink-0 rounded border-input accent-primary" />
                <span className="text-muted-foreground">
                  {t("auth.agreePrefix")}
                  <Link to="/terms" target="_blank" className="font-semibold text-primary hover:underline" data-testid="terms-link">{t("auth.terms")}</Link>
                  {t("auth.and")}
                  <Link to="/privacy" target="_blank" className="font-semibold text-primary hover:underline" data-testid="privacy-link">{t("auth.privacy")}</Link>
                </span>
              </label>
            )}
            <Button type="submit" className="h-11 w-full text-base" disabled={loading || (isRegister && (!agreed || !phoneVerified))} data-testid="auth-submit">
              {loading ? <Loader2 className="h-5 w-5 animate-spin" /> : <>{isRegister ? t("auth.createAccount") : t("auth.signIn")} <ArrowRight className="ml-1.5 h-4 w-4" /></>}
            </Button>
          </form>

          {!isRegister && <div className="mt-3 text-right">
            <Link to="/forgot-password" className="text-sm font-semibold text-primary hover:underline" data-testid="forgot-password-link">{t("passwordReset.forgotLink")}</Link>
          </div>}

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
