# Muno

Muno is the Adiona trip-planner project home base for NoETL. It contains the trip-planner frontend, widget contract schemas, project-local playbooks, documentation, scripts, and AI working memory.

## Development

```bash
npm install
npm run dev
npm run type-check
npm run build
npm run smoke:widgets
```

Auth0 is required for the production app at `https://travel.mestumre.dev`.
After Auth0 login, Muno exchanges the Auth0 ID token with
`https://gateway.mestumre.dev/api/auth/login` and uses the returned gateway
`session_token` for playbook execution. Local development can preserve guest
mode by setting `VITE_ALLOW_GUEST=true`.

Deployed builds inject the existing `auth0_client` Secret Manager payload plus
the restricted Google Maps widget key at container build time.

For a production-style container build:

```bash
TAG="$(date -u +%Y%m%d-%H%M%S)" ./scripts/build_container.sh
```

## Source of Truth

- Widget schemas: `playbooks/widget-contract/*.schema.json`
- Generated TypeScript types: `src/contracts/widgets.ts`
- Architecture: `docs/architecture/widget-contract.md`
- Auth0 setup: `docs/auth/auth0-setup.md`
- Gateway session pattern: `docs/auth/gateway-session-pattern.md`
- Cloudflare Pages deployment: `docs/deployment/travel-subdomain.md`
- Scoping context: `noetl/ai-meta sync/issues/2026-05-12-trip-planner-app-scoping.md`
