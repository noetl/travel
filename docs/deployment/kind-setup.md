# Kind Setup

## Auth0

Auth0 is optional for local kind and Vite runs. If `VITE_AUTH0_DOMAIN` and
`VITE_AUTH0_CLIENT_ID` are missing, Muno runs in guest mode.

To test the sign-in flow locally, create a private `.env.local` with Auth0 SPA
values from the shared `auth0_client` secret and make sure the Auth0 application
allows `http://localhost:5173/callback`.

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

For GKE images, prefer `./scripts/build_container.sh`; it defaults to
`linux/amd64` so images do not accidentally inherit the Mac host architecture.
