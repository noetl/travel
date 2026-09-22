# Validation evidence

Validation date: 2026-09-22 UTC. Current target validation: local macOS, **PostgreSQL 19beta3**, installed CLI 2.8.3 (not used as the PostgreSQL executor), pinned NoETL source revisions in `sources.md`. The direct adapter uses tools 4.0.1 at the pinned Git revision; the worker uses tools 4.0.1 from its Cargo.lock. No production systems were used.

## Executed

- Direct upstream Rust PostgreSQL tool + actual PostgreSQL: **37 integration checks passed**. This invokes the YAML tool configuration and upstream template engine, not copied SQL against a mock. Checks cover enforced PostgreSQL 19 server version, repeat provisioning and ledger checksum mismatch, source PostgreSQL fixture, user/item CRUD, normalized identity, localized content/fallback, category filters, item/category/media/attribute/bundle relationships, invalid email/negative price, FK rejection, statement rollback on a later translation conflict, quote/SQL-like/template-like input, restrictive deletion, user privacy, direct SQL RLS, self-profile escalation prevention, unmapped identities, identity-subject uniqueness, six concurrent retries converging to one item, nested bundle/category/type cycle rejection, enforced graph isolation, forged ownership FK rejection and invalid translation language.
- Real Rust server → EHDB command bus → Rust worker → PostgreSQL: **21 executions reached their expected terminal states**. Provisioning twice, user creation/replay/deletion, item creation/replay, translation with literal template delimiters, reads, invalid price failure, rollback failure, cross-provider/customer denials, private profile read, catalog read, explicit unlink/delete. See `runtime-results.json` for execution IDs/statuses. All non-reset YAML files registered; execution coverage is the named subset, not every playbook.
- Server parser compatibility patch: PostgreSQL array and HTTP object parameter regression test passed.
- Upstream PostgreSQL tool fix: nine PostgreSQL unit tests plus the real `smallint` minimum/maximum/zero/NULL/integer-neighbor regression passed in both object and array output modes. [PR #104](https://github.com/noetl/tools/pull/104). Its real-database regression was also rerun successfully on PostgreSQL 19beta3.
- Repository-required `npm run type-check`, `npm run build`, `npm run smoke:widgets` passed; 28 widget envelopes. Build retains its existing large-bundle warning.

The documented database/runtime startup and shutdown scripts were exercised using a fresh PostgreSQL 19 cluster in `.local/pgdata-19`. Startup correctly rejects PostgreSQL 17 binaries. A separate negative test executed the provisioning playbook against an empty PostgreSQL 17.11 database on loopback port 55440: it failed with the version error and created neither business nor migration schema. The provisioning playbook itself requires major version 19 before applying or checking migrations. Direct-tool evidence is in `integration-results.txt`; full execution evidence is in `runtime-results.json`.

## Findings resolved during execution

The Rust tool decoded `smallint` as null; explicit JSON row projection works around it, and the upstream PR fixes the decoder. The server stored playbooks at registration but rejected positional arrays at execution; the bundled server patch fixes that parser mismatch. Multi-stage rendering changed request strings containing Jinja delimiters; encoding the bound request between stages preserves them, verified by the full runtime. RLS could not see the just-inserted parent from a sibling CTE; the translation table now has a checked ownership FK allowing atomic creation without bypassing RLS.

Full-runtime builds initially exhausted disk space. Rebuilding without debug information/incremental artifacts succeeded. Early local configuration probes failed before setting the event bus and public callback URL; final validation used correctly isolated loopback addresses and reached terminal states. None of those failed probes are counted as successful tests.

## Limits

The full runtime uses the local server parser patch and server-side orchestration, not an unmodified production deployment or WASM orchestrator. PostgreSQL 19 final-release validation remains outstanding; 19beta3 was the available prerelease. The source build and checksum are documented in `postgresql19.md`. This minimal local build did not enable ICU/TLS. No restart/crash recovery, distributed multi-node load, large-object result externalization, production TLS, real identity provider, bucket operations, payment provider, source MySQL server/data import, or historical row reconciliation was exercised. Source analysis is from repository DDL/procedures/controllers, not an accessible running legacy database. Specialized travel and booking endpoints remain deferred as documented.

Tests use synthetic local trust-authenticated connections. They prove the SQL/RLS principal boundaries for separate non-owner logins, not authorization of a future public gateway. Deployment must bind verified identities to appropriate credentials and restrict playbook/credential administration.

## Historical PostgreSQL 17 baseline

The earlier 17.11 run passed 36 direct-tool checks and 21 full-runtime executions. It is retained as `integration-results-postgres17.txt` and `runtime-results-postgres17.json`; it is not evidence of version 19 execution. The current evidence files were regenerated against 19beta3. The schema migration body/checksum is unchanged; the new major-version guard lives before migration execution.
