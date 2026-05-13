# Guest Mode

Guest mode is a local-development convenience. Production builds default to the
gateway-session auth flow and should not expose the chat shell before sign-in.

Set `VITE_ALLOW_GUEST=true` in `.env.local` to keep the unauthenticated shell
for fast local iteration. When guest mode is enabled, the NoETL playbook
workload receives no authenticated `user_uid`.

When Auth0 is configured and the user signs in, Muno exchanges the Auth0 ID
token with the NoETL gateway for a `session_token`, stores it in localStorage,
and sends it as `Authorization: Bearer <session_token>` on gateway calls. The
gateway session is the production auth boundary.
