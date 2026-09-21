# Transaction contracts — implementation required

These are proposed hospitality commands, not built-in NoETL APIs. Each command runs in one PostgreSQL transaction through a stored function or a narrow adapter. The HTTP transport in these playbooks is replaceable by a transactional NoETL tool. Never split a mutation across independently committed workflow steps. The included adapter is a development fixture using an in-memory lock; it does not prove database isolation, durability, or crash recovery.

## Authority and tenancy

Production resolves tenant, property membership, and role from verified identity. Do not trust workload-supplied tenant, role, API URL, principal, or payment outcome. Bind the deployment's adapter URL and credentials server-side. The starter's `X-Demo-Principal` header is deliberately fake and must never be accepted by a production service. Restrict privileged confirmation/expiration playbooks to workers; the demo combines fake staff and worker identities only for testing.

All commands reject unexpected input fields. Identifiers are opaque. The mock uses readable IDs; the proposed SQL uses UUIDs. Clients do not supply totals, taxes, hold deadlines, payment amount, or currency to confirmation. The adapter computes or loads those values from authoritative records.

## Idempotency

Every POST requires `Idempotency-Key`. Scope is tenant + verified principal + operation + key. Persist canonical payload and committed response together with the domain change. Serialize concurrent same-key commands (for example, transaction advisory lock with stable key hashing, followed by request lookup). Same key and same payload returns the original response; same key with different payload returns HTTP 409. Do not overwrite a previous response. Transport retries reuse the key; a new logical request needs a new key. IDs and keys must not contain guest PII.

Replay returns the historical command response, which can differ from current reservation state. A production status endpoint is needed for current state. Confirmation must always reload and check current state, even if an earlier hold response was replayed. Expiration schedules use a fresh invocation key per tick and the same key for retries of that tick.

## Lock protocol for first SQL implementation

Begin with a transaction-scoped per-property advisory lock for ALL inventory mutations, plus row locks and unique constraints. This deliberately serializes a small property's writes and simplifies multi-room evolution. Require the same lock in hold, confirm, cancel, expiry, block/unblock, and room-move commands. Lock order: idempotency key → property advisory lock → reservation/quote records → room-night rows ordered by room_id and night → payment records. Payment ingestion that changes reservation state also follows this protocol. Do not hold locks during provider calls.

Seed every saleable room-night; absence is unavailable. Query using [arrival, departure), lock rows, and require the exact expected count. Do not use an unlocked availability check followed by an insert. Reclaim only expired holds, never confirmed bookings. Release only rows still owned by the reservation being released. Benchmark contention before replacing property serialization with a finer lock protocol.

## Commands

| Endpoint | Allowed caller | Atomic effect and result |
|---|---|---|
| POST /v1/quotes | Staff in first pilot | Validate room, dates, occupancy, rate/restriction configuration; persist a priced snapshot and policy version. Return quote_id, server-calculated total/currency, expiry. Search availability is advisory. |
| POST /v1/holds | Staff in first pilot | Validate quote ownership and expiry; lock all room-nights; reclaim expired owners; create at most one reservation per quote; assign all nights; append reservation.held event; persist response. Return reservation_id, held state, deadline, quoted total. |
| POST /v1/test/payments | Development worker ONLY | Simulate captured/declined outcome, deriving amount/currency from reservation. No provider access. This endpoint has no production equivalent. |
| POST /v1/confirmations | Verified payment worker | Load verified payment and reservation; validate ownership, linkage, captured status, amount, currency, current hold deadline, and night ownership. Confirm and append event atomically, or record needs_refund and release only owned rows. |
| POST /v1/holds/expire | Worker | Process up to limit (1–500) expired holds for authorized property. Release inventory; mark expired, or needs_refund if captured funds exist; append events. Return affected IDs/count. Run again with a fresh key for the next batch. |
| POST /v1/holds/cancel | Staff | Cancel held, unpaid inventory only; release owned nights and append event. Captured payments and confirmed reservations require a separate cancellation/refund policy workflow. |

## Payment boundary

Production must replace simulated payment with create_payment_attempt → provider call → verified webhook/provider reconciliation → record_payment_result → confirm. Persist attempt and stable provider key before the call. Unknown outcomes stay unknown until reconciled; never turn an HTTP timeout into a decline. Verify webhook signatures and merchant identity before committing inbox/payment facts. Deduplicate by provider + merchant account + provider event/transaction ID. Reject contradictory or older state transitions and reconcile with the provider. Request headers or a browser-supplied success flag are not evidence of capture.

Payment facts must be retained even when the reservation is expired/canceled. Late capture enters needs_refund with a durable outbox event. A recovery worker must discover captured attempts with unfinished confirmation; workflow termination must not strand paid bookings indefinitely. This worker and real void/refund calls are future implementation tasks. `needs_refund` means review/compensation is required, not that a refund was executed.

## Outbox boundary

Commit reservation state, audit evidence, command response, and event together. A relay claims rows with leases, invokes the supported NoETL API, and marks accepted delivery; consumers deduplicate by event_id. A crash after acceptance and before acknowledgement can duplicate delivery. Confirmation notifications use a deterministic notification key and a provider capable of deduplication or reconciliation. The starter collects pending events only; it does not deliver messages or update channel availability.

## Pricing and time

Demo pricing is deliberately fictional: USD 100/night + 10% tax, two guests, two rooms, 30-night maximum; quote TTL 5 minutes, hold TTL 10 minutes. Do not use these as ranch settings. Production needs effective-dated rates/taxes, rounding rules, property-local date validation, booking restrictions, policy acceptance evidence, and pricing snapshots. Clock comparisons use database time evaluated after lock acquisition. The mock's injectable clock only supports deterministic tests.

## Error and retry semantics

401 unauthenticated; 403 unauthorized; 404 absent/out-of-scope object; 409 business conflict; 422 malformed command. 429/502/503/504 may retry with the same key and bounded backoff. Other HTTP errors fail the workflow. Network errors are allowed to fail; a caller can replay with the same key after inspecting execution state. Full runtime timeout classification is a remaining integration check. Business result `needs_refund` is a successful command outcome requiring follow-up, not a tool transport error.
