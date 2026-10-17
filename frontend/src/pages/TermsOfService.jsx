import { Link } from "react-router-dom";
import { useI18n } from "@/context/I18nContext";
import { Truck, ArrowLeft } from "lucide-react";

const S = ({ title, children }) => (
  <section className="mt-6">
    <h2 className="text-lg font-bold text-foreground">{title}</h2>
    <div className="mt-2 space-y-2 text-sm leading-relaxed text-muted-foreground">{children}</div>
  </section>
);

export default function TermsOfService() {
  const { t } = useI18n();
  return (
    <div className="min-h-screen bg-background" data-testid="terms-page">
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
        <h1 className="text-3xl font-extrabold tracking-tight sm:text-4xl">{t("auth.terms")}</h1>
        <p className="mt-2 font-mono text-xs uppercase tracking-wider text-muted-foreground">{t("legal.lastUpdated")}</p>

        <S title="1. B2B Marketplace Facilitation">
          <p>Distro Logistics operates an online business-to-business marketplace that connects wholesale suppliers/distributors with retailers/buyers. Distro Logistics acts solely as a technology facilitator: it enables product listings, bulk ordering, order tracking, messaging and payment coordination. Distro Logistics is not the seller of record for any product and does not take title to goods. The commercial contract for each order is formed directly between the retailer and the supplier.</p>
        </S>
        <S title="2. Supplier Order Fulfillment Responsibilities">
          <p>Suppliers are solely responsible for the accuracy of their listings (pricing, minimum order quantities, stock and images), for accepting or rejecting orders in a timely manner, and for fulfilling accepted orders — including picking, packing, delivery and the quality and legality of the goods supplied. Suppliers must keep order statuses up to date (Pending → Processing → In Transit → Delivered) and resolve buyer queries in good faith.</p>
        </S>
        <S title="3. Automated Monthly Commission Billing">
          <p>Distro Logistics charges suppliers a platform service commission on orders facilitated through the marketplace, at the rate configured for the platform. Commission on cash/offline orders accrues to the supplier's monthly ledger. On the 1st day of each month an official commission invoice is generated for the prior month. <strong>Each invoice is due within five (5) calendar days of issuance (i.e. on or before the 6th).</strong> Commission already collected at online checkout is marked "paid at checkout" and carries no further balance on the monthly invoice.</p>
        </S>
        <S title="4. Auto-Debit Authorization for Overdue Invoices">
          <p>By saving a payment card and accepting these Terms, suppliers authorize Distro Logistics to automatically debit the saved card for any outstanding commission balance that remains unpaid on its due date, including an automated auto-debit attempt on the 6th of each month. If an invoice remains unpaid after the grace period, the supplier's ability to accept new orders may be temporarily frozen until the balance is reconciled.</p>
        </S>
        <S title="5. Payment Card Data & PCI-DSS Compliance">
          <p>Payment card processing is handled in a PCI-DSS compliant manner. Distro Logistics stores only a secure payment token together with the card brand and last four digits; full card numbers (PAN) and CVC are never stored on our systems. A small temporary authorization hold may be placed when a card is added, to verify authenticity, and is released immediately.</p>
        </S>
        <S title="6. Account Suspension & Freeze">
          <p>Distro Logistics may suspend, freeze or terminate accounts that violate these Terms, carry overdue balances, or misuse the platform. Administrators review supplier registrations before activation.</p>
        </S>
        <S title="7. Acceptance">
          <p>By checking the acceptance box during registration you confirm that you have read, understood and agree to be bound by these Terms of Service and the Privacy Policy. Your acceptance, together with the date, time and originating IP address, is recorded for legal verification. See also our <Link to="/privacy" className="font-semibold text-primary hover:underline">{t("auth.privacy")}</Link>.</p>
        </S>
      </main>
    </div>
  );
}
