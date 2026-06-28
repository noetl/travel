# Streaming / async provider turns (perceived-instant UX)

Status: design + cleanest-viable plan (noetl/ai-meta latency track, FIX E)

## Problem

A provider turn in the Muno itinerary-planner blocks the user-facing
response on the synchronous provider call. The chain is fully serial:

```
extract_turn (OpenAI ~0.8s)
  -> call_<provider> (BLOCKING, return_result:true, ~1s external)
  -> normalize_tool_response
  -> render_widget_chat
  -> final_result -> gateway callback (status COMPLETED) -> SSE -> SPA
```

The SPA shows nothing until the entire chain finishes. The provider
HTTP call (~1s of Google Places / Duffel / HotelBeds latency) sits on
the critical path, so a turn that hits a provider feels ~1s+ slower
than a no-provider turn even though the user could have seen a
"Searching Paris…" affordance immediately.

This violates the [callback / hook rule](../../../../agents/rules/execution-model.md):
"a block must not hold a worker slot waiting for an external operation."
The provider call is exactly such an external operation.

## Goal

Return the user-facing response **immediately** after `extract_turn`
(a "Searching Paris…" placeholder widget derived from the known
`render_intent`), and **fill the widget** with provider results when
they arrive — instead of blocking the turn on the provider call.

A no-provider turn (pure chat) is unaffected: it already has no
provider hop.

## Shape — optimistic placeholder + deferred fill (two callbacks)

NoETL providers return a JSON document, not a token stream, so
"streaming" here is **optimistic UI**: one early callback with a
placeholder, one later callback with the real widget. Both carry the
same `request_id`; the SPA replaces the placeholder in place.

```
extract_turn
  ├─(parallel leaf, when first_tool != '')─ emit_searching_placeholder
  │      -> gateway /api/internal/callback/async
  │         { request_id, status: "PARTIAL", data: { render: <placeholder widget> } }
  │      (dead-end leaf — like the SLM shadow leaf; nothing reads it)
  │
  └─(response path)─ call_<provider> -> normalize_tool_response
         -> render_widget_chat -> persist_all_atomically
         -> final_result -> gateway callback
            { request_id, status: "COMPLETED", data: { render: <real widget> } }
```

The placeholder leaf forks **in parallel** off `extract_turn` (inclusive
`next`, same mechanism the SLM shadow leaf already uses), so it adds
**zero hops to the response path** — the provider dispatch starts at the
same time. The user sees "Searching Paris…" ~after `extract_turn`
(~1.5s in) instead of after the whole chain (~3–4s in), and the real
results replace it when `final_result` fires.

### Why a parallel leaf, not a pre-provider step

Putting the placeholder callback *before* the provider dispatch would
add a serial hop (~250ms orchestration) and delay the provider start.
Forking it as a parallel dead-end leaf means the placeholder callback
and the provider call race — the placeholder almost always wins (a
single gateway POST vs an external provider round-trip), so it lands
first with no critical-path cost.

## Components to change

### 1. Planner (`repos/travel/playbooks/itinerary-planner.yaml`)

Add a parallel placeholder leaf forked off `extract_turn`'s `next`
(inclusive mode, mirroring the `render_widget_chat` → `shadow_slm_compare`
pattern). The leaf:

- Fires only when `extract_turn.first_tool != ''` (provider turns only).
- Builds a minimal placeholder widget from `extract_turn.render_intent`
  (destination, intent → e.g. `{ widget_type: "searching",
  bot_message: "Searching <dest>…" }`).
- POSTs the gateway async callback with `status: "PARTIAL"`.
- Is a dead-end leaf (no `next` into the response path), so it never
  perturbs the response chain. Gated additionally behind a
  `workload.stream_placeholder.enabled` flag (default off) for a safe
  staged rollout, exactly like `workload.slm_shadow.enabled`.

The leaf is a `kind: python` step that does the gateway POST inline
(same `urllib` callback shape `final_result` already uses, lines
~2040–2090 of the planner).

### 2. Gateway (`repos/gateway`)

The gateway must forward an intermediate `PARTIAL` callback to the
SPA over the existing SSE / subscription channel for that `request_id`,
**without** closing the stream (the `COMPLETED` callback closes it).
Today `/api/internal/callback/async` is built around a single terminal
callback per request. Required change:

- Accept `status: "PARTIAL"` (in addition to `COMPLETED` / `FAILED`).
- On `PARTIAL`, push the payload to the request's SSE subscription and
  keep the subscription open.
- On `COMPLETED` / `FAILED`, push and close as today.

This is additive and flag-guardable on the gateway side.

### 3. SPA (`repos/travel` widget runtime)

The widget runtime renders the `PARTIAL` placeholder widget, then
**replaces** it when the `COMPLETED` payload for the same `request_id`
arrives. A `searching` widget type (spinner + "Searching <dest>…")
is added to the widget contract. Replacement keys on `request_id` +
`thread_path`.

## What ships where / staging

| Increment | Repo | Risk | Flag |
|---|---|---|---|
| `searching` widget type + replace-on-COMPLETED | travel SPA | low | n/a (additive widget) |
| `PARTIAL` callback forwarding | gateway | med | gateway env flag |
| placeholder leaf in planner | travel playbook | low | `workload.stream_placeholder.enabled` (default off) |

All three are independently shippable; the planner leaf is inert until
the gateway forwards `PARTIAL` and the SPA renders `searching`, so they
can land in any order behind their flags.

## Kind validation plan

- Planner leaf: register the candidate planner to kind, drive a turn
  with `stream_placeholder.enabled=true`, assert two callbacks fire
  for the request_id (PARTIAL then COMPLETED) in the event log.
- Gateway: unit-test the `PARTIAL` branch keeps the SSE subscription
  open; kind smoke a two-callback sequence.
- SPA: widget-contract smoke for the `searching` type + replacement.

The provider round-trip itself can't run on kind (WI metadata mint is
GKE-only), so the kind proof is the **two-callback ordering**, not the
real provider payload — the perceived-instant behavior is the ordering,
which kind validates.

## Honest scope

This is the cleanest viable shape: optimistic placeholder + deferred
fill, parallel-leaf so zero response-path cost, flag-gated per
component. It is a 3-repo change (planner + gateway + SPA); the planner
leaf is the only piece on the latency-critical playbook and is inert
behind its flag. Implementing the gateway `PARTIAL` path and the SPA
`searching` widget is the remaining work before the flag can flip.
