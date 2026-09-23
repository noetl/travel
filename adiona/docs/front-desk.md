# Authenticated front desk

The optional React front desk uses the existing Auth0 → gateway session flow. A new scoped application route in the Rust gateway maps the validated gateway user ID to approved, immutable NoETL catalog IDs. Each catalog entry contains the original SQL and a fixed provider-specific PostgreSQL credential alias. Browser requests carry business input only. The gateway never queries the hospitality database.

## Prepare provider scope

1. Apply catalog migration 1 and lodging migration 2 with the separate migrator identity. Create the provider, guest accounts, catalog items and rooms through reviewed administrative playbooks.
2. Create a non-owner PostgreSQL login, grant `adiona_runtime`, and map it to the provider in `adiona.principals`. Follow the [existing credential setup](../README.md#trusted-deployment-setup). Configure SERIALIZABLE and bounded whole-operation retry handling for serialization failures.
3. Store that login in the supported NoETL credential store under a distinct `adiona_provider_*` alias. Never reuse or mutate a shared actor alias per browser request.
4. Generate six public, credential-reference-only playbooks:

```bash
node adiona/scripts/export-front-desk.mjs hotel_one adiona_provider_hotel_one /absolute/new/export-directory
```

The utility changes only metadata and the fixed credential alias; SQL and bound request encoding remain unchanged. It excludes provisioning, reset, user administration and arbitrary catalog writes. The output includes hashes for operator review. Register these files through the **internal operator** catalog endpoint. Record catalog IDs as decimal strings without passing them through JavaScript floating-point numbers.

5. Configure the gateway's `GATEWAY_SCOPED_APPS_FILE` with validated **gateway** user IDs, not Adiona provider IDs or browser-submitted claims. Example synthetic mapping:

```json
{"bindings":{"7":{"availability":"101","hold":"102","reservation":"103","reservations":"104","transition":"105","release_expired":"106"}}}
```

Replace every ID with reviewed registrations and staff accounts. Multiple staff accounts may map to the same provider's catalog entries. Each account has one configured scope in this first version. Enrollment and revocation require an operator config change and gateway restart; do not map an email address or caller-provided provider ID.

## Restricted gateway deployment

The gateway change is a prerequisite. Set `GATEWAY_SCOPED_APPS_FILE`, a random `GATEWAY_SCOPED_RECEIPT_KEY` of at least 32 bytes, and `NOETL_INTERNAL_API_TOKEN` through deployment secret/config mechanisms. Do not commit their values. Auth bypass is rejected. Use an isolated gateway deployment for this application: scoped mode omits generic `/noetl/*`, GraphQL, SSE and push-ingress routes. The existing gateway remains unchanged when scoped configuration is absent.

Only publish the reviewed sign-in/session and `/api/scoped/*` routes through the external ingress. Restrict internal callback and upstream NoETL/catalog/credential endpoints to trusted infrastructure. Configure the existing session backend with verified issuer/audience/signature/expiry checks and correct revocation/cache policy; this feature reuses that validator and does not independently authenticate arbitrary Auth0 tokens. Session-cache revocation behavior is inherited, not strengthened by receipts. Use TLS and a narrowly configured allowed origin. Current scoped forwarding assumes a single control-plane base URL; sharded upstream routing is not covered.

Receipts are signed, valid for one hour, and bound to session, user, action, execution and catalog ID. Polling revalidates the session and current binding. Responses expose only status and business rows from the supported one-step PostgreSQL result shape. SQL errors, workload and raw events are withheld; unknown shapes fail closed. Only register the reviewed one-step playbooks. Use a new catalog ID and update the binding when releasing a workflow revision.

## Frontend

Build a dedicated front-desk instance with:

```text
VITE_FRONT_DESK_ENABLED=true
VITE_GATEWAY_BASE_URL=https://your-restricted-gateway.example
```

Configure the existing Auth0 settings and registered redirect URL for that host. The opt-in build opens the front desk at `/` and `/front-desk`; the ordinary planner build is unchanged. Guest mode never enables staff controls. UI role claims are not authorization: an authenticated but unmapped account receives a gateway denial.

The page provides availability by arrival/departure/guest count; 15-minute holds for an existing guest account ID; recent reservation listing (up to 100); lookup by reservation ID; confirmation/cancellation/check-in/check-out; and explicit expiry release. Confirmation never asserts payment. Listing supports `arrival`, `status`, and `before_id` at the playbook boundary for later filtered/paginated UI work.

The page retains the same idempotency key for an unchanged booking intent and keeps a receipt when polling is interrupted. Use **Check pending operation** before starting another write. **Start a new booking** intentionally resets the key. Receipts/intent state live in the page, not durable browser storage; after a reload or lost submit response, reconcile recent reservations before starting a new booking. Existing reservation IDs and amounts remain decimal strings end to end. Guest discovery/enrollment, multi-property switching and payments remain separate stages.

## Validation

- `node adiona/tests/front-desk.mjs`: real PostgreSQL 19 list/filter/provider/customer boundaries plus deterministic export checks; run after the existing catalog and hospitality suites.
- Frontend contract and server-render tests: scoped request envelopes, polling failures, retry keys, bigint money, guest/linkage gating.
- Gateway unit suite: allowlists, invalid config, receipt forgery/expiry/session/catalog binding and sanitized/fail-closed projection.
- Gateway live test: actual scoped HTTP router → Rust server/EHDB/worker → PostgreSQL. The test injects a synthetic already-validated identity; it does **not** prove a live identity provider or production session backend.

To repeat the live test, start the isolated runtime per the main README, then:

```bash
node adiona/tests/front-desk-runtime.mjs
SCOPED_LIVE_BINDINGS="$PWD/adiona/.local/scoped-live-bindings.json" \
  cargo test --manifest-path /absolute/path/to/gateway/Cargo.toml real_runtime_scoped_actions -- --ignored --nocapture
```

No production deployment, live Auth0 login, browser-to-production round trip, session-revocation rollout, or multi-shard forwarding was performed. The documented server positional-parameter patch remains required for the pinned runtime.
