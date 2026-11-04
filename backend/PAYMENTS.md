# Local bank card checkout

Checkout supports hosted card payments through TBC Bank and Bank of Georgia
(BOG). Card numbers and security codes are never sent to or stored by this
application. Configure provider credentials only in the backend environment.

## Invoice Transfer Reconciliation

`POST /api/v1/invoices/bank-webhook` reconciles successful bank transfers with
commission invoices. The provider adapter must map its callback/statement row
to this payload shape and sign the exact raw JSON body with HMAC-SHA256 using
`BANK_WEBHOOK_SECRET`, sent as `X-Signature` (hex digest):

```json
{
  "transaction_id": "bank-transaction-unique-id",
  "reference": "the-invoice-payment-reference",
  "amount": "100.00",
  "currency": "GEL",
  "status": "completed"
}
```

The handler requires an existing unique invoice reference, exact amount and
currency equality, and a successful provider status. It records each
`transaction_id` in `invoice_bank_transactions`, protected by a unique index;
replays are idempotent and reuse of a transaction ID with different payment
data is rejected. Production also requires `WEBHOOK_ALLOWED_IPS` to include the
provider's documented CIDRs. The existing `/api/invoices/webhook` endpoint is
a separate generic invoice callback keyed by `invoice_id`, not the bank
transaction reconciliation endpoint.

This endpoint defines the backend contract; a bank-specific adapter is still
needed if the provider sends a different callback format or requires a
server-to-server receipt lookup before the callback can be trusted.

## TBC Bank

Configure:

- `TBC_API_KEY`
- `TBC_CLIENT_ID`
- `TBC_CLIENT_SECRET`
- `APP_BASE_URL` (public HTTPS frontend base URL used for the post-payment return)
- `TBC_CALLBACK_URL` (optional override; defaults to
  `{APP_BASE_URL}/api/payments/tbc/callback`)
- `TBC_API_BASE_URL` (optional; defaults to `https://api.tbcbank.ge/v1`)

Enable the TBC merchant account and set the callback URL in the TBC E-Commerce
merchant dashboard. The callback endpoint must be publicly reachable over
HTTPS and accept TBC's POST containing `PaymentId`. The backend does not trust
that callback as proof of payment: it fetches payment details from TBC and
checks the payment ID, GEL currency, amount, and (when supplied by TBC) the
merchant payment ID before updating the order and payout records.
Allow inbound callback requests from TBC's documented IPs when your hosting
firewall requires an allowlist: `193.104.20.44`, `193.104.20.45`,
`185.52.80.44`, and `185.52.80.45`.

## Bank of Georgia

Configure:

- `BOG_CLIENT_ID`
- `BOG_CLIENT_SECRET`
- `APP_BASE_URL` (public HTTPS frontend base URL)
- `BOG_CALLBACK_URL` (optional override; defaults to
  `{APP_BASE_URL}/api/payments/bog/callback`)
- `BOG_API_BASE_URL` (optional; defaults to `https://api.bog.ge`)
- `BOG_OAUTH_URL` (optional; defaults to BOG's OAuth client-credentials URL)
- `BOG_CALLBACK_PUBLIC_KEY` (optional PEM override for BOG callback key rotation;
  the current official public key is built in)

Register the callback URL in the BOG E-Commerce merchant configuration. It must
be reachable over HTTPS. Callback requests are verified against BOG's
`Callback-Signature` using SHA256withRSA before they are parsed. The callback
then triggers a server-to-server receipt lookup; only the authoritative BOG
receipt is used to update order and payout status. The lookup checks the BOG
order ID, merchant payment ID, GEL currency, and requested amount.

## Checkout and payment status

The authenticated checkout endpoints are:

- `POST /api/payments/tbc/checkout`
- `POST /api/payments/bog/checkout`

Both reserve requested product quantities while the hosted payment is pending
and restore them when the bank reports a failed or expired payment. The
customer returns to `/orders?payment_id=...&payment_gateway=...`; that page
polls the provider-specific authenticated endpoint:

- `GET /api/payments/tbc/{payment_id}`
- `GET /api/payments/bog/{payment_id}`

Both status endpoints are restricted to the retailer who initiated that
payment. Supplier order lists do not expose unpaid bank-checkout orders.

Official provider documentation:

- [TBC E-Commerce API overview](https://developers.tbcbank.ge/docs/checkout-api-overview.md)
- [TBC Create payment](https://developers.tbcbank.ge/docs/checkout-create-checkout-payment.md)
- [TBC Get payment details](https://developers.tbcbank.ge/docs/checkout-get-checkout-payment-details.md)
- [TBC callback URL setup](https://developers.tbcbank.ge/docs/checkout-callback-url)
- [BOG payments overview](https://api.bog.ge/docs/payments/introduction)
- [BOG authentication](https://api.bog.ge/docs/payments/authentication)
- [BOG create order](https://api.bog.ge/docs/payments/standard-process/create-order)
- [BOG payment details](https://api.bog.ge/docs/payments/standard-process/get-payment-details)
- [BOG callback and signature verification](https://api.bog.ge/docs/payments/standard-process/callback)
