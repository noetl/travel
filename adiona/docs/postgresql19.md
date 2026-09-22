# PostgreSQL 19 target

The migration targets **PostgreSQL major version 19**. PostgreSQL 17.11 was an earlier compatibility baseline, not the intended deployment version.

As verified on 2026-09-22 UTC, the official [beta page](https://www.postgresql.org/developer/beta/) and [version 19 documentation](https://www.postgresql.org/docs/19/) identify **19 Beta 3** as the available prerelease. The [project announcement](https://www.postgresql.org/about/news/postgresql-186-1711-1615-1519-1424-and-19-beta-3-released-3365/) dates it to August 13, 2026. The final PostgreSQL 19 release is the intended production baseline; beta validation does not constitute production readiness or approval.

## Reproducible local build

Use PostgreSQL 19 server binaries via `PG_BIN`. If no suitable installed package is available, the included local-test build script downloads the official 19beta3 source archive and verifies its pinned SHA-256:

```bash
./adiona/scripts/build-postgres19.sh
export PG_BIN="$PWD/adiona/.local/postgresql19-build/install/bin"
export PATH="$PG_BIN:$PATH"
./adiona/scripts/start-postgres.sh
```

Source: `https://ftp.postgresql.org/pub/source/v19beta3/postgresql-19beta3.tar.bz2`.

SHA-256: `ea4ad8933121930a58f23c73dc99c26a4184faca26faefa77d15ce0fba7dfe2c` (checked against the official companion `.sha256` file).

Requires a C toolchain, make, curl, tar and shasum; configure reports any additional platform prerequisites. This minimal validation build disables ICU, readline and zlib and does not enable TLS. It is used only for the loopback test database. Production packaging, TLS and locale/collation behavior still require validation using the chosen PostgreSQL 19 distribution. Do not mistake a minimal local build for a production installation recipe.

The startup and shutdown scripts check major version 19. The provisioning playbook rejects other server majors before applying or checking its unchanged migration body. The database lives at ignored `adiona/.local/pgdata-19`; the old PostgreSQL 17 `pgdata` directory is not reused or upgraded. The runtime also checks the actual server version and data directory before initializing NoETL metadata. Both database and full-runtime tests assert the server major version. The prerelease accepts the same version guard as final 19; exact tested versions are recorded in evidence.

## Migration and release policy

No schema migration rewrite or PostgreSQL-19-specific feature is needed for this change. Existing transactional DDL, prepared parameters, JSONB, RLS, identity columns and SERIALIZABLE graph operations are retained. Do not edit the already-versioned migration checksum merely to update a target label.

Before production use, pin the selected final 19.x build and rerun both suites with the actual NoETL runtime, production TLS settings and locale configuration. A future major-version upgrade needs its own explicit data migration/upgrade procedure; these scripts never upgrade an existing cluster in place.

Historical 17.11 evidence remains in `integration-results-postgres17.txt` and `runtime-results-postgres17.json`. Current evidence is in `integration-results.txt` and `runtime-results.json`; the latter records the exact PostgreSQL version for the new run. See [validation](validation.md) for results and remaining limits.
