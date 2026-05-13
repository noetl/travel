# Muno Subdomain Deployment

This runbook deploys Muno at `https://muno.mestumre.dev` on GKE.

## Build

The container image is built from the repository root:

```bash
TAG="$(date -u +%Y%m%d-%H%M%S)" \
PLATFORM=linux/amd64 \
VITE_NOETL_API_BASE_URL=https://gateway.mestumre.dev/api \
./scripts/build_container.sh
```

The build script injects:

- Auth0 SPA fields from `auth0_client`
- Google Maps browser key from `google-maps-widget-key`
- NoETL API base URL for the gateway surface

Only browser-safe values are compiled into the Vite bundle.
The default platform is `linux/amd64`, which matches the current GKE Autopilot
nodes.

## GKE

The ops manifests create:

- Namespace `muno`
- Deployment `muno`
- ClusterIP Service `muno`
- GKE ManagedCertificate for `muno.mestumre.dev`
- GKE Ingress that exposes the service and returns the external IP

Apply the manifests from `repos/ops`:

```bash
kubectl apply -f ci/manifests/muno/
kubectl -n muno rollout status deployment/muno
kubectl -n muno get ingress muno
```

## Cloudflare DNS Handoff

After the Ingress has an address, create:

- Type: `A`
- Name: `muno`
- Content: `<GKE_INGRESS_IP>`
- Proxy: enabled after the managed certificate is active

For first certificate issuance, Google-managed certificates generally need the
hostname to resolve directly to the GKE load balancer. If certificate
provisioning stalls while proxied, temporarily set the record to DNS-only until
`kubectl -n muno get managedcertificate muno` shows `Active`, then re-enable the
orange-cloud proxy.

## Auth0

The existing Auth0 SPA application must allow:

- `https://muno.mestumre.dev/callback`
- `https://muno.mestumre.dev/`
- `https://muno.mestumre.dev`

Local development also uses `http://localhost:5173/callback`.

## Verification

```bash
curl -I https://muno.mestumre.dev/
```

In the browser:

1. Open `https://muno.mestumre.dev`.
2. Sign in with Auth0.
3. Confirm the profile chip appears in the sidebar.
4. Run a small trip-planner prompt and confirm a widget renders.
