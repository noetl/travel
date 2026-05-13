# Kind Setup

## Google Maps Widget Key

`MapView` reads the Google Maps JavaScript key from Vite at build time:

```bash
export VITE_GOOGLE_MAPS_KEY="$(gcloud secrets versions access latest \
  --secret=google-maps-widget-key \
  --project=noetl-demo-19700101)"
npm run build
```

The key is intentionally browser-visible and restricted by HTTP referrer. Local
builds without the variable still succeed; the widget renders a map preview
placeholder instead of loading Google Maps.

## Container Smoke

```bash
podman build -t noetl-muno:kind-smoke .
podman run --rm -d --name muno-smoke -p 18080:8080 noetl-muno:kind-smoke
curl -fsS http://localhost:18080/
podman rm -f muno-smoke
```
