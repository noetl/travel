# Auth0 Setup

Muno uses Auth0 as a frontend-only SPA integration. The browser obtains an
access token through `@auth0/auth0-react`; the backend still accepts guest mode
and does not validate JWTs in this round.

## Secret Source

The canonical GCP Secret Manager entry is `auth0_client` in project
`noetl-demo-19700101` / project number `1014428265962`. The secret value is a
JSON payload whose `.data` object contains:

- `domain`
- `client_id`
- `audience`

`client_secret` may exist in the same payload because the Auth0 application is
shared with other automation, but Muno never reads it and never ships it to the
browser.

## Local Development

Guest mode is the default when Auth0 variables are missing:

```bash
npm run dev
```

To run with Auth0 locally, create a private `.env.local`:

```bash
VITE_AUTH0_DOMAIN=<auth0-domain>
VITE_AUTH0_CLIENT_ID=<auth0-spa-client-id>
VITE_AUTH0_AUDIENCE=<auth0-audience>
VITE_NOETL_API_BASE_URL=http://localhost:8082/api
```

Do not commit `.env.local`.

## Deployed Build

The container build script reads the Auth0 payload and injects only browser-safe
fields into the Vite build:

```bash
TAG="$(date -u +%Y%m%d-%H%M%S)" ./scripts/build_container.sh
```

The Auth0 application must allow these URLs:

- Callback: `https://muno.mestumre.dev/callback`
- Logout: `https://muno.mestumre.dev/`
- Web origin: `https://muno.mestumre.dev`
- Local callback: `http://localhost:5173/callback`

## Current Limits

- JWT validation is frontend-only in this round.
- Guest mode remains available as a fallback.
- Firestore rules remain the v1 permissive rules until a later auth-hardening
  round.
