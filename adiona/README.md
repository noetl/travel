# Adiona → NoETL catalog and users

MySQL is the business-schema source; **PostgreSQL 19 is the target**. This package replaces the Python hospitality mock with NoETL YAML operations for Adiona's general product/service catalog and users. It is a tested local foundation, not a deployed public API. The [hospitality extension](docs/hospitality.md) adds real room inventory and staff-managed reservations.

See [PostgreSQL 19 target and release policy](docs/postgresql19.md). The earlier PostgreSQL 17 results remain historical evidence.

Read [source mapping and differences](docs/migration-map.md), [architecture/access boundaries](docs/architecture.md), [validation](docs/validation.md), [pinned sources](docs/sources.md), and [Rust compatibility](runtime/README.md).

## What is implemented

- Transactional, versioned, repeatable schema provisioning; separate explicit validation-only reset.
- Languages, currencies, user types/profiles/provider identities; no raw OAuth/API token storage.
- Category/type hierarchies and translations, category images, items, bundles, item translations/images/categories, numeric attributes and localized attribute content.
- Natural-key upserts, price update, reads/search, explicit relationship unlinking and restrictive deletes.
- PostgreSQL RLS using the connection's mapped identity; provider ownership, private user profiles, admin-only taxonomy/identity writes.
- Prepared parameters for all caller values. One SQL statement per operation; item and default translation roll back together.

All operation files are in `playbooks/` with catalog paths `adiona/v1/<filename-without-yaml>`. Request shape is `{"request": {...}}`; inspect each playbook's JSON field names. Upserts are full replacements of their listed fields, not partial JSON patches. `item_update` updates only price. Read/delete of a missing or invisible entity returns no rows. Upserts/links return the stable persisted row; SQL validation/authorization failures fail the execution. Output rows are `output.data.rows[].result` at the tool boundary; runtime event envelopes add their own wrappers.

## Hospitality extension

Apply `lodging_provision` after `provision` to add migration 2. Seven additional YAML workflows cover rooms, exact flat-rate quotes, holds, confirmation/cancellation, check-in/out and expiry. See [contracts, setup and remaining service stages](docs/hospitality.md). Run `node adiona/tests/hospitality.mjs` after the catalog integration suite; with the Rust server/worker running, also run `node adiona/tests/hospitality.mjs --runtime`.

## Isolated local PostgreSQL + actual Rust tool

Requires PostgreSQL 19 server binaries (currently tested with 19beta3), Node.js, Rust/Cargo and Git. The test runner links the pinned upstream NoETL Rust tool; it is not a mock and not a replacement workflow engine. These tests reset only the disposable `adiona_validation` database at loopback port 55439.

From the repository root:

```bash
# Use installed PostgreSQL 19 binaries, or build the pinned local-test prerelease:
./adiona/scripts/build-postgres19.sh
export PG_BIN="$PWD/adiona/.local/postgresql19-build/install/bin"
export PATH="$PG_BIN:$PATH"
./adiona/scripts/start-postgres.sh
CARGO_NET_GIT_FETCH_WITH_CLI=true cargo build --locked --manifest-path adiona/tests/rust/Cargo.toml --target-dir adiona/tests/rust/target
node adiona/tests/integration.mjs
```

The startup script refuses an occupied port, requires PostgreSQL 19 binaries and creates a private test cluster under ignored `adiona/.local/pgdata-19`, and binds only to 127.0.0.1. Local trust authentication is for this disposable fixture only. Synthetic users use `example.invalid`; no source data is loaded. Stop it after runtime validation:

```bash
./adiona/scripts/stop-postgres.sh
```

The integration test creates non-superuser `av_*` logins, grants `adiona_runtime`, maps trusted principals and uses separate database connections for access-boundary and concurrency checks. It tests PostgreSQL execution through `PostgresTool::execute`, including upstream template rendering. It does not by itself prove orchestration; use the next section for that.

## Real Rust server + worker validation

The installed CLI's local mode does not support PostgreSQL. Use the distributed Rust stack. The pinned server needs the [included parser patch](runtime/README.md) for positional parameter arrays. No Python service is started. The local setup uses EHDB command/event buses hosted by the Rust worker, with in-process server orchestration (WASM orchestration disabled).

Clone `noetl/server` and `noetl/worker` into a separate source directory; check out the exact revisions in `docs/sources.md`. Then:

```bash
export TRAVEL_ROOT="$PWD"
export NOETL_SOURCE_ROOT=/absolute/path/to/noetl-validation-sources
export NOETL_RUNTIME_TARGET="$NOETL_SOURCE_ROOT/target"
git -C "$NOETL_SOURCE_ROOT/server" apply "$TRAVEL_ROOT/adiona/runtime/0001-postgres-positional-params.patch"
export CARGO_TARGET_DIR="$NOETL_RUNTIME_TARGET"
export CARGO_PROFILE_DEV_DEBUG=0
export CARGO_INCREMENTAL=0
cargo test --manifest-path "$NOETL_SOURCE_ROOT/server/orchestrate-core/Cargo.toml" positional_parameter_tests
cargo build --manifest-path "$NOETL_SOURCE_ROOT/server/Cargo.toml" --no-default-features
cargo build --manifest-path "$NOETL_SOURCE_ROOT/worker/Cargo.toml" --no-default-features
node adiona/scripts/runtime-local.mjs
node adiona/tests/runtime.mjs
node adiona/scripts/runtime-local.mjs stop
```

Run the database/tool integration suite first, because it establishes the synthetic catalog and principals. The runtime startup verifies the actual PostgreSQL data directory matches this package's disposable cluster. It provisions upstream NoETL metadata in that database and stores a random local encryption key only in ignored `.local/runtime.key`. Its disabled internal API authentication is restricted to the loopback validation services and must not be copied to a public deployment. The runtime test registers all non-reset playbooks, assigns only local test credentials, executes workflows via `/api/execute`, waits for terminal status and checks persisted results/rollback. It writes a reproducible execution-ID report to `docs/runtime-results.json`.

## Trusted deployment setup

1. Apply provisioning with an owner credential named `adiona_migrator`, authorized to create the schema and the NOLOGIN group role. Never reuse this credential for public/catalog operations. Do not register `reset` or `source_postgres_fixture` outside validation.
2. Register PostgreSQL credential alias `adiona_actor` using NoETL's supported credential mechanism. Its data fields are `db_host`, `db_port`, `db_name`, `db_user`, `db_password`; actual secret values belong in the encrypted credential store, not YAML, workloads or Git.
3. A database administrator creates each real non-owner login, grants `adiona_runtime`, and adds an entry to `adiona.principals(db_role,user_id,permission)`. Roles are `admin`, `provider`, `customer`. No public account may change these mappings. Set SERIALIZABLE on the actual login for graph operations, and implement bounded whole-operation retries for 40001/40P01. A trusted mapping example (substitute reviewed local identities, never caller input):

```sql
GRANT adiona_runtime TO catalog_provider;
ALTER ROLE catalog_provider IN DATABASE application_database
  SET default_transaction_isolation = 'serializable';
INSERT INTO adiona.principals(db_role,user_id,permission)
VALUES ('catalog_provider', 123, 'provider');
```

4. Register playbooks using the pinned server's `POST /api/catalog/register` with a JSON body containing `content` (the YAML string). Execute with `POST /api/execute`, `{"path":"adiona/v1/item_upsert","payload":{"request":{...}}}`. See `examples/item.json` and `examples/user.json`; use actual provisioned IDs. Register only reviewed operations and pin catalog revisions in the gateway. Keep credential selection and catalog/execution management APIs behind trusted access controls.
5. Connect a real verified-identity gateway before serving multiple users. The example static actor alias models one deployment principal, not a public caller-selected identity. This package intentionally does not wire the existing travel frontend to a shared administrator credential.

PostgreSQL tool fix: [noetl/tools#104](https://github.com/noetl/tools/pull/104). The fix is merged; the direct validation adapter pins that merge revision. JSON projection also keeps the pinned worker compatible. The server parser patch remains a separate runtime requirement.

## Remaining scope

Specialized trip/tour/car availability and pricing response parity, trip/itinerary/order/invoice schema migration, seasonal pricing/taxes/fees, payments/refunds/outbox, public gateway integration, verified account linking, GCS object operations, historical data cleanup/import and production TLS validation are not implemented. The migration map names the source rules and unresolved gaps. No production database, bucket, payment provider or deployment was modified.
