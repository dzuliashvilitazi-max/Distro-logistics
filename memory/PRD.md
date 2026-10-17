# Distro Logistics — PRD

## Original Problem Statement
B2B Distribution & Logistics web app. Three roles — Supplier/Distributor, Retailer/Store Owner, Admin. Retailer: catalog with filters, bulk orders with MOQ + tier pricing, cart & checkout (payment method), order history. Supplier: inventory with tier pricing, order management, revenue analytics. Admin: user management, approvals, analytics, platform settings. Shared: polling notifications, in-app messaging, profiles. Dark/light, responsive, GEL/₾ currency, EN/KA/RU localization.

## Architecture
- Backend: FastAPI + MongoDB (motor). JWT Bearer auth (bcrypt). All routes under /api. Auto-seeds on startup when empty.
- Frontend: Vite + React 19 + Tailwind v4 + shadcn/ui. Context: Auth, Theme, Cart, I18n. Recharts, framer-motion. Polling (6s) for notifications.
- Roles via require_role + ownership scoping.
- New backend modules: email_service.py (Emergent managed Resend), invoices.py (reportlab PDF), billing logic in server.py.
- Scheduling: .emergent/crons.yml (monthly-invoices on 1st 05:00 UTC; billing-check daily 06:00 Asia/Tbilisi).

## User Personas
- Retailer: browses catalog, places bulk orders, tracks deliveries.
- Supplier: manages inventory, fulfills orders, pays monthly platform commission.
- Admin / finance Super-Admin: approvals, users, platform GMV, and full commission/financial oversight.

## Core Requirements (static)
- JWT auth with role selection; supplier starts pending.
- Tier pricing + MOQ; order lifecycle Pending → Processing → In Transit → Delivered (+ Cancelled).
- GEL/₾ currency; EN/KA/RU localization; dark/light.
- Configurable platform service fee/commission (percent/fixed; payer supplier/retailer/split).
- Commission billing always accrues to the SUPPLIER for every delivered order.

## Implemented
### v1 MVP (2026-06)
- Auth, demo accounts; Retailer catalog/cart/checkout/orders; Supplier dashboard/inventory/orders; Admin overview/users/orders/settings; messaging; notifications; profiles. 37/37 backend tests.
### Payments, currency, localization, registration (2026-06)
- Checkout payment methods (cash/card/consignment) persisted on orders. GEL/₾ everywhere. Full EN/KA/RU i18n. Retailer ID/establishment/card; Supplier ID/bank/IBAN/city; Admin fee settings, categories, city filter.
### Automated Commission Billing & Financial Management (2026-06) — NEW, tested 18/18
- **Accrual**: order advancing to Delivered sets delivered_at + commission_amount (= 5% service_fee); always billed to supplier.
- **Monthly invoices**: do_generate_invoices() builds one invoice per supplier per prior month from delivered, not-yet-invoiced orders; idempotent per (supplier, period). Invoice includes issuer legal name/tax ID/IBAN, supplier tax ID, itemized orders, GEL total, issue/due dates (5-day term), official PDF (reportlab).
- **Email**: invoice + overdue reminder emails via Emergent managed Resend (try_send_email, non-raising). Links point to app only; guardrail gate enforced.
- **Supplier "Invoices & Billing"** (/supplier/invoices): invoice table, status badges, PDF download, frozen banner.
- **Super-Admin "Financials & Commission Tracker"** (/admin/financials): totals (outstanding/accrued/collected); per-supplier ledger (month sales, accrued, outstanding, collected, frozen badge); invoices with green=Paid/yellow=Pending/red=Overdue; Mark Paid, Send Reminder, PDF, Generate Invoices Now.
- **Mark-as-paid** reconciliation → recomputes/clears supplier freeze.
- **Account freeze**: overdue invoice freezes supplier — retailers cannot place orders to them (403) and the supplier cannot advance/accept orders (403) until marked paid.
- **Crons**: generate-invoices (monthly) + billing-check (daily: mark overdue, freeze, email reminders). Bearer WEBHOOK_CRON_SECRET, 401 without.
- **Admin issuer settings** in Admin Settings (legal name, tax ID, IBAN).

### Real Card Payments & Split (2026-06) — SANDBOX gateway, tested 17/17
- **Constraint**: Stripe does not operate in Georgia (claimable sandbox returned `country_not_supported`), so a self-contained sandbox gateway (`backend/payments.py`) was built — real Luhn/expiry/CVC validation, 1 GEL auth-hold on add-card, token-only storage (brand+last4, no PAN/CVC). Swappable to TBC Bank later. Clearly labeled sandbox in UI. No real money.
- **Card on file** (`/api/payments/cards` add/get/delete) for retailers & suppliers via reusable `CardForm.jsx` (Profile + Supplier Invoices). Test cards: 4242…=ok, 4000000000000002=decline-on-add, 4000000000000341=decline-on-charge.
- **Online checkout split** (`payment_method:"online"`): charges retailer card, marks order `paid_at_checkout`, computes `supplier_payout = total - commission`, platform keeps commission; writes `payouts` ledger (`GET /api/payments/payouts`).
- **Smart invoicing**: paid-at-checkout orders excluded from monthly invoices & accrued; surfaced as `checkout_collected` in `/api/admin/financials` (shown as "Paid at checkout" per supplier) and rolled into collected.
- **Auto-debit on the 6th** (`do_auto_debit`, cron `/api/cron/auto-debit`, admin `/api/admin/auto-debit/run`): charges supplier saved card for due/overdue invoices → marks paid + unfreezes. Freeze still enforced on frozen suppliers at order placement & status change.
- Cron added to `.emergent/crons.yml` (auto-debit, 6th 07:00 UTC). 3 crons total.

### Terms of Service & Privacy acceptance (2026-06)
- Public `/terms` and `/privacy` pages (localized headings; legal body in EN) covering B2B facilitation, supplier fulfillment, monthly commission 5-day due date, auto-debit authorization, and PCI-DSS. Linked from the landing footer and the registration form.
- Registration requires a mandatory "I agree to the Terms of Service and Privacy Policy" checkbox with clickable links; Create account is disabled until checked (backend also rejects with 400 if `accept_terms` is not true).
- Consent audit recorded at signup: `terms_accepted`, `terms_accepted_at` (UTC), `terms_accepted_ip` (first X-Forwarded-For hop), `terms_version` on the user, plus an immutable record in the `terms_acceptances` collection (user_id, email, role, version, timestamp, ip, user_agent).

## Endpoints (billing)
- GET /api/invoices (supplier own / admin all) · GET /api/invoices/{id}/pdf
- PUT /api/admin/invoices/{id}/paid · POST /api/admin/invoices/{id}/remind · POST /api/admin/invoices/generate
- GET /api/admin/financials
- POST /api/cron/generate-invoices · POST /api/cron/billing-check (Bearer WEBHOOK_CRON_SECRET)

## Backlog
- P1: Reject ad-hoc generation for current (open) month in admin generate endpoint.
- P2: Admin audit log + rate-limit on reminder sends.
- P2: Extract billing section from server.py into billing.py (server.py ~788 lines).
- P2: Atomic/transactional stock decrement; saved delivery addresses; CSV export.
- P2: Explicit CORS origins + credentials for prod.

## Notes
- Demo billing state: Metro=Paid, Apex=Pending, SnackNation=Overdue+Frozen, Coastal=none.
- No real payment processor; card fields are data/UI only (no vaulting).
