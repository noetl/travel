# Feature Specification: Travel playbooks

**Feature Directory**: `specs/001-travel-playbooks`
**Created**: 2026-11-15
**Status**: Draft v1. `profile` is *Specified* and ready to work. Other playbooks are *Draft*, so refine them before starting.
**Input**: "Track changes to the travel NoETL playbooks (starting with profile.yaml) so they can be debugged, updated and deployed safely, mainly by AI agents."

Governed by [the constitution](../../.specify/memory/constitution.md). How-to:
[`docs/playbooks/AGENT-GUIDE.md`](../../docs/playbooks/AGENT-GUIDE.md). Plan: [plan.md](plan.md).
Tasks: [tasks.md](tasks.md).

## Scope

The YAML playbooks in `playbooks/` that the travel SPA (adiona/frontend, served at
travel.mestumre.dev) calls through `gateway.mestumre.dev`:

| Playbook | Catalog path | Status |
| :-- | :-- | :-- |
| `playbooks/profile.yaml` | `muno/playbooks/profile` | *Specified* (below) |
| `playbooks/itinerary-planner.yaml` | `muno/playbooks/itinerary-planner` | *Draft* |
| `playbooks/hotel-cards.yaml` | `muno/playbooks/hotel-cards` | *Draft* |
| `playbooks/flights-details.yaml` | `muno/playbooks/flights-details` | *Draft* |
| `playbooks/trip-intake.yaml` | `muno/playbooks/trip-intake` | *Draft* |
| `playbooks/catalog/**` | `travel/playbooks/catalog/**` | *Draft* |

Out of scope: the Firestore provider itself (`automation/agents/mcp/firestore`, in
noetl/ops) and the gateway/server.

## User Scenarios & Testing *(mandatory)*

### User Story 1: A signed-in traveller sees their saved profile on login (Priority: P1)

The SPA sends `{uid, profile: {}, read_only: true}` at login and renders what comes back.

**Acceptance**:
1. **Given** a stored `users/{uid}`, **when** the login read runs, **then** the trace shows
   `begin_read` RAN, `save_profile` skipped, and the response's `profile` is the stored
   document.
2. **Given** a login read, **then** the document's `updateTime` is unchanged.
3. **Given** no stored document, **then** `found: false`, `profile: {}`, and no document is
   created.

### User Story 2: A traveller's edit is saved without wiping other sections (Priority: P1)

**Acceptance**:
1. **Given** a save of one section, **then** other top-level fields survive (merge on
   top-level keys).
2. **Given** a save, **then** `saved: true` and `found_after_write: true`, and the trace
   shows `save_profile` RAN.

### User Story 3: An agent debugs and redeploys a playbook safely (Priority: P2)

**Acceptance**: following the agent guide, an agent can:
- run a gateway read,
- produce the RAN/skipped trace,
- check `updateTime`,
- validate against the noetl.ai schema,
- pin, register and verify a new version,
- roll back, without touching a real user's profile.

### Edge Cases

- `read_only` arrives as a string (`"false"`): only `true/1/yes/on` count as read-only.
- Blank `uid` is rejected before any Firestore call.
- **The gateway binds `uid` to the session.** A test save writes the signed-in user's
  profile.
- **Local runtime:** profile can't run locally (python steps). Local results aren't
  evidence.

## Requirements *(mandatory)*

### Functional Requirements (profile)

- **PR-001**: A `read_only: true` request MUST NOT call `set_doc` (route
  `validate_input → begin_read → load_profile → build_response`).
- **PR-002**: `load_profile` MUST NOT be a sibling target in `validate_input`'s exclusive
  arc set (`scripts/playbook_skip_topology_test.py`).
- **PR-003**: Saves MUST use `set_doc` with `merge: true` and pass the SPA's profile
  object through unchanged.
- **PR-004**: The response MUST report `saved` and `found_after_write` truthfully
  (`false` on a read).
- **PR-005**: Every registered version MUST pass the noetl.ai schema and the repo guards.

### Key Entities

- **Profile document:** Firestore `shastaratech-noetl-prod` / `(default)` /
  `users/{uid}`, where `uid` is the Auth0 `sub`. It has camelCase fields plus snake_case
  copies.
- **Registered version:** catalog path, version, `catalog_id`, content sha256.

## Current state (2026-11-15)

- **Prod:** `muno/playbooks/profile` **v7**, catalog id `736128634880000113`, registered
  2026-10-12T15:56:11Z, sha256 `201bcee08206391d…`. Byte-identical to `main` (#145).
  Read-only route verified live (execution `380438259395731456`).
- **Open:** noetl/travel#146 (suggestions planned from the stored profile) and #147
  (delete branch). Neither changes the read or save path or the field set.

## Success Criteria *(mandatory)*

- **SC-001**: Every profile deploy has a recorded pin, register and verify (execution id
  plus digest) in its PR.
- **SC-002**: Zero login-time reads with `save_profile` RAN in prod traces.

## Assumptions

- The gateway and the prod catalog are reachable with an operator `gke-prod` session.
- Registration needs an operator role. Agents without one stop and ask.
