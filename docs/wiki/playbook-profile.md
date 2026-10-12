# Playbook: profile

The operator playbook for user profiles: where they live, how they are read and
written, and what to do when one is wrong. The executable workflow is
[`playbooks/profile.yaml`](https://github.com/noetl/travel/blob/main/playbooks/profile.yaml) (`muno/playbooks/profile`);
this page is the procedure around it. Source of truth in the repo:
[`docs/runbooks/profile-handling.md`](https://github.com/noetl/travel/blob/main/docs/runbooks/profile-handling.md).

Every claim below was checked against the code on 2026-10-11:
`playbooks/profile.yaml`, the Firestore MCP provider
([`noetl/ops automation/agents/mcp/firestore.yaml`](https://github.com/noetl/ops/blob/main/automation/agents/mcp/firestore.yaml)),
and adiona/frontend `src/context/ProfileContext.tsx`, `src/services/api.ts`,
`src/types/profile.ts`.

## Where a profile lives

| | |
| :-- | :-- |
| store | Firestore, project `shastaratech-noetl-prod`, database `(default)`, `us-central1` |
| document | `users/{uid}` — one document per user, **not** `users/{uid}/profile` |
| `uid` | the Auth0 `sub` claim, e.g. `auth0|…` |
| written by | `muno/playbooks/profile` → `automation/agents/mcp/firestore` `set_doc` |
| read by | the same playbook (`get_doc`), at login and after every save |
| recovery window | **1 hour.** PITR is disabled and `versionRetentionPeriod` is `3600s`; there is no backup schedule. An overwritten profile is gone after that. |

Other data shares the `users/{uid}` prefix but is **not** the profile:
`users/{uid}/trips/{tripId}/events/{eventId}` holds calendar events written by
the itinerary planner ([data-model.md](https://github.com/noetl/travel/blob/main/docs/architecture/data-model.md)). Those
can exist under a uid with no profile document at all.

## The document shape

The SPA's `ProfileState` (`src/types/profile.ts`):

```text
userId, displayName, bio, homeCity,
preferences   { homeAirport, currency, cabin, seat, maxStops, hotelAmenities[], interests[], … }
notifications { priceDropAlerts, bookingReminders, weeklyInspiration, productUpdates }
bookings[]    { id, userId, kind: flight|hotel|car|activity, title, startDate, endDate,
                amount, currency, status: confirmed|pending|completed|cancelled, reference? }
savedTrips[]  { id, userId, title, destination, slug?, savedAt }
activity[]    { id, text, at, kind: booking|search|save|account }   — capped at 50
```

⚠ **Every field is stored twice.** `toPlaybookProfile()` sends the camelCase
object *and* snake_case copies (`display_name`, `home_city`, `saved_trips`,
`preferences.home_airport`, …). `hydrate()` reads camelCase first and falls back
to snake_case. When the two disagree, camelCase wins. Fix data in **both**.

## How the SPA uses the playbook

All calls go through the gateway's `executePlaybook` GraphQL mutation with
`name: "muno/playbooks/profile"` and `variables: { uid, profile, read_only }`.

| when | `profile` | `read_only` | flow |
| :-- | :-- | :-- | :-- |
| login (`ProfileProvider` effect) | `{}` | `true` | `validate_input → load_profile → suggest_pois/skip → build_response` |
| any edit (debounced 500 ms) | the **whole** profile | `false` | `validate_input → save_profile → load_profile → … → build_response` |
| booking / saved trip add or remove | the whole profile, immediately | `false` | same as an edit |
| "reset profile" on the Profile page | `EMPTY_PROFILE` with the same `userId` | `false` | same as an edit |

The response the SPA reads is `build_response`'s result:
`{ ok, uid, saved, read_only, found, found_after_write, profile, suggestions, suggestions_error }`.
`saved: false` on a read is correct. `found_after_write: false` on a **write**
is not, and means the write did not land.

## Write semantics, precisely

`save_profile` calls `set_doc` with `merge: true`. The provider turns that into
a Firestore `PATCH` with `updateMask.fieldPaths` = **the top-level keys of
`data`**. Consequences:

- **Top-level keys merge; everything under a key is replaced.** Saving
  `{preferences: {...}}` rewrites the whole `preferences` map, so nested maps do
  not merge.
- **Arrays are replaced wholesale.** That is how removing a booking or saved
  trip works: the SPA sends the array without it.
- **A top-level key can never be removed** by this playbook, because an omitted
  key is left alone. Stale keys accumulate.
- ⚠ **`merge: true` with an EMPTY `data` replaces the entire document.** The
  provider only adds `updateMask` when `data` is non-empty (`if merge and data:`).
  Without a mask, a `PATCH` is a full overwrite, here with zero fields. The
  provider also coerces any non-object `data` to `{}`, so a profile that reaches
  it as a string has the same effect. Before `read_only` routing (noetl/travel#133),
  the login read sent `profile: {}` down `save_profile`. **On any registered
  version without that routing, every login wipes the profile.** This is
  data loss, contrary to the note in #133 and in `profile_read_only_test.py`.
  The empty-merge case must be fixed in the provider: an empty merge should be a
  no-op.

## Procedures

### 1. Inspect a user's profile (read-only)

The whole-store check, which also validates every profile against the shape above:

```bash
python3 scripts/firestore_travel_validate.py            # human report, exit 1 on FAIL
python3 scripts/firestore_travel_validate.py --json out.json
```

For one document, use a plain GET. Quote the URL, and never write a Firestore
`resource:verb` as `"$var:verb"` in zsh: `:l` is a lowercase modifier, and the
read becomes a `POST` to a collection, i.e. a **document create**.

```bash
UID='auth0|…'
curl -s -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  "https://firestore.googleapis.com/v1/projects/shastaratech-noetl-prod/databases/(default)/documents/users/${UID}"
```

Read `createTime`/`updateTime` alongside `fields`. Here's how to interpret them:

| what you see | meaning |
| :-- | :-- |
| 404 | the user never saved and never logged in on a pre-#133 version |
| document with **no `fields`** | the empty-merge wipe above (or a login on a pre-#133 version) |
| fields present, camel/snake disagree | a partial write from an older client; camelCase is what the SPA shows |

### 2. "My profile is empty after I log in"

1. Inspect the document (procedure 1). No `fields` with a recent `updateTime`
   means it was wiped by an empty-data merge, not lost in transit.
2. Confirm the **registered** playbook has read-only routing. The repo file is
   not proof of what prod runs:
   `noetl --context gke-prod catalog get muno/playbooks/profile`. Check for
   `read_only` in `workload` and the `validate_input.read_only` arc *before*
   the save arc (`mode: exclusive` takes the first match, so reversed arcs make
   every read write again).
3. Inside the 1-hour window, the previous version is readable with a
   `readTime` parameter on the GET. After it, the data is gone; tell the user.

### 3. "My change didn't save"

In a non-production build the SPA logs `[Profile] save response` with the
`executionId`. For that execution:

- `ok: false` + `error` means `validate_input` refused it (blank `uid`, or
  `profile` not an object). Nothing was written.
- `saved: true`, `found_after_write: false` means the write did not land. Check
  the `save_profile` step's provider error.
- `read_only: true` on a save means the flag arrived truthy. Only
  `true/1/yes/on` count; anything else is a write by design.
- An execution stuck at 2 events means the registered playbook has no
  `metadata.version`. See the header of `profile.yaml`.

### 4. "Suggestions are always empty"

This is expected today. `suggest_pois` runs only when the **input** profile has
numeric `home_lat`/`home_lng`, and the SPA never sends coordinates (it stores
`homeCity` only). Even with coordinates, `preferences.interests` holds UI labels
("Food & drink"), not Places types, so the interest filter would drop
everything. `suggestions_error` says which applies. Making this work needs
geocoding `homeCity` and mapping interests to Places types. That's a product
decision, not an incident.

### 5. Change and register the playbook

1. Diff the registered version against the repo first. If they differ, settle
   which is authoritative before editing.
2. Run the guards locally. CI runs them on any `playbooks/**` PR:
   `python scripts/profile_read_only_test.py` (and the rest of `scripts/*_test.py`).
3. Keep `metadata.version`, the read-only arc order, `merge: true`, and
   `return_result: true` on both Firestore hops.
4. Register, then smoke with a **synthetic** uid (`qa-…` or `test-…`), never
   a real user: one write, one `read_only` read, and confirm the read reports
   `found: true, saved: false` and that the document's `updateTime` did not move.
5. Run `scripts/firestore_travel_validate.py` afterwards.

Rollback means re-registering the previous version. Catalog deletes are locked
on prod.

### 6. Delete a user's profile (account deletion / data request)

**There is no product path.** The playbook cannot delete, and the SPA's "reset
profile" only *overwrites* with defaults, so the document survives. Until a
delete flow exists, this is an owner-approved operator action:

1. Get written approval naming the uid.
2. Export the document first (procedure 1 → save the JSON). With PITR off, this
   is the only undo.
3. Delete via the Firestore MCP `delete_doc` tool (`path: users/{uid}`) from a
   one-off execution.
4. `delete_doc` **does not cascade**. List `users/{uid}` subcollections
   (`:listCollectionIds`) and delete `trips/*/events/*` explicitly if the
   request covers them.
5. Re-run procedure 1 and expect a 404.

### 7. Test data hygiene

Use `qa-` / `test-` prefixed uids for every probe. The QA suite already refuses
anything else. Known probe documents under `users/` are reported by the
validator as `test/probe` and can be ignored.

## Known gaps

| gap | where | status |
| :-- | :-- | :-- |
| empty-data merge wipes the document | provider `set_doc` | open, must be fixed in noetl/ops |
| no delete operation (frontend#59 asked for update **and** delete) | `profile.yaml` | open |
| suggestions never run for SPA traffic | `profile.yaml` / SPA | open, product decision |
| `qa/regression/cases/profile-merge.yaml` live mode calls `POST {gateway}/api/profile` with `users/{id}/profile`. Neither the endpoint nor the path exists, so it can only ever report `blocked` | QA suite | open, should call `executePlaybook` against `users/{uid}` |
| stale top-level keys can't be removed | merge semantics | by design; needs a delete-field write if it matters |

## Related

- [Playbook: itinerary-planner](playbook-itinerary-planner) — writes the calendar events that share the `users/{uid}` prefix.
- [Playbook: hotel-cards](playbook-hotel-cards) and [Playbook: flight-planner](playbook-flight-planner) — the bookings that end up in `bookings[]`.
- [Auth and session](auth-and-session) — where the Auth0 `sub` used as `uid` comes from.
- [QA with NoETL playbooks](qa-with-noetl-playbooks) — the `profile-merge` regression case.
