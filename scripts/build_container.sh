#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-noetl-demo-19700101}"
IMAGE_REPO="${IMAGE_REPO:-ghcr.io/noetl/muno}"
TAG="${TAG:-$(date -u +%Y%m%d-%H%M%S)}"
NOETL_API_BASE_URL="${VITE_NOETL_API_BASE_URL:-https://gateway.mestumre.dev/api}"
RUNTIME="${CONTAINER_RUNTIME:-podman}"
PLATFORM="${PLATFORM:-linux/amd64}"

tmp="$(mktemp)"
cleanup() {
  rm -f "$tmp"
}
trap cleanup EXIT

gcloud secrets versions access latest --secret=auth0_client --project="$PROJECT_ID" > "$tmp"

AUTH0_DOMAIN="$(jq -r '.data.domain' "$tmp")"
AUTH0_CLIENT_ID="$(jq -r '.data.client_id' "$tmp")"
AUTH0_AUDIENCE="$(jq -r '.data.audience' "$tmp")"
GOOGLE_MAPS_KEY="$(gcloud secrets versions access latest --secret=google-maps-widget-key --project="$PROJECT_ID")"

"$RUNTIME" build \
  --platform "$PLATFORM" \
  --build-arg "VITE_AUTH0_DOMAIN=$AUTH0_DOMAIN" \
  --build-arg "VITE_AUTH0_CLIENT_ID=$AUTH0_CLIENT_ID" \
  --build-arg "VITE_AUTH0_AUDIENCE=$AUTH0_AUDIENCE" \
  --build-arg "VITE_GOOGLE_MAPS_KEY=$GOOGLE_MAPS_KEY" \
  --build-arg "VITE_NOETL_API_BASE_URL=$NOETL_API_BASE_URL" \
  -t "$IMAGE_REPO:$TAG" \
  -t "$IMAGE_REPO:latest" \
  .

echo "$IMAGE_REPO:$TAG"
