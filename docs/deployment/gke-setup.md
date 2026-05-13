# GKE Setup

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
