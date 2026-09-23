# Authenticated front desk

This increment provides an opt-in front-desk application for availability, holds, reservation lookup/listing, confirmation/cancellation, check-in/out and expired-hold release. PostgreSQL 19 and NoETL YAML remain the business backend. It is implemented in [travel PR #129](https://github.com/noetl/travel/pull/129) and [gateway PR #51](https://github.com/noetl/gateway/pull/51), both ready for review. It is not enabled in production.

The Rust gateway maps a validated session user to operator-approved catalog IDs. Each provider receives fixed credential-bound copies of the reviewed playbooks; the browser cannot choose a database identity or arbitrary playbook. Signed, session-bound receipts protect result polling, and only business rows are returned. A dedicated restricted gateway omits generic proxy, GraphQL, SSE and push-ingress routes.

The React build requires `VITE_FRONT_DESK_ENABLED=true` and the restricted gateway URL. Guest mode never grants front-desk access. The initial interface uses existing guest account IDs; guest enrollment, payment collection, seasonal rates and multi-property switching remain later work. Confirmation does not assert payment.

[Setup and boundaries](https://github.com/noetl/travel/blob/kadyapam/front-desk-access/adiona/docs/front-desk.md) · [Feature specification](https://github.com/noetl/travel/blob/kadyapam/front-desk-access/specs/active/front-desk-access/spec.md) · [Validation evidence](https://github.com/noetl/travel/blob/kadyapam/front-desk-access/adiona/docs/front-desk-validation.json)

Validation includes seven actual PostgreSQL/export checks, 62 frontend tests, 88 gateway unit tests and a live scoped HTTP test executing seven workflows through the Rust server/EHDB/worker/PostgreSQL stack. The HTTP test injects a synthetic already-validated identity; it does not prove a production Auth0 issuer or session backend. Production identity configuration, ingress restrictions, staff enrollment, TLS and final PostgreSQL 19.x qualification remain deployment requirements.
