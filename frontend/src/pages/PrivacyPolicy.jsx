import { Link } from "react-router-dom";
import { useI18n } from "@/context/I18nContext";
import { Truck, ArrowLeft } from "lucide-react";

const S = ({ title, children }) => (
  <section className="mt-6">
    <h2 className="text-lg font-bold text-foreground">{title}</h2>
    <div className="mt-2 space-y-2 text-sm leading-relaxed text-muted-foreground">{children}</div>
  </section>
);

export default function PrivacyPolicy() {
  const { t } = useI18n();
  return (
    <div className="min-h-screen bg-background" data-testid="privacy-page">
      <header className="sticky top-0 z-10 border-b border-border bg-background/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-3">
          <Link to="/" className="flex items-center gap-2.5" data-testid="legal-home-link">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary"><Truck className="h-5 w-5 text-primary-foreground" /></div>
            <p className="text-base font-extrabold tracking-tight">Distro<span className="text-primary">Logistics</span></p>
          </Link>
          <Link to="/" className="flex items-center gap-1.5 text-sm font-medium text-muted-foreground hover:text-primary" data-testid="legal-back-link"><ArrowLeft className="h-4 w-4" /> {t("legal.backHome")}</Link>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-10">
        <h1 className="text-3xl font-extrabold tracking-tight sm:text-4xl">{t("auth.privacy")}</h1>
        <p className="mt-2 font-mono text-xs uppercase tracking-wider text-muted-foreground">{t("legal.lastUpdated")}</p>

        <S title="1. Information We Collect">
          <p>We collect the information you provide when registering and using the platform: contact name, business name, email, phone, address and city, tax/identification number, establishment type, and — for suppliers — bank name and IBAN used for payouts. We also collect operational data such as orders, invoices, messages and notifications generated through your use of the marketplace.</p>
        </S>
        <S title="2. Payment & Card Data (PCI-DSS)">
          <p>Payment cards are handled in a PCI-DSS compliant manner. We store only a secure payment token together with the card brand and last four digits. We never store full card numbers (PAN) or CVC codes. Card authentication uses a temporary authorization hold that is released immediately after verification.</p>
        </S>
        <S title="3. How We Use Your Information">
          <p>We use your information to operate the marketplace: to facilitate orders between retailers and suppliers, process payments and commission billing, generate invoices, send notifications and reminders, provide support, prevent fraud, and comply with legal obligations.</p>
        </S>
        <S title="4. Commission Billing & Auto-Debit Data">
          <p>For suppliers we maintain a commission ledger, monthly invoices and payout records. Where you have authorized auto-debit, we use your saved payment token to collect outstanding commission balances on their due date. Invoice, payment and auto-debit events are logged for accounting and legal purposes.</p>
        </S>
        <S title="5. Data Sharing">
          <p>Order-related information is shared between the transacting retailer and supplier as needed to fulfil an order (e.g. business name, tax ID, delivery address). We share data with payment processors strictly to process payments, and with authorities where required by law. We do not sell your personal data.</p>
        </S>
        <S title="6. Consent & Retention Records">
          <p>When you accept our Terms of Service and this Privacy Policy at registration, we record the exact timestamp, the originating IP address and your user/account identifier as proof of consent for legal verification. We retain account, transaction and consent records for as long as your account is active and as required by applicable law.</p>
        </S>
        <S title="7. Your Rights & Contact">
          <p>You may access or update your profile information at any time from your account settings, and request correction or deletion subject to legal retention requirements. For privacy questions, contact the platform administrator. See also our <Link to="/terms" className="font-semibold text-primary hover:underline">{t("auth.terms")}</Link>.</p>
        </S>
      </main>
    </div>
  );
}
