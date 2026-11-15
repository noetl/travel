# Tasks: Travel playbooks

One task = one PR. Status is updated in the PR that changes it.

## profile (`muno/playbooks/profile`)

- [x] **T-P01**: Read-only login route (`begin_read`) and skip-topology fix.
  Merged in #133 and #145. Registered as v7 (`736128634880000113`), verified 2026-11-15
  (exec `380438259395731456`).
- [ ] **T-P02**: Plan suggestions from the stored profile (#146). Needs adiona/frontend#75 to
  send coordinates. Verify: a read returns `suggestions` for a profile with stored
  `home_lat`/`home_lng`.
- [ ] **T-P03**: Delete branch (#147). Held until the owner's authorization review is
  done. Then adiona/frontend#76.
- [ ] **T-P04**: QA live merge case drives the real path (#144). Needs a dedicated QA
  Auth0 account.

## Other playbooks

- [ ] **T-O01**: Specify itinerary-planner, hotel-cards, flights-details, trip-intake and
  catalog/** (refine their sections of spec.md from *Draft* to *Specified*).

## Tooling

- [x] **T-T01**: Agent guide + skill + spec-kit + schema validator + trace/doc-read
  helpers (this PR).
