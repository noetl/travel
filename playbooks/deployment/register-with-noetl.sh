#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NOETL_SERVER_URL="${NOETL_SERVER_URL:-http://localhost:8082/api}"

cd "$ROOT_DIR"
echo "Registering muno itinerary planner with ${NOETL_SERVER_URL}"
noetl --server-url "$NOETL_SERVER_URL" register playbook --file playbooks/itinerary-planner.yaml
