# Muno Subdomain Deployment

This runbook deploys Muno at `https://muno.mestumre.dev` on Cloudflare Pages.
This matches the `adiona/team4` pattern: static Vite assets go to Pages, while
NoETL APIs and workers stay in GKE behind `gateway.mestumre.dev`.

## CI Pipeline

Muno deploys through `.github/workflows/cloudflare-pages.yml`.

Pull requests run:

- `npm ci`
- `npm run type-check`
- `npm run test`
- `npm run smoke:widgets`
- `npm run build`

Pushes to `main` run the same checks, then deploy `dist/` to the Cloudflare
Pages project `muno`.

The repository also includes a Team4-style `wrangler.toml`:

```toml
name = "muno"
pages_build_output_dir = "dist"
```

Manual deploy remains available:

```bash
npm run build
npm run deploy:cf
```

This is the Muno equivalent of the established NoETL GUI playbook path:

```bash
cd repos/ops
noetl run automation/cloudflare/gke_gateway_edge.yaml \
  --runtime local \
  --set action=pages \
  --set gui_repo_dir=../gui \
  --set pages_project_name=noetl-gui \
  --set pages_branch=main \
  --set gui_domain=mestumre.dev \
  --set gateway_public_url=https://gateway.mestumre.dev
```

For Muno we keep the same Wrangler Pages deployment primitive, but the app uses
different Vite variables (`VITE_NOETL_API_BASE_URL`, Auth0 audience, and Maps
key), so the GitHub Actions workflow is the canonical automated path.

## GitHub Secrets and Vars

Required GitHub Actions secrets:

- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`
- `VITE_AUTH0_DOMAIN`
- `VITE_AUTH0_CLIENT_ID`
- `VITE_AUTH0_AUDIENCE`
- `VITE_GOOGLE_MAPS_KEY`

Optional GitHub Actions variable:

- `VITE_NOETL_API_BASE_URL` (defaults to `https://gateway.mestumre.dev/api`)

The Cloudflare token only needs permission to deploy the Pages project. A token
with Cloudflare Pages edit access for the account is sufficient.

If the Cloudflare secrets are not configured, the deploy job prints a notice and
skips the Pages upload while still keeping the build/test checks green.

## Cloudflare Pages Project

Create or connect a Pages project:

- Project name: `muno`
- Production branch: `main`
- Build command: `npm ci && npm run build`
- Output directory: `dist`
- Root directory: repository root
- Node version: `20`

The GitHub Actions workflow can deploy with Wrangler after the Pages project
and API token are configured.

## Custom Domain

After the first Pages deployment, add the custom domain:

- Domain: `muno.mestumre.dev`
- DNS shape: `CNAME muno -> <muno-project>.pages.dev`
- Proxy: enabled

## Build

Cloudflare Pages builds from the repository root:

```bash
npm ci
npm run build
```

The build receives:

- Auth0 SPA fields from `auth0_client`
- Google Maps browser key from `google-maps-widget-key`
- NoETL API base URL for the gateway surface

Only browser-safe values are compiled into the Vite bundle.

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
