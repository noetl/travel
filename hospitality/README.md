# NoETL Hospitality Playbooks — Starter 0.1

First booking workflow package for a ResNexus-like system on NoETL. **Development starter, not deployed or production-ready.** The package contains real YAML playbooks plus a local command adapter for exercising their request contracts. PostgreSQL integration is designed but not implemented in this version.

## Included playbooks

| File | Purpose |
|---|---|
| `playbooks/quote_stay.yaml` | Request a persisted price quote with expiry. |
| `playbooks/hold_inventory.yaml` | Allocate room nights through the atomic hold command. |
| `playbooks/simulate_payment.yaml` | Record a fictional captured/declined payment in the local adapter. |
| `playbooks/confirm_reservation.yaml` | Validate payment evidence and confirm, or return `needs_refund` for late capture. |
| `playbooks/release_expired_holds.yaml` | Release a bounded batch of expired holds. |
| `playbooks/cancel_unpaid_hold.yaml` | Release an unpaid hold; excludes confirmed/captured bookings. |
| `playbooks/booking_demo.yaml` | Quote → hold → simulated payment → confirmation. |

The individual playbooks expose each domain operation for integration and recovery. The demo explicitly composes those HTTP commands in one workflow so no unverified child-playbook invocation syntax is required. Every mutation carries an idempotency key. Errors fail the workflow; transient selected HTTP responses retry with the same key. The demo returns the business result, including `needs_refund` when applicable.

## Run locally

Requires Python 3.10+ and PyYAML 6.0.3. From this directory:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
python3 -m local.check_playbooks
```

Start the development adapter in one terminal:

```bash
python3 -m local.adapter
```

In a second terminal with the same environment active:

```bash
python3 -m local.check_playbooks --demo --request-key demo-booking-001
```

Repeat the demo with the same key to exercise replay: it returns the same reservation and does not create another payment. A new key for the same dates/room conflicts while the first booking owns those nights. Restarting the adapter clears all state. The standalone playbooks require IDs returned by preceding commands; replace their `REPLACE_WITH_...` values before use.

**The local runner is a small HTTP contract harness, not a NoETL runtime or replacement engine.** It evaluates only the paths, policies, and linear steps used here. It checks that these YAML requests work against the fixture; it does not prove NoETL scheduling, expression evaluation, retries, or recovery behavior.

## Configuration and synthetic data

- Adapter binds to loopback only (`127.0.0.1:8099`). No live network service is provisioned.
- `ranch-demo` and `room-1`/`room-2` are fictitious identifiers.
- USD 100/night plus 10% tax is test data, **not actual ranch pricing or tax advice**.
- Arrival/departure default to October 2–4, 2027. Checkout does not consume that night's inventory.
- Quotes last 5 minutes; holds last 10 minutes in the fixture.
- `request_key` identifies one logical request; use a fresh key for a new operation and preserve it on retries.
- The demo accepts fake identities in `X-Demo-Principal`. Anyone with access can impersonate them. Never expose this adapter publicly or connect it to real data.

## NoETL integration status

YAML structure is based on `noetl.io/v2` examples at an immutable upstream commit. HTTP requests use `json`, `headers`, and `timeout_seconds` from the inspected Rust HTTP tool. Body capture uses `output.data.data`, following that tool's response envelope, via `tool.spec.policy.rules` and `ctx` values.

No NoETL CLI/server/worker or PostgreSQL server was available in the preparation environment. **No playbook has been registered or executed in a real NoETL runtime, and the SQL draft has not been applied.** The deployed NoETL version must be checked before registration. See `docs/sources.md` for exact source revisions and the remaining compatibility checks.

Before running against a real NoETL deployment:

1. Pin the actual Gateway/server/worker/tools versions. Validate these YAML files with that release's supported validator/catalog registration interface.
2. Deploy the development adapter only inside an isolated test network. `127.0.0.1` in a worker container points to that container, not the operator's laptop. Set a fixed worker-reachable `api_base` as trusted deployment configuration. Do not allow public callers to choose it.
3. Register the seven playbooks under `hospitality/v0_1/...` using the installed release's catalog interface. Use the workload in `examples/demo-workload.json`, adjusted for the test adapter address.
4. Execute `booking_demo`, repeat with the same key, then try overlapping inventory under different keys. Verify output envelope, `ctx` assignments, fail/retry policies, terminal result, and restart behavior on the actual runtime.
5. Implement the PostgreSQL command adapter/functions and run the same scenarios against real concurrent database connections. Replace fake identity, bind property authorization, and enforce RLS and least-privilege database access.
6. Replace payment simulation with durable payment attempts and a verified provider integration. Add webhook inbox, unknown-outcome reconciliation, compensation, and outbox delivery before enabling customer checkout.

## Files and implementation boundaries

- `contracts/openapi.json`: OpenAPI 3.1 request/response contract for the development adapter.
- `contracts/transactions.md`: PostgreSQL transaction boundaries, lock ordering, tenancy, idempotency, payment and outbox requirements.
- `sql/001_schema.draft.sql`: Proposed tables/constraints. No command functions or RLS policies yet; not a production migration.
- `local/adapter.py`: In-memory reference behavior, protected by one process lock. No durability or distributed guarantees.
- `local/check_playbooks.py`: Static checks and loopback HTTP request harness.
- `tests/test_booking.py`: Concurrency, replay, expiry, late-payment, payment linkage, tenancy, and full YAML request-contract tests.
- `docs/validation.md`: Executed checks and limitations.

First scope is one assigned room per reservation, full simulated payment, and internal staff operations. Multi-room/group bookings, fees/promotions, real tax configuration, policy acceptance records, guest identity, direct-public booking authorization, notifications, refunds, channel updates, storage uploads, and production operations remain subsequent work. Pending outbox entries demonstrate the integration boundary; no email, SMS, refund, or channel update is sent.

## Next implementation task

Implement PostgreSQL-backed quote/hold/confirm/expiry commands using the documented lock protocol, then validate these playbooks in the pinned NoETL deployment. This replaces only the command adapter; the playbook workflow contracts remain stable. The HTTP adapter may later become a native transactional tool once its database parameter-binding and transaction guarantees are verified.

## Repository integration

This starter lives under `hospitality/` in `noetl/travel`. Run the commands above from that directory. Every playbook includes an explicit `start` step, following the repository wiki Rust migration guidance. The starter is separate from the existing trip-planner UI and production registration/deployment scripts.
