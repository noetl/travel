#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
pg_bin="${PG_BIN:-$(pg_config --bindir)}"
pg_version="$("$pg_bin/postgres" --version)"
pg_major="$(printf '%s' "$pg_version" | sed -E 's/.*PostgreSQL\) ([0-9]+).*/\1/')"
if [[ "$pg_major" != 19 ]]; then
  echo "PostgreSQL 19 binaries required; found $pg_version. Set PG_BIN to a PostgreSQL 19 bin directory." >&2
  exit 1
fi
"$pg_bin/pg_ctl" -D "$root/.local/pgdata-19" -m fast stop
