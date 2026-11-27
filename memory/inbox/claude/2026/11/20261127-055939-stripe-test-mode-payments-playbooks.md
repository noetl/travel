# Stripe test-mode payments playbooks
- Timestamp: 2026-11-27T05:59:39Z
- Author: claude
- Tags: payments,stripe,checkout,test-mode
- Kind: claude

## Summary
Added muno/playbooks/payments (create_checkout/finalize/get_status/cancel_booking), payments-webhook, Subscription muno/subscriptions/stripe-test (verify stripe_signature), the payments_checkout_mode planner flag (default off) and the payment_checkout widget. Option A merchant of record; authorize->book->capture; generated from playbooks/payments/ by scripts/build_payments_playbooks.py. Not registered; needs GSM stripe-api-test + Wallet stripe_webhook_test + gateway/server stripe_signature first. See docs/architecture/payments-stripe.md.

## Actions
-

## Related
-
