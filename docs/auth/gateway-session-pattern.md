# Gateway Session Pattern

Travel mirrors the NoETL GUI gateway authentication flow rather than using an
edge allowlist. The browser first completes Auth0, then exchanges the Auth0 ID
token with the NoETL gateway for a gateway `session_token`. All playbook calls
use that gateway session.

## Source Pattern In `repos/gui`

The canonical implementation lives in
`repos/gui/src/services/gatewayAuth.ts` and
`repos/gui/src/components/GatewayLogin.tsx`.

### Auth0 Authorize URL

The GUI builds the Auth0 URL directly:

- endpoint: `https://<auth0-domain>/authorize`
- response type: `id_token token`
- scope: `openid profile email`
- redirect URI: `VITE_AUTH0_REDIRECT_URI`, defaulting to
  `<window.location.origin>/login`
- audience: not included in the GUI authorize URL

After Auth0 redirects back, `GatewayLogin` reads `id_token` from
`window.location.hash`.

### Gateway Login Exchange

The GUI exchanges the Auth0 ID token with the gateway:

- endpoint: `${gatewayBaseUrl}/api/auth/login`
- method: `POST`
- headers: `Content-Type: application/json`
- body fields:
  - `auth0_token`: the Auth0 ID token
  - `auth0_domain`: the configured Auth0 tenant domain
- response fields used:
  - `session_token`: required
  - `user`: optional user profile stored for display

The gateway base URL comes from `resolveGatewayBaseUrl()`. Public browser
deployments resolve to `https://gateway.<current-domain-root>`; for
`travel.mestumre.dev`, that is `https://gateway.mestumre.dev`.

### Storage

The GUI stores session data in `localStorage`:

- `session_token`: the gateway session token
- `user_info`: JSON-encoded user profile returned by the gateway

Logout closes the SSE connection and removes both keys. It does not call a
gateway logout endpoint.

### Session Validation

The GUI validates an existing session by posting to:

- endpoint: `${gatewayBaseUrl}/api/auth/validate`
- method: `POST`
- body field: `session_token`

If the response contains `valid: true`, the GUI keeps the local session and
updates `user_info` when a `user` object is present.

### Playbook Authorization And Execution

Before execution, the GUI checks access:

- endpoint: `${gatewayBaseUrl}/api/auth/check-access`
- method: `POST`
- body fields:
  - `session_token`
  - `playbook_path`
  - `permission_type`

Authenticated GraphQL calls use:

- endpoint: `${gatewayBaseUrl}/graphql`
- header: `Authorization: Bearer <session_token>`
- 401 handling: clear local auth state and treat the session as expired

The GUI's playbook execution mutation uses the same bearer session header. SSE
callbacks use `session_token` as a query parameter to
`${gatewayBaseUrl}/events`.

## Travel Implementation Decision

`repos/gui` and `repos/travel` are independent frontend repositories, not a
shared npm workspace. Round 9 copies the gateway-session pattern into Travel
and documents the duplication here. A future shared package could reduce drift,
but this round intentionally avoids monorepo restructuring.

Travel keeps the existing Auth0 SPA provider, but it requests ID-token claims
from `@auth0/auth0-react` after login, posts the raw ID token to
`/api/auth/login`, stores the returned gateway session with the same
`localStorage` keys as the GUI, and sends `Authorization: Bearer <session_token>`
on subsequent gateway calls.

Guest mode is disabled by default. Developers can set `VITE_ALLOW_GUEST=true`
for local Vite runs when they need the old unauthenticated shell.
