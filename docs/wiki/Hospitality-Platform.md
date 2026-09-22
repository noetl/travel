# Open-source hospitality service

The service keeps Adiona's general product/service catalog and adds lodging operations through NoETL YAML and the Rust runtime, targeting PostgreSQL 19. The earlier Python mock was removed; the new reservation workflows execute against real PostgreSQL.

The [catalog migration #125](https://github.com/noetl/travel/pull/125) and [PostgreSQL tool fix #104](https://github.com/noetl/tools/pull/104) are merged. The hospitality increment is merged in [PR #126](https://github.com/noetl/travel/pull/126) and available on [main](https://github.com/noetl/travel/tree/main/adiona). Backend production deployment has not been performed.

## Implemented in the hospitality increment

- Version-2 migration extends existing catalog items/users with individual rooms and reservations.
- Room capacity, active status, flat nightly prices and currency.
- Date availability and exact quotes; PostgreSQL exclusion constraints prevent overlapping active allocations.
- Fifteen-minute holds with permanent provider-scoped idempotency keys and original price/expiry preservation.
- Staff confirmation, cancellation, check-in and checkout with optimistic versions.
- Explicit expiry release; provider ownership and guest read privacy enforced through database RLS.

[Contracts and run instructions](https://github.com/noetl/travel/blob/main/adiona/docs/hospitality.md) explain request shapes, retry rules, credential boundaries and the distinction between confirmation and payment. All seven new playbooks are public in the repository. The schema preserves catalog products and services beyond lodging.

## Validation

The local tests passed 24 direct hospitality checks and 23 full-runtime scenarios (61 executions), plus the existing 37 catalog checks and 21 runtime executions. They run on PostgreSQL 19 Beta 3 using the actual Rust PostgreSQL tool and full Rust server → EHDB → worker execution. They cover concurrent competing holds, retries, rollback, invalid input, expired holds, state/version checks, room closure and cross-provider/guest access boundaries. [Evidence and limits](https://github.com/noetl/travel/blob/main/adiona/docs/validation.md) link to committed results. A dedicated PostgreSQL 19 CI job runs the direct database suites.

Final PostgreSQL 19.x qualification remains pending. The pinned Rust server still requires the included positional-parameter parser patch. No live property database, payment provider or production deployment is connected.

## Next service stages

Verified-identity gateway and front-desk UI; property/timezone configuration; seasonal rates, taxes and fees; reservation audit/outbox; real payments and refunds; housekeeping and maintenance blocks; channel synchronization. Public self-service bookings and multi-room group transactions remain future work. The new dated room model does not claim migration parity for legacy Adiona orders/invoices or specialized tour/car availability.
