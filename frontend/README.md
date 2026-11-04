# frontend (fastapi-vite-shadcn)

React 19 + JavaScript on **Vite**, Tailwind CSS **v4** via `@tailwindcss/vite` (theme tokens live in
`src/index.css` under `@theme`; there is no `tailwind.config.js`/`postcss.config.js`), shadcn/ui (Radix),
react-router-dom, axios, TanStack Query (`QueryClientProvider` mounted in `src/index.js`, client in
`src/lib/queryClient.js`).

Same conventions as the classic `shadcn` (fastapi_react_mongo_shadcn) template: JSX lives in `.js` files (`src/index.js`,
`src/App.js`), the `@/*` alias maps to `src/*`, and the frontend reads
`process.env.REACT_APP_BACKEND_URL` from `frontend/.env` (Vite inlines every `REACT_APP_*` key
at build time via `vite.config.mjs`).

## Scripts

- `yarn start` / `yarn dev` — Vite dev server on port 3000 (supervisor runs `yarn start`)
- `yarn build` — production bundle into `build/`
- `yarn preview` — serve the production bundle locally

Hot reload is Vite HMR; restart the `frontend` supervisor program only after changing `.env`
or `vite.config.mjs`, or after installing dependencies (`yarn add`, never npm).

## Delivery route traffic and driver links

Set `VITE_GOOGLE_MAPS_API_KEY` in the frontend environment and enable the Google Maps JavaScript API
and Directions API (Legacy) to show the live traffic layer and calculate traffic-aware routes. Restrict
the key to the deployed frontend referrers and the required APIs. Without this key or when Google
traffic routing is unavailable, route planning falls back to the existing OpenStreetMap/OSRM route.

Suppliers can schedule and assign saved routes from `/supplier/routes` or the weekly/daily calendar
on `/supplier/drivers`. Each dispatch creates a private, 30-day driver link; generating a new link
rotates the previous one, and deleting the saved route revokes it. Links open the mobile driver
view at `/m/driver-route?token=...` (the older `/driver/routes/:token` path remains supported).
Share links should only be sent to the assigned driver.
Driver profiles include a vehicle plate, active status, and working weekdays; calendar assignment
automatically selects an active driver scheduled for the chosen weekday.

The daily driver calendar can add manual external deliveries and optimize them together with selected
platform orders. Re-optimizing a driver's scheduled day combines its active stops into one route;
external orders retain their external marker and remain excluded from platform financial reporting.

## Store credit and payment tracking

Stores can review distributor balances, payment due dates, invoices, and transaction statements at
`/store/finance`. Distributors configure credit limits and 7-, 14-, or 30-day terms per store and
record cash or bank-transfer payments at `/supplier/finance`. Delivered-order due dates are based on
the saved terms; older orders without saved terms use a 14-day default. Consignment checkout is
checked against a configured credit limit. Confirmed online checkout payments are recorded
automatically, and order invoice PDFs are available after delivery.
Order invoices render in Georgian with an embedded Noto Sans Georgian font, issuer and buyer details,
GEL totals, payment dates, bank information, and signature fields. Supplier profiles can mark VAT
registration; registered suppliers' agreed order totals are treated as VAT-inclusive and the 18% VAT
component is shown without changing the payable total. These platform-generated PDFs are transaction
documents, not electronically registered Revenue Service tax invoices.

The backend runs the idempotent MongoDB data migration in `backend/migrations/store_finance.py` on
application startup. It backfills existing orders with payment balances and payment-ledger entries;
the migration does not require manual SQL changes.

## Store branches, POS sync, pricing, and analytics

Retailers land on `/store` and can manage branch addresses at `/store/branches`. The active branch
is selected in the top bar; checkout, order history, finance, and the price calculator use that
branch, while `/store/analytics` compares all branches. Existing store orders are assigned to the
migrated main branch.

`/store/integrations` creates per-retailer bearer tokens; tokens are stored as hashes and shown only
when created or rotated. Connected POS clients pull delivered purchases from
`GET /api/store/integrations/orders` and push sales batches to
`POST /api/store/integrations/sales`. A sale item must identify a product previously purchased and
delivered to that branch. The order feed returns up to 1,000 records; while `has_more` is true,
request the next page with both `next_updated_since` and `next_id`. Sale IDs are idempotent. These
REST endpoints provide the sync contract; an adapter/job in the POS or ERP is required to call them.

Branch P&L uses synced POS retail revenue, purchase cost matched from delivered order lines, and
manually entered branch operating expenses. Price advice uses a 25% gross-margin baseline unless
at least three other POS-connected retailers provide an anonymized product benchmark; it is an
estimate, not tax/accounting advice. No competitor price is disclosed for fewer than three other
retailers.

Visual edits: the packaged `@emergentbase/visual-edits` plugin tags `.jsx`/`.tsx`; because this
template keeps JSX in `.js`, `vite.config.mjs` stamps the same `x-*` metadata on `src/**/*.js`
before compiling the JSX (dev server only; `DISABLE_VISUAL_EDITS=true` turns it off).
