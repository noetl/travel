#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
pg_bin="${PG_BIN:-$(pg_config --bindir)}"
if [[ ! -x "$pg_bin/postgres" ]]; then
  echo 'Set PG_BIN to a PostgreSQL server bin directory (not the libpq client-only directory).' >&2
  exit 1
fi
pg_version="$("$pg_bin/postgres" --version)"
pg_major="$(printf '%s' "$pg_version" | sed -E 's/.*PostgreSQL\) ([0-9]+).*/\1/')"
if [[ "$pg_major" != 19 ]]; then
  echo "PostgreSQL 19 binaries required; found $pg_version. Set PG_BIN to a PostgreSQL 19 bin directory." >&2
  exit 1
fi
mkdir -p "$root/.local"
if "$pg_bin/pg_isready" -h 127.0.0.1 -p 55439 >/dev/null 2>&1; then
  echo 'Port 55439 is already occupied; refusing to reuse an unknown cluster.' >&2
  exit 1
fi
if [[ ! -f "$root/.local/pgdata-19/PG_VERSION" ]]; then
  "$pg_bin/initdb" -D "$root/.local/pgdata-19" -U migration_owner -A trust --no-locale -E UTF8 > "$root/.local/initdb.log"
fi
"$pg_bin/pg_ctl" -D "$root/.local/pgdata-19" -l "$root/.local/postgres.log" -o "-h 127.0.0.1 -p 55439 -k ''" start
if [[ "$("$pg_bin/psql" -X -At -h 127.0.0.1 -p 55439 -U migration_owner -d postgres -c "SELECT count(*) FROM pg_database WHERE datname='adiona_validation'")" == 0 ]]; then
  "$pg_bin/createdb" -h 127.0.0.1 -p 55439 -U migration_owner adiona_validation
fi
printf 'Disposable PostgreSQL ready at 127.0.0.1:55439/adiona_validation\n'
