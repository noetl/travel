#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NOETL_SERVER_URL="${NOETL_SERVER_URL:-http://localhost:8082/api}"
THREAD_ID="${THREAD_ID:-_smoke-$(date +%s)}"

cd "$ROOT_DIR"

echo "Registering itinerary planner if needed..."
noetl --server-url "$NOETL_SERVER_URL" register playbook --file playbooks/itinerary-planner.yaml

echo "Running smoke thread chat_threads/${THREAD_ID}"
EXECUTION_ID="$(
  noetl --server-url "$NOETL_SERVER_URL" exec muno/playbooks/itinerary-planner --runtime distributed \
    --set thread_id="${THREAD_ID}" \
    --set event_type=user_message \
    --set 'event_payload={"text":"Plan a trip to Miami next month for 2 adults"}' \
    --set ai_provider=openai \
    --json | jq -r '.execution_id // .id // empty'
)"

if [[ -z "$EXECUTION_ID" ]]; then
  echo "No execution id returned" >&2
  exit 1
fi

echo "Execution: ${EXECUTION_ID}"
for _ in $(seq 1 60); do
  STATUS_JSON="$(noetl --server-url "$NOETL_SERVER_URL" status "$EXECUTION_ID" --json)"
  STATUS="$(jq -r '.status // empty' <<<"$STATUS_JSON")"
  if [[ "$STATUS" == "completed" || "$STATUS" == "failed" || "$STATUS" == "error" ]]; then
    jq '{execution_id, status, result}' <<<"$STATUS_JSON"
    break
  fi
  sleep 2
done

echo "Smoke complete. Cleanup is handled by mcp/firestore.delete_doc when running the full bridge phase."
