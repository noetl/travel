# Travel regression report

**Suite: PASS** — 4 passed, 0 failed, 2 blocked, 0 errored (19 assertions)

Generated 2026-09-23T16:03:07.149340+00:00

| Case | Status | Assertions | Duration | Note |
|---|---|---|---|---|
| `dispatch_health` | **PASS** | 4 | 0.1 ms | — |
| `frontend_health` | **PASS** | 5 | 0.2 ms | — |
| `hotel_cards_contract` | **PASS** | 6 | 16.2 ms | — |
| `hotel_cards_execution` | **BLOCKED** | 0 | 0.0 ms | workload.server_endpoint is empty. hotel-cards runs on kind: python, which the local runtime skips while still... |
| `profile_merge_detector` | **PASS** | 4 | 0.0 ms | — |
| `profile_merge_live` | **BLOCKED** | 0 | 0.0 ms | workload.gateway_url is empty, so the live merge was not exercised. The detector controls still ran; this half... |

## Blocked (not passed — missing coverage)

- `hotel_cards_execution` — workload.server_endpoint is empty. hotel-cards runs on kind: python, which the local runtime skips while still exiting 0, so it cannot be executed here. The contract tier still ran; this tier is blocked, which is not a pass.
- `profile_merge_live` — workload.gateway_url is empty, so the live merge was not exercised. The detector controls still ran; this half is blocked, which is not a pass.

