# Distro Logistics — PRD

## Original Problem Statement
B2B Distribution & Logistics web app with clean, modern, high-contrast UI. Three roles — Supplier/Distributor, Retailer/Store Owner, Admin. Retailer: catalog with filters, bulk order placement with MOQ + tier pricing, cart & checkout with delivery address/notes, order history with status badges. Supplier: inventory management with tier pricing, order management (accept/reject/advance status), revenue analytics. Admin: user management, approve supplier registration, system analytics. Shared: real-time (polling) notifications, in-app messaging between retailer and supplier, profile settings. Dark/light toggle, responsive, rich mock data (beverages, groceries, snacks).

## Architecture
- Backend: FastAPI + MongoDB (motor). JWT Bearer auth (bcrypt). All routes under /api. Auto-seeds mock data on startup when empty.
- Frontend: Vite + React 19 + Tailwind v4 + shadcn/ui. Context for Auth, Theme, Cart. Recharts for analytics. framer-motion for landing. Polling (5-7s) for notifications/orders/messages.
- Roles enforced via require_role dependency + ownership scoping (retailer sees own orders, supplier sees own products/orders).

## User Personas
- Retailer / Store Owner: browses catalog, places bulk orders, tracks deliveries, messages suppliers.
- Supplier / Distributor: manages inventory & tier pricing, fulfills orders, views sales analytics.
- Admin: approves suppliers, manages users, oversees platform GMV/analytics.

## Core Requirements (static)
- JWT auth with role selection (retailer/supplier self-register; supplier starts pending).
- Tier pricing + MOQ enforced in catalog, cart, and checkout.
- Order lifecycle: Pending → Processing → In Transit → Delivered (+ Cancelled). Supplier advances; retailer may cancel own pending.
- Polling notifications + in-app messaging + profile settings.
- Dark/light theme, responsive web + mobile.

## Implemented (2026-06, v1 MVP)
- Auth: register/login/me, demo quick-login for all 3 roles, seeded accounts.
- Retailer: catalog (category/search/stock filters), bulk order dialog with live tier pricing, cart + checkout (address/window/notes), order history with status timeline + cancel.
- Supplier: dashboard (revenue, daily sales, active orders, 7-day chart, popular items, low-stock alerts), inventory CRUD with tier pricing, order management (accept/reject/advance).
- Admin: platform overview (GMV, orders, fulfillment, fees, counts), user management table with supplier approval queue + suspend/activate.
- Shared: notification bell with unread count (polling), messaging with contacts + quick replies, profile settings.
- Verified: 37/37 backend tests passed; all critical frontend flows passed.

## Backlog
- P1: Atomic/transactional stock decrement with availability check (prevent race/negative stock).
- P1: Supplier-specific catalog view filter for retailers; saved delivery addresses.
- P2: Export orders/analytics CSV; date-range analytics filters.
- P2: Switch FastAPI on_event to lifespan; add login brute-force lockout.
- P2: Order reorder (one-click repeat); email notifications.

## Next Tasks
- Gather user feedback on MVP, then prioritize reorder, saved addresses, and atomic stock handling.
