# Auth0 Setup

Muno uses Auth0 as a frontend-only SPA integration, then mirrors the NoETL GUI
gateway-session pattern. After Auth0 signs the user in, the browser obtains the
Auth0 ID token and exchanges it with `gateway.mestumre.dev/api/auth/login` for a
NoETL gateway `session_token`. Subsequent playbook execution calls carry that
gateway session with `Authorization: Bearer <session_token>`.

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

Production guest mode is disabled by default. For local development, set
`VITE_ALLOW_GUEST=true` to keep the old unauthenticated shell:

```bash
VITE_ALLOW_GUEST=true
npm run dev
```

Travel falls back to the same public Auth0 SPA domain and client id used by the
NoETL GUI, so a missing Pages env value does not strand the sign-in pane. To
override those defaults locally, create a private `.env.local`:

```bash
VITE_AUTH0_DOMAIN=<auth0-domain-override>
VITE_AUTH0_CLIENT_ID=<auth0-spa-client-id-override>
VITE_AUTH0_AUDIENCE=<auth0-audience>
VITE_NOETL_API_BASE_URL=http://localhost:8082/api
VITE_GATEWAY_BASE_URL=https://gateway.mestumre.dev
```

Do not commit `.env.local`.

## Deployed Build

The container build script reads the Auth0 payload and injects only browser-safe
fields into the Vite build:

```bash
TAG="$(date -u +%Y%m%d-%H%M%S)" ./scripts/build_container.sh
```

The Auth0 application must allow these URLs:

- Callback: `https://travel.mestumre.dev/callback`
- Logout: `https://travel.mestumre.dev/`
- Web origin: `https://travel.mestumre.dev`
- Local callback: `http://localhost:5173/callback`

## Gateway Exchange

The gateway exchange follows the same pattern documented in
[`gateway-session-pattern.md`](./gateway-session-pattern.md):

1. Auth0 SPA login completes in the browser.
2. Muno reads the Auth0 `id_token` directly from the `/callback#...` URL hash,
   matching the NoETL GUI flow.
3. Muno posts `{ auth0_token, auth0_domain }` to
   `https://gateway.mestumre.dev/api/auth/login`.
4. The gateway validates the token through the existing Auth0 login playbook and
   returns `session_token` plus optional user info.
5. Muno stores `session_token` and `user_info` in localStorage, matching the GUI.
6. Authenticated playbook calls use the gateway session. A 401 clears local
   session state and returns the user to the sign-in flow.

## Current Limits

- Gateway session validation now gates production playbook execution.
- Guest mode is local-dev only via `VITE_ALLOW_GUEST=true`.
- Firestore rules remain the v1 permissive rules until a later auth-hardening
  round.
