# Stripe payments for muno checkouts (TEST MODE)

Status: built on branches, **not registered, not deployed, test mode only**. Owner
decision 2026-11-26: **option A, Adiona is the merchant of record**. The traveller's
card is charged into Adiona's Stripe account; Adiona pays the providers (Duffel
wallet balance, HotelBeds invoice). Price = provider total as-is (markup and fee
are wired but zero). Charged in the offer's currency.

## Pieces

| Repo | Piece |
|---|---|
| noetl/travel (this repo) | `muno/playbooks/payments`, `muno/playbooks/payments-webhook`, Subscription `muno/subscriptions/stripe-test`, the `payments_checkout_mode` planner flag, the `payment_checkout` widget, `checkouts/**` rules |
| adiona/frontend | Payment Element checkout replacing the raw card fields |
| noetl/ops | `automation/agents/mcp/stripe` (the reusable Stripe MCP agent; `payments.yaml` inlines the same client for latency) |
| noetl/gateway + noetl/server | the `stripe_signature` ingress verify type |

Sources: `playbooks/payments/{core,run,settle,webhook}.py` and `*.yaml.in`.
`python3 scripts/build_payments_playbooks.py` renders the two playbooks; never
edit their `code:` blocks by hand (`scripts/payments_build_sync_test.py`).

## Flow: authorize, book, then capture

```
SPA                      payments (run)            Stripe        provider        settle
create_checkout ───────▶ re-price (Duffel offer /
                         HotelBeds checkRate)
                         write checkouts/{id}
                         PI create (manual capture,
                         Idempotency-Key) ─────────▶
◀── client_secret
confirmPayment (Payment Element; card data goes to Stripe only) ─▶ hold placed
finalize ──────────────▶ GET PI: requires_capture?
                         CAS authorized→booking
                         kind: playbook ───────────────────────▶ create_order /
                                                                 book_hotel ──▶ ok:   capture
                                                                                fail: cancel (hold released)
get_status (poll) ◀───────────────────────────────────────────────────────────── confirmed | booking_failed_released
```

The webhook (`payment_intent.amount_capturable_updated`) runs the same `finalize`
as the checkout's own uid, so 3DS redirects and closed tabs still complete.
`finalize` never trusts its caller: it re-reads the PaymentIntent from Stripe, and
only `requires_capture` with the quoted amount, currency and `metadata.checkout_id`
claims the checkout. The claim is a Firestore compare-and-set
(`currentDocument.updateTime`), so two finalizes book once.

## Checkout states (`checkouts/{checkout_id}`)

`checkout_id` = `co_` + sha256(uid + "\n" + client_request_id)[:24], so a retried
create returns the same checkout and the same PaymentIntent.

| state | meaning |
|---|---|
| `created` | document written, PaymentIntent not yet created (a retry finishes it) |
| `requires_payment` | PI exists; waiting for the card |
| `payment_failed` | declined; the traveller can retry on the same PI |
| `authorized` | hold placed (set by the webhook; finalize also claims from earlier states) |
| `booking` | claimed; the provider booking is running |
| `confirmed` | provider confirmed and the hold captured |
| `booking_failed_released` | provider failed; the hold was cancelled, nothing charged |
| `canceled` | the PI was cancelled or expired before a booking |
| `refund_pending` / `refunded` | after `cancel_booking` / `charge.refunded` |
| `needs_review` | capture failed after a booking, amount mismatch, booking stuck >10 min, or a capture without a booking |

`ops_review` records non-terminal flags (`provider_price_drift`, `dispute`).

## Result the SPA parses

The step result with `schema: "muno.payments.v1"` and `final: true` (on the booking
path that is `settle`, otherwise `run`):

```
{ status: "ok" | "error", schema, action, final, error?: code, message?,
  checkout: { checkout_id, state, kind, title, amount_minor, currency,
              display_amount, line_items[], provider_ref?, provider_booking?,
              error?: {code, message} },
  client_secret?   // create_checkout only
}
```

## Secrets and guards (names only, no values anywhere in a repo)

| Name | Where | Holds |
|---|---|---|
| `stripe-api-test` | GSM, project `shastaratech-noetl-prod` | Stripe **test** secret or restricted key: bare string, `{"token": …}` or `{"data": {"token": …}}` |
| `stripe_webhook_test` | NoETL Wallet credential alias | `{"secret": "whsec_…"}` from the test webhook endpoint |
| `REACT_APP_STRIPE_PUBLISHABLE_KEY` | adiona/frontend build env | `pk_test_…` (public by design, still not committed) |
| `duffel-api-test`, `hotelbeds-hotels-test` | GSM (existing) | re-pricing |

Guards fail closed: a key that is not `sk_test_`/`rk_test_` gives `live_key_refused`
before any request; any Stripe object or event with `livemode: true` gives
`livemode_refused`; Duffel must be `duffel_test_`; HotelBeds must be the sandbox
host. Hosts, secret names and pricing are constants in code, not workload (a
workload variable is caller-controlled through the gateway). Every Stripe POST
carries `Idempotency-Key: checkout:{id}:{create|capture|cancel|refund:n}`.

The webhook trusts only the event `id` from the delivered body and re-fetches the
event from Stripe. Because the gateway acks a delivery once forwarded, a failed
webhook run is **not** redelivered by Stripe; the SPA's finalize/get_status calls
converge the checkout anyway.

## Refunds and cancellation (sketch)

- Booking fails after the hold: cancel the PI (no refund needed). Built.
- Capture fails after the provider booked: `needs_review` with the reference; ops
  cancels the provider booking or re-captures. Built (state + flag).
- Traveller cancels a confirmed booking: `cancel_booking` refunds through Stripe
  with `checkout:{id}:refund:1`. **Disabled** (`CANCEL_BOOKING_ENABLED = False`)
  until it also cancels at the provider (Duffel `order_cancellations`, HotelBeds
  `DELETE /bookings/{ref}`) and refunds the provider's refund quote, not the total.
- `charge.refunded` / `charge.dispute.created` are mapped by the webhook.

## Chat path flag

`itinerary-planner` workload `payments_checkout_mode`: `off` (default, the direct
TEST booking is unchanged), `canary` (only `payments_canary_uids`), `on`. When
active, the Book CTA emits a `payment_checkout` widget and requests no provider
tool. `scripts/payments_flag_test.py` checks that `off` is decision-for-decision
identical to `origin/main`.

## Test plan

Unit (no key, no network): `scripts/payments_checkout_test.py`,
`scripts/payments_flag_test.py`, `scripts/payments_build_sync_test.py`, plus the
existing schema, topology, policy and widget guards.

Real test-card run (after the owner's go-live steps below):

| Card | Expect |
|---|---|
| 4242 4242 4242 4242 | hold, booking, capture: `confirmed` |
| 4000 0025 0000 3155 | 3DS challenge, then `confirmed` |
| 4000 0000 0000 9995 | decline: `payment_failed`, retry allowed |
| 4242… with an expired Duffel offer | `booking_failed_released`, PI `canceled` |

## Go-live checklist (TEST mode; owner's actions)

1. Create a Stripe **test-mode** restricted key (PaymentIntents write, Refunds
   write, Events read) and load it: `gcloud secrets create stripe-api-test …` in
   `shastaratech-noetl-prod`, then grant the worker GSA
   `roles/secretmanager.secretAccessor` on it.
2. Add a Stripe **test-mode** webhook endpoint `https://<gateway>/ingress/stripe-test`
   for the six events above, and store its signing secret as the Wallet credential
   `stripe_webhook_test` (`{"secret": "whsec_…"}`).
3. Release the gateway and server with `stripe_signature`, then register
   `playbooks/payments.yaml`, `playbooks/payments-webhook.yaml` and
   `playbooks/subscriptions/stripe-test.yaml` (pin first, per AGENT-GUIDE §4).
4. Build adiona/frontend with `REACT_APP_STRIPE_PUBLISHABLE_KEY=pk_test_…`.
5. Run the cards above with a QA account; trace each execution.

Live keys and real money are out of scope and remain the owner's decision.
