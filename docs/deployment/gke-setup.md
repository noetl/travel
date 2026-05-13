# GKE Setup

## Muno Frontend

Muno's browser UI is deployed to Cloudflare Pages, not GKE. See
[Travel Subdomain](./travel-subdomain.md). GKE remains the runtime for NoETL APIs,
workers, and storage.

## Auth0 Build Values

GKE builds read the existing `auth0_client` Secret Manager JSON payload. The
frontend uses only `.data.domain` and `.data.client_id`. Never inject
`.data.client_secret` into a Vite build. Do not inject an Auth0 audience for the
Travel SPA; the gateway-session flow mirrors the NoETL GUI and exchanges the
Auth0 ID token with `gateway.mestumre.dev`.

## Google Maps Widget Key

GKE/Cloudflare builds should inject the restricted browser key before the Vite
build:

```bash
export VITE_GOOGLE_MAPS_KEY="$(gcloud secrets versions access latest \
  --secret=google-maps-widget-key \
  --project=noetl-demo-19700101)"
npm run build
```

The key is scoped for browser use with HTTP referrer restrictions covering the
Muno deployment domains. Do not ship an unrestricted server API key into the
frontend bundle.

If the key is not present, `MapView` degrades to a static coordinate preview so
the rest of the trip-planner widgets remain usable.
