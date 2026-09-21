# Validation report — starter 0.1

**Result: 24 local tests passed.** Python 3 with PyYAML 6.0.3 was used. See `validation-output.txt` for the test runner output.

Executed:

```bash
python3 -m unittest discover -s tests -v
```

Coverage includes:

- Twelve concurrent in-memory hold requests for the same room/dates: one allocation, eleven conflicts.
- Same idempotency key replay; changed-payload rejection; repeated confirmation and single confirmation event.
- Repeated quote-to-hold conversion and simulated payment creation without duplicates.
- Adjacent stays, quote expiry, bounded hold expiration, and reclaim without the sweeper.
- Late capture after reallocation: needs_refund; new inventory ownership preserved.
- Captured expired holds retain compensation requirements during sweeps and reclaim.
- Declined/wrong-reservation/wrong-amount payment rejection.
- Unpaid cancellation and refusal to use that path for captured funds.
- Cross-tenant object rejection, staff/worker separation, and rejection of client-supplied tenant/amount.
- All seven YAML files pass package-level structural checks.
- Full demo YAML requests run through an actual loopback HTTP server; replay returns the same confirmed reservation with one simulated payment.

Not executed: NoETL runtime/catalog validation, PostgreSQL DDL or transactional isolation tests, Cloud SQL configuration, provider payment/webhook integration, persistent outbox delivery, multi-process concurrency, process-crash recovery, or production authentication. The tests model intended domain behavior using a single in-memory lock and do not establish distributed booking correctness. The local harness is intentionally limited to this package's constructs.

No external guest messages, payment requests, refunds, channel updates, or production database changes were made.

Repository integration checks also passed: `npm run type-check`, `npm run build`, and `npm run smoke:widgets` (28 widget envelopes). All 24 hospitality tests passed again after adding explicit `start` steps.
