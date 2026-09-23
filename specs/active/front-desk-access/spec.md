# Authenticated front desk

Status: implemented and locally verified; ready for review. Scope decisions below follow the existing Auth0/gateway session architecture and the user's PostgreSQL 19 / NoETL Rust requirements.

## Problem and goals
Provider staff need to find available rooms, create a hold for an existing guest, and manage reservations without database credentials or unrestricted NoETL execution access.

## User journeys and acceptance criteria
- FD-01: An unauthenticated, unmapped or bypass-authenticated caller cannot use scoped application routes. Authorization is decided by the gateway's validated session identity, never browser role claims.
- FD-02: A mapped staff member can execute only administrator-configured action/catalog-ID pairs. Request bodies cannot override catalog IDs, credential aliases or execution configuration. Generic proxy/GraphQL routes are absent in restricted application mode.
- FD-03: Polling requires a signed, expiring execution receipt bound to the same session, action and catalog binding. Responses expose only status and projected business rows, not raw events, credentials or SQL errors.
- FD-04: The `/front-desk` page requires gateway sign-in even when guest mode is enabled. It supports date/occupancy search, holds for an existing guest ID, reservation lookup/list and valid lifecycle actions. IDs and amounts remain strings.
- FD-05: Retrying a hold after uncertain delivery retains its idempotency key; changing booking input creates a new key. UI distinguishes pending/failed/empty results and confirmation does not claim payment.
- FD-06: Provider-specific catalog exports retain the tested SQL and bind fixed non-owner PostgreSQL credentials. The gateway never reads the business database.
- FD-07: Run gateway authorization/receipt/projection tests, frontend contract tests and actual PostgreSQL list checks; run repository checks. Record unexecuted production identity/deployment scenarios explicitly.

## Constraints and scope decisions
Use the existing gateway session validator. Configure its issuer/session backend securely; this increment does not replace the identity provider. Gateway user IDs and Adiona provider IDs are distinct: an operator maps the former to immutable catalog IDs whose credentials map to the latter. No shared mutable credential alias switching per request. Restricted routes are opt-in and fail closed on missing configuration or auth bypass. No new Python service, new payment integration or production deployment.

The first page accepts an existing guest account ID; guest discovery/onboarding, seasonal rates, housekeeping, property timezone configuration, payment collection and public self-service are separate scope. Results use one-step PostgresTool event projection and fail closed on unsupported/missing result shape. Operational deployment must restrict internal callback/auth-administration surfaces and upstream NoETL access.

## Plan and verification
1. Gateway: scoped action registry, session-bound receipts, sanitized polling and restricted router mode. Test forged receipts, wrong sessions, removed bindings, malformed/unknown inputs and missing results.
2. Travel: reservation list playbook and scoped export utility. Validate on isolated PostgreSQL 19 with provider/customer boundaries.
3. Front desk: authenticated route, typed client, inventory/holds/reservation actions, state/error handling. Test request shape, polling failure handling, retry keys and precision.
4. Publish separate ready-for-review PRs and wiki pages with their dependencies and evidence.

## Open questions
None blocking this increment. Public production identity configuration and staff enrollment remain operator deployment requirements, not guessed defaults.

## Review artifacts

- [Gateway #51](https://github.com/noetl/gateway/pull/51): restricted action execution and receipts.
- [Travel #129](https://github.com/noetl/travel/pull/129): UI, list playbook, exports and tests.
- Evidence: `adiona/docs/front-desk-validation.json`; production identity/deployment scenarios remain explicitly unexecuted.
