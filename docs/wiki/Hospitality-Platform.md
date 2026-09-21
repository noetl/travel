# Hospitality platform on NoETL

Development starter for a property-management and direct-booking system, initially aimed at independent inns and B&Bs. This extends the repository with reservation operations; it is not yet integrated with the existing trip-planner UI or live provider flows.

Source: [hospitality/ on feat/hospitality-playbooks](https://github.com/noetl/travel/tree/feat/hospitality-playbooks/hospitality). The branch is pending review and is not deployed.

## Architecture decision

| Responsibility | Proposed component |
|---|---|
| Reservations, room-night inventory, prices, guests, folios and payment records | PostgreSQL on Google Cloud SQL |
| Workflow orchestration and application endpoints | NoETL playbooks and Gateway |
| Documents, images, import/export archives | Google Cloud Storage |
| Identity | Use the existing Gateway/session authorization boundary; Firebase Authentication is an option for a future separate hospitality client, not a replacement of the travel app's current Auth0 deployment |
| Global distributed writes | Reevaluate Spanner when measured requirements justify migration |
| Client realtime projections | Optional Firestore; PostgreSQL remains the inventory authority |

Every inventory-changing command must commit as one PostgreSQL transaction. NoETL coordinates the surrounding process, including eventual payment-provider integration and notifications. External payment requests are outside the database transaction and require durable attempts, reconciliation, and compensation.

The current implementation calls an isolated HTTP development adapter. The adapter stores state in memory under a process lock; PostgreSQL functions and production authorization are still to be implemented. The transport can later become a native transactional NoETL tool once parameter binding and transaction behavior are verified.

## Playbooks

All files are under `hospitality/playbooks/`; catalog paths start with `hospitality/v0_1/`.

| File | Purpose |
|---|---|
| `quote_stay.yaml` | Persist a price quote and deadline. |
| `hold_inventory.yaml` | Reserve available nights from a quote. |
| `simulate_payment.yaml` | Record a fictional captured/declined outcome; test only. |
| `confirm_reservation.yaml` | Confirm after payment/inventory checks, or return `needs_refund`. |
| `release_expired_holds.yaml` | Release a bounded batch of expired inventory holds. |
| `cancel_unpaid_hold.yaml` | Cancel unpaid held inventory only. |
| `booking_demo.yaml` | Quote → hold → simulated payment → confirmation. |

Each playbook has a literal `start` step, following the [Rust migration guide](python-to-rust-migration). Requests carry idempotency keys. Replays reuse keys; new logical requests use new keys. Repeated confirmation must not create duplicate reservation events. Late capture after expiration must not take inventory from a newer booking.

## Local setup

Clone the repository and check out the feature branch, then:

```bash
cd hospitality
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
python3 -m local.check_playbooks
python3 -m local.adapter
```

In a second terminal, from `hospitality/` with the same environment activated:

```bash
python3 -m local.check_playbooks --demo --request-key demo-booking-001
```

The fixture binds to `127.0.0.1:8099`. It uses fictional rooms, USD 100/night plus 10% test tax, five-minute quotes, and ten-minute holds. These are not property rates or policies. Restart clears state. The fake `X-Demo-Principal` identity is for isolated testing only. No real payment, email, refund, or channel update is performed.

The local harness exercises the YAML requests against the mock; **it is not the NoETL engine**. For a real worker/container, localhost refers to that worker, so configure a fixed worker-reachable test-adapter URL. Bind URL and credentials as trusted configuration and enforce caller/property permissions server-side.

## Validation and readiness

- 24 local tests pass, including concurrent last-room requests, duplicate commands, tenant isolation, expired quotes/holds, late payments, and full demo HTTP request replay.
- Each of the seven YAML files passes package-level structural checks, including explicit `start` presence.
- Actual NoETL registration/execution, PostgreSQL isolation/durability, provider webhooks, outbox delivery, and crash recovery remain unverified.
- `sql/001_schema.draft.sql` proposes tables and constraints; it is not a complete migration and has not been executed.

See the [README](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/hospitality/README.md), [transaction contracts](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/hospitality/contracts/transactions.md), [OpenAPI contract](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/hospitality/contracts/openapi.json), and [validation report](https://github.com/noetl/travel/blob/feat/hospitality-playbooks/hospitality/docs/validation.md).

## Next steps

1. Implement PostgreSQL commands with tenant isolation, consistent locking, persistent idempotency, and an atomic business outbox.
2. Validate against the pinned NoETL deployment, including response-envelope/context handling, failure/retry behavior, and restart recovery.
3. Add durable payment attempts, verified provider events, unknown-outcome reconciliation, and refund/void compensation.
4. Add rate/policy configuration, guest-facing permissions, notifications, housekeeping, and staff UI.
5. Verify channel connectivity and export/migration access before replacing an existing PMS; keep one inventory authority during cutover.

Multi-room/group bookings, promotions, actual tax policies, guest checkout, live payment processing, and channel synchronization are outside this first starter.
