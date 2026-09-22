#!/usr/bin/env bash
# Reproducible, minimal LOCAL TEST build; not a production PostgreSQL package.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
build_dir="${ADIONA_PG19_BUILD_DIR:-$root/.local/postgresql19-build}"
version=19beta3
expected_sha256=ea4ad8933121930a58f23c73dc99c26a4184faca26faefa77d15ce0fba7dfe2c
mkdir -p "$build_dir"
cd "$build_dir"
archive="postgresql-$version.tar.bz2"
if [[ ! -f "$archive" ]]; then
  curl -fSL "https://ftp.postgresql.org/pub/source/v$version/$archive" -o "$archive"
fi
printf '%s  %s\n' "$expected_sha256" "$archive" | shasum -a 256 -c -
if [[ ! -d "postgresql-$version" ]]; then
  tar -xjf "$archive"
fi
cd "postgresql-$version"
./configure --prefix="$build_dir/install" --without-icu --without-readline --without-zlib
make -j "${ADIONA_BUILD_JOBS:-4}"
make install
printf '\nSet PG_BIN=%s/install/bin\n' "$build_dir"
