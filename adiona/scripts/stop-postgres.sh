#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
pg_bin="${PG_BIN:-$(pg_config --bindir)}"
"$pg_bin/pg_ctl" -D "$root/.local/pgdata" -m fast stop
