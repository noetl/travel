# RFC: Travel-domain Small Language Model (SLM) to replace OpenAI in the Muno itinerary-planner

- **Status:** Draft (Phase 0 — design only)
- **Owner:** Muno / NoETL travel
- **Tracking umbrella:** noetl/travel#63 (children: #64 dataset, #65 train, #66 serve, #67 shadow-eval, #68 cutover)
- **Related:** noetl/travel#60 (Python→Rust planner migration), noetl/ai-meta#137 (MCP provider auth), noetl/ai-meta#130/#136 (per-hop latency)
- **Scope of this document:** the functional spec the SLM must satisfy, model/serving/integration options with a recommendation, a training-data + evaluation + rollout plan, and the open decisions needed to start Phase 1. **No model is trained, no infra is stood up, and the planner is not modified by this RFC.**

---

## 1. Motivation

The Muno itinerary-planner (`playbooks/itinerary-planner.yaml`) is designed around two LLM passes that today are declared as OpenAI calls:

- **Extraction pass** (`gpt-4o`, JSON mode, `temperature: 0`) — turns a user turn + slot state + recent thread events into a structured decision: which slots changed, which tool to call with which arguments, and what to render.
- **Chat-rendering pass** (`gpt-4o-mini`) — turns the extraction result + tool response + render intent into a short bot message plus one or more validated UI-widget envelopes.

Replacing these two OpenAI calls with a **local, travel-domain SLM** buys us:

1. **Cost** — removes per-turn OpenAI token spend on a high-frequency path.
2. **No external dependency** — removes a third-party network hop and an API-key/secret-rotation surface from the planner's critical path (relevant to noetl/ai-meta#137's auth work).
3. **Latency control** — an in-cluster model lets us own the latency budget directly rather than paying OpenAI RTT on every hop (relevant to the per-hop latency work in noetl/ai-meta#130 / end-to-end planner latency in #136).
4. **Domain specialization** — the task is narrow (travel intent → tool routing → widget spec). A small model fine-tuned on this exact contract can match or beat a general frontier model on *this* task while being orders of magnitude cheaper to run.

This is a **swap, not a rewrite**: the SLM must emit byte-compatible JSON for the two contracts below so it drops into the planner where OpenAI is, behind a flag, with the routing and widget contracts unchanged.

---

## 2. Current-state survey (the functional spec / labeling oracle)

> This section is the load-bearing part of the RFC: it is the exact I/O contract the SLM must reproduce. It was derived by reading `playbooks/itinerary-planner.yaml`, `playbooks/agent/system_prompt_extraction.md`, `playbooks/agent/system_prompt_chat.md`, `playbooks/agent/widget_envelope_examples.md`, and the `playbooks/widget-contract/*.schema.json` set.

### 2.1 Where OpenAI sits in the planner

The planner declares OpenAI at the workload level:

```yaml
# playbooks/itinerary-planner.yaml
workload:
  ai_provider: openai
  llm_extraction_model: gpt-4o
  llm_chat_model: gpt-4o-mini
  openai_secret_path: projects/.../secrets/openai-api-key/versions/1
capabilities: [..., ai:openai, ai:anthropic, ai:vertex-ai, ai:ollama]
keychain:
  - name: openai_token   # GCP Secret Manager → api_key
```

Two workflow steps are the OpenAI roles:

| Step | Model (declared) | Role | Output consumed by |
|---|---|---|---|
| `extract_turn` (line ~159) | `gpt-4o`, JSON mode, temp 0 | Intent + slot extraction + tool selection + args + render intent | the routing arcs (`when: extract_turn.first_tool == '...'`) and `render_widget_chat` |
| `render_widget_chat` (line ~1286) | `gpt-4o-mini` | Bot message + UI widget envelopes | the SPA (validated against `widget-contract/*.schema.json`) |

**Important nuance for implementers (and for the dataset plan):** on the current branch both steps run a **deterministic Python implementation** of these contracts (regex/keyword slot hints + rule-based routing in `extract_turn`; deterministic widget assembly in `render_widget_chat`). The step emits an `llm_contract` object with `fallback_used: true`. The OpenAI *contract* is fully specified by the two `system_prompt_*.md` files and the widget schemas; the deterministic Python is a **working reference baseline and a ready labeling-oracle scaffold**. This is a gift for the SLM project — see §5.

### 2.2 Extraction-pass contract (`extract_turn`)

**System prompt:** `playbooks/agent/system_prompt_extraction.md`.

**Inputs the pass sees:**

- One new user event. `event_type` ∈ `{user_message, user_widget_submit, user_widget_cta_click}`.
  - `user_message`: free-form text in `event_payload.text` (or `.message` / `.label`).
  - `user_widget_submit`: `event_payload.submitted_value` (or `.value`) is authoritative; carries `action_id`.
  - `user_widget_cta_click`: interpret `action_id` (e.g. `pick_offer:off_123`, `book_offer:<id>`, `view_offer:<id>`, `order:<id>`, `add_place:<id>`, `pick_hotel:<id>`).
- The current `slot_state` (loaded from Firestore via `load_slot_state`).
- Recent event log for the thread (for context).
- Runtime constants: `duffel_env: test` (must be preserved in tool requests), `flight_provider`.

**Output (strict JSON, no prose, no code fences):**

```json
{
  "slot_updates": { },
  "tool_requests": [ { "tool": "<tool-id>", "arguments": { } } ],
  "render_intent": { "kind": "<intent>", "missing": ["region","dates","party"] }
}
```

- `slot_updates` — a **partial deep patch** for `slot_state`. Omit unchanged fields. Use `null` only to explicitly clear a value.
- `tool_requests` — array; the runtime dispatches **at most one** per turn, so the most important request is first. `first_tool` / `first_tool_arguments` are derived from `tool_requests[0]`.
- `render_intent.kind` — one of the values in §2.4.

**Slot-state shape** (the schema the model patches; from the prompt + the Python projection):

```json
{
  "region": {"label":"Miami","city_code":"MIA","country_code":"US","kind":"city"},
  "check_in_date": "2026-07-10", "check_out_date": "2026-07-14", "nights": 4,
  "party": {"rooms":1,"adults":2,"children":[{"age":8}]},
  "star_rating_min": 4,
  "budget_min": {"amount":1200,"currency":"USD"},
  "budget_max": {"amount":2400,"currency":"USD"},
  "bed_type": "king", "amenities_required": ["wifi","breakfast"],
  "flight_search_results": ["off_123"], "picked_flight_offer_id": "off_123",
  "hotel_search_results": ["hotel_123"], "picked_hotel_id": "hotel_123",
  "places_seen": ["place_id"], "order_id": "...", "booking_reference": "...",
  "total_results_seen": 54, "total_cost": {"amount":1860,"currency":"USD"}
}
```

**Tool catalog the extractor selects from** (the `tool` string is exact — routing arcs match it verbatim):

| `first_tool` | When | Argument shape (verbatim keys) |
|---|---|---|
| `mcp/google-places.search_text` | New/ambiguous destination, before places seen | `{"query":"Paris","max_results":5}` |
| `mcp/duffel.search_offers` | region+dates+party known, no flight batch | `{"origin":"SFO","destination":"<city_code>","departure_date":"YYYY-MM-DD","adults":N,"cabin_class":"economy"}` |
| `mcp/duffel.create_order` | user confirms an offer (test wallet only) | `{"offer_id":"...","passengers":[...],"duffel_env":"test"}` |
| `mcp/hotelbeds.search_hotels` | hotel intent + region | `{"city":"Paris","city_code":"PAR","check_in":"...","check_out":"...","adults":N,"rooms":N,"children":N,"radius":20}` |
| `mcp/hotelbeds-activities.search_activities` | activities intent + region | `{"destination":"PAR","from":"...","to":"...","adults":N,"language":"en"}` |
| `mcp/hotelbeds-transfers.search_transfers` | transfer intent + region | `{"from_type":"IATA","from_code":"CDG","to_type":"GPS","to_code":"48.8566,2.3522","outbound":"...T10:00:00","adults":N,"children":N,"language":"en"}` |
| `""` (no tool) | missing slots / clarify / summary | — |

> Note on coordinates: transfers need a `to_code` in `lat,lng` order; today this is resolved from a hard-coded known-city geo map (`_city_geo`) for {PAR, MIA, NYC, LON, BOS}. The SLM either learns this mapping for known cities or defers to a deterministic geo lookup post-model (see §3 "hybrid").

### 2.3 Chat-rendering-pass contract (`render_widget_chat`)

**System prompt:** `playbooks/agent/system_prompt_chat.md`. **Examples:** `playbooks/agent/widget_envelope_examples.md`.

**Inputs:** current `slot_state`, the extraction result, the normalized tool response (`normalize_tool_response.summary`), and `render_intent`.

**Output (strict JSON):**

```json
{ "bot_message": "Short conversational text", "widgets": [ <envelope>, ... ] }
```

Every envelope:

```json
{ "schema_version": 1, "widget_type": "<type>", "variant": "default", "payload": { } }
```

The runtime validates each envelope+payload against `playbooks/widget-contract/*.schema.json`. **Invalid output is replaced with `bot_text`** — so schema validity is a hard success metric (§7).

**Widget vocabulary (24 types)** — `bot_text`, `user_text`, `clarify_question`, `error_card`, `notification`, `loading_card`, `typing_indicator`, `action_chooser`, `place_autocomplete_input`, `date_range_picker`, `party_picker`, `place_list` / `place_card`, `flight_list` / `flight_card`, `hotel_list` / `hotel_card` / `hotel_compare`, `activity_list`, `transfer_list`, `itinerary_summary`, `calendar_view`, `order_confirmation`, `map_view`, `filter_panel`, `property_block`.

**Widget-selection rules (from the chat prompt):**

- Missing region → `place_autocomplete_input`; missing dates → `date_range_picker`; missing party → `party_picker`.
- Ambiguous/contradictory → `clarify_question`; provider/tool error → `error_card` (with retry CTA).
- `mcp/google-places.search_text` result → `place_list` of `place_card`.
- `mcp/duffel.search_offers` result → `flight_list` of `flight_card`.
- `mcp/hotelbeds.search_hotels` → `hotel_list` of `hotel_card`; comparing two → `hotel_compare`.
- activities → `activity_list`; transfers → `transfer_list`.
- `mcp/duffel.create_order` → `order_confirmation` (copy receipt fields verbatim — never fabricate `booking_reference`).
- End-of-flow → `itinerary_summary` + companion `calendar_view` (`display_events`).
- "show my schedule" → `calendar_view` (`variant: full`, `editable: true`, `events_path` for live subscription).

**Hard constraints:** `bot_message` stays short (structured info lives in widgets); CTA ids must round-trip (`pick_offer:off_123`, `retry:<tool>`, `confirm`, `edit:dates`); **widget-type selection is deterministic** for the same (slot_state, tool-response class) — only natural-language wording may vary. This determinism requirement strongly shapes the model approach (§3).

### 2.4 `render_intent.kind` enum (the bridge between the two passes)

Observed across the prompt + the Python projection:
`collect_missing` (with `missing: [...]`), `show_places`, `show_flights`, `show_hotels`, `show_activities`, `show_transfers`, `summary` / `summarize`, `order_confirmation`, `order_detail`, `flight_detail`, `calendar_live`, `clarify`, `error`.

### 2.5 Summary: what the SLM must reproduce

1. **Extractor:** `(event, slot_state, thread_context) → {slot_updates, tool_requests, render_intent}` — schema-valid, deterministic tool selection, exact tool-id + argument-key fidelity.
2. **Renderer:** `(slot_state, extraction, tool_summary, render_intent) → {bot_message, widgets[]}` — every widget validating against its schema, deterministic widget-type selection.

These two functions are the entire SLM scope. Everything else in the planner (Firestore persistence, NATS routing, the Rust orchestrator, the MCP provider calls) is unchanged.

---

## 3. Model approach — options and recommendation

The task is **structured generation under a fixed JSON grammar with deterministic class selection**, not open-ended chat. That framing drives the options.

### Option A — Small instruct model, fine-tuned (recommended core)

A ~0.5B–3B instruct model (candidates: Qwen2.5-0.5B/1.5B/3B-Instruct, Llama-3.2-1B/3B-Instruct, Phi-3.5-mini ~3.8B, SmolLM2-1.7B) fine-tuned (LoRA/QLoRA) on the travel extraction+rendering contract.

- **Pros:** highest task accuracy for a fixed footprint; learns the domain's tool-selection and widget-selection rules directly; small enough for CPU or a small GPU; removes prompt-engineering brittleness.
- **Cons:** requires a training pipeline + dataset + eval harness; two roles may want two adapters (or one multi-task model with a role token).

### Option B — Constrained / grammar-guided decoding (recommended companion, not standalone)

Use a JSON-schema / GBNF grammar to force structurally valid output (llama.cpp GBNF, Outlines, XGrammar, vLLM guided decoding). Apply the **widget-envelope schemas and the extraction schema directly** as the decoding grammar.

- **Pros:** guarantees schema-valid JSON (drives widget-validity metric to ~100% structurally); guarantees the `tool` field is one of the enum values; cheap to add on top of any model.
- **Cons:** grammar enforces *structure*, not *correctness* — it won't pick the *right* tool or the *right* widget on its own. Best used **with** A.

### Option C — Prompt a small instruct model (no fine-tune)

Few-shot the existing `system_prompt_*.md` against a small instruct model as-is.

- **Pros:** zero training; fastest to stand up for a Phase-1 baseline.
- **Cons:** small models follow long multi-rule prompts poorly; accuracy/determinism likely below the deterministic Python baseline. Useful only as a **baseline number**, not the target.

### Recommendation: **Hybrid A + B**

Fine-tune a small instruct model (**A**) for the domain decisions, and wrap inference in **grammar-guided decoding (B)** so the output is always schema-valid and the `tool`/`widget_type` fields are always in-enum. Concretely:

- One model, two roles, selected by a role token / separate system prompt (extract vs render). Start from **Qwen2.5-1.5B-Instruct** or **Llama-3.2-1B-Instruct** as the Phase-2 default (revisit after the Phase-1 baseline).
- Grammar = the extraction JSON schema for the extractor, the widget-envelope union schema for the renderer.
- Keep a **deterministic post-processor** for the few mechanical bits that don't need a model: the `_city_geo` lat/lng lookup, `duffel_env: test` injection, CTA-id formatting. This is the "hybrid" seam — the model decides, deterministic code fills mechanical fields. It also gives a guaranteed-safe fallback path (the existing Python) when the model is unavailable.

### Footprint / latency sketch (to validate in Phase 2, not commitments)

| Approach | Footprint | Latency target (per pass) | Serving |
|---|---|---|---|
| 0.5–1.5B + grammar, CPU (GGUF/llama.cpp, quantized) | ~0.5–1.5 GB RAM | aim < 300–600 ms | CPU inference service / worker-embedded |
| 1.5–3B + grammar, small GPU (vLLM/TGI) | 1× T4/L4 | aim < 100–200 ms | in-cluster GPU inference service |

These are the numbers Phase 2/4 must actually measure against the OpenAI baseline and the per-hop budget (#130/#136).

---

## 4. Serving architecture

**Strong preference: mirror the MCP-provider pattern we already use** (firestore / duffel / google-places / hotelbeds*). That is: an **in-cluster inference service exposed over HTTP**, called from a NoETL playbook via the existing tool/HTTP machinery, so it slots into the catalog exactly like another `mcp/*` provider.

```
itinerary-planner.yaml
  └─ extract_turn / render_widget_chat
       └─ (flagged) tool: playbook  path: automation/agents/mcp/travel-slm
            └─ http → travel-slm inference service (in-cluster)
                 └─ small model + grammar-guided decoding
```

### Two serving shapes (decide in Phase 3)

1. **Sidecar/standalone inference service over HTTP (recommended).** A Deployment running vLLM/TGI (GPU) or llama.cpp-server/Ollama (CPU) exposing `POST /extract` and `POST /render` (or one MCP-style `tools/call`). The `mcp/travel-slm` playbook calls it via the `http` tool. Honors the data-access boundary (the model is an *external subsystem* to NoETL like Auth0/Duffel; it touches no `noetl.*` data) and the secrets rule (no business secret needed — it's a local model).
   - **Pros:** scales independently (KEDA on its own queue), GPU isolation, model swap = redeploy one service, zero worker-image bloat. Matches the auth/runtime lessons in noetl/ai-meta#137 (don't bake heavy deps into the worker image).
2. **Worker-embedded model.** Load a quantized GGUF inside the Rust/Python worker and infer in-process.
   - **Pros:** no extra network hop (best per-hop latency).
   - **Cons:** couples model lifecycle to worker image; every worker pod holds model memory; conflicts with the worker-scaling math; harder to put on GPU. **Not recommended** unless Phase-2 latency proves the HTTP hop is the bottleneck and the model is tiny.

### Latency budget

The planner is a multi-hop event-sourced flow; per-hop latency is actively tracked (#130 off-server drive ~per-hop; #136 end-to-end). Replacing two OpenAI RTTs (~hundreds of ms–seconds each, plus external-network variance) with a local in-cluster call should **reduce and stabilize** the LLM contribution to per-turn latency. Phase 4 measures this explicitly; the SLM is only a win if local p50/p95 ≤ OpenAI p50/p95 at acceptable accuracy.

---

## 5. Training-data plan

The contract's two `system_prompt_*.md` files + the deterministic Python reference make bootstrapping unusually cheap.

### 5.1 Teacher-bootstrapped dataset (OpenAI as teacher)

1. Assemble a **seed corpus of travel turns**: real Muno thread events (replayed from the event log — the planner is event-sourced, so historical turns are available), plus a curated set of synthetic queries covering each intent (destination lookup, dates, party, hotels, activities, transfers, flights, booking, calendar, clarify/error, corrections, multi-turn).
2. For each turn (with its slot_state + thread context), run the **OpenAI prompts** (`gpt-4o` extraction, `gpt-4o-mini` render) to produce the gold `{slot_updates, tool_requests, render_intent}` and `{bot_message, widgets[]}`. This is the **teacher label**.
3. **Cross-check against the deterministic Python reference** for the extraction routing and widget-type selection. Where teacher and deterministic agree → high-confidence label. Where they disagree → human review decides the gold label (and surfaces real bugs in either path).
4. **Schema-validate every label** (extraction schema + widget schemas). Drop/repair invalid teacher outputs.

This yields a `(input → gold JSON)` dataset for both roles, with the deterministic Python acting as a free second oracle and the widget schemas as a validity filter.

### 5.2 Curated + adversarial additions

- Hand-authored hard cases: contradictory corrections ("actually make it Paris not Miami"), ambiguous cities, missing-slot chains, production-booking refusals (must → `clarify`), sparse/failed tool responses (must → `error_card`).
- Coordinate/known-city coverage for transfers, and out-of-known-city cases (where the deterministic geo map is empty — the SLM must degrade gracefully or defer to post-processing).

### 5.3 Eval set

Hold out a stratified eval set (per intent, per event_type, per tool) **never seen in training**. Include a "golden replay" set of real prod threads so we can measure end-to-end turn equivalence, not just per-field accuracy.

---

## 6. Playbook integration (behind a flag, for A/B + shadow)

A new MCP-style playbook **`automation/agents/mcp/travel-slm`** exposes the model to the planner, and the planner calls it **instead of OpenAI behind a workload flag** so we can A/B and shadow-eval before any cutover. The routing arcs and widget contracts are **unchanged**.

Sketch (design only — not registered by this RFC):

```yaml
# automation/agents/mcp/travel-slm  (NEW — Phase 3)
# Thin MCP wrapper around the in-cluster travel-slm inference service.
# method: tools/call ; name ∈ {extract_turn, render_widget_chat}
workflow:
  - step: call_slm
    tool:
      kind: http
      method: POST
      url: "{{ workload.slm_service_url }}/{{ workload.slm_method }}"
      body: "{{ workload.slm_payload }}"   # the same inputs the OpenAI pass sees
    # returns the same JSON contract as the OpenAI pass (§2.2 / §2.3)
```

Planner wiring (design only):

```yaml
# itinerary-planner.yaml  (Phase 3 — flagged)
workload:
  extraction_engine: openai   # openai | slm | deterministic   (default openai)
  render_engine: openai       # openai | slm | deterministic
  slm_shadow: false           # when true: call SLM in parallel, log diff, but USE the active engine's output
```

- **`extraction_engine` / `render_engine`** select the active path per pass (so we can flip extraction to SLM while keeping rendering on OpenAI, or vice-versa).
- **`slm_shadow: true`** runs the SLM alongside the active engine, records the diff to the event log (§7 metrics), and discards the SLM output — zero user-facing risk during shadow-eval.
- The deterministic Python stays as the always-available `deterministic` engine and the safety fallback.

Observability (per `agents/rules/observability.md`): the SLM playbook ships a span (`slm.extract` / `slm.render`), latency + error + match-rate metrics, and `execution_id` correlation in the same change set as the integration.

---

## 6A. MLOps lifecycle as NoETL playbooks (dogfooding requirement)

**Hard architectural requirement:** *every* stage of the SLM's MLOps lifecycle — not just serving — is itself a **NoETL playbook/agent**, never an external script. The SLM project dogfoods the platform: the same ephemeral-blueprint execution model that runs the planner runs the model's own lifecycle. Each stage is a playbook under `automation/mlops/travel-slm/`, composed by a scheduled orchestrator. This keeps the lifecycle event-sourced, replayable, observable, and authored in the same place as the rest of the system.

### 6A.1 The lifecycle DAG (one playbook per stage)

| Stage | Playbook | Step DAG (sketch) | Tool kinds | NoETL capability needed | Gap |
|---|---|---|---|---|---|
| Dataset | `automation/mlops/travel-slm/dataset_build` | `load_corpus` (event-log replay + curated seed) → fan-out over turns → per turn: `teacher_extract` (http→gpt-4o) ‖ `teacher_render` (http→gpt-4o-mini) ‖ `oracle_deterministic` (playbook→deterministic engine) → `merge+schema_validate` (python, widget schemas) → `write_record` → `aggregate` → `write_dataset_artifact` → `register_dataset` | http, python, playbook, loop | teacher API + keychain secret; event-log replay; **large-artifact storage**; **dataset registry** | G3 |
| Train | `automation/mlops/travel-slm/finetune` | `resolve_dataset` (registry) → `dispatch_job` (GPU k8s-Job: LoRA/QLoRA, mounts dataset) → `await_completion` (callback/hook — frees the worker slot for the hours-long run) → `collect_artifact` (adapter → object store) → `register_model` (version + metrics + lineage) | **job/container**, callback, python | **GPU container/k8s-Job dispatch**; **long-running async** (hours); **large-artifact storage + model registry**; GPU node pool | G1, G2, G3 |
| Eval | `automation/mlops/travel-slm/eval` | `resolve_model`+`resolve_eval_set` → `run_inference` (http→inference svc / job) over held-out eval → `compute_metrics` (python: tool/arg/slot/render-intent/widget-type match vs OpenAI ceiling + deterministic floor; widget-schema validity; latency p50/p95) → `gate` (pass/fail vs §7) → `write_report`+`register_eval` | http, python | model registry read/write | G3 |
| Shadow | `automation/mlops/travel-slm/shadow_eval` | (driven by planner `slm_shadow: true`, which emits a `slm_shadow_diff` event per turn) → `aggregate_diffs` (read via server API/event log) → `compute_match_rate`+`latency` on live-shaped traffic → `report` | python, http (server API), schedule | event-log read via server API (data-access boundary) | — |
| Package | `automation/mlops/travel-slm/package` | `resolve_model` → `merge_quantize_job` (k8s-Job: merge LoRA, quantize to GGUF / build serving image) → `write_artifact` → `register_release` (serving-ready version + image digest) | **job/container**, python | GPU/CPU job; **large-artifact storage + model registry** | G1, G3 |
| Deploy | `automation/mlops/travel-slm/deploy` | `resolve_release` (registry) → `rollout` (deploy inference svc via the ops deploy automation; kind-validate first) → `smoke` (http health + extract/render sanity) → `flip_flag` (set planner `extraction_engine`/`render_engine` via catalog register) → `verify`+`record`. Rollback = re-flip the flag | playbook (ops deploy), http, catalog register | k8s rollout (existing ops automation); catalog/flag update; observability | — |
| Cron | `automation/mlops/travel-slm/retrain_orchestrator` | scheduled: `dataset_build` → `eval` (drift check) → conditional `finetune` → `eval` → `package` → gated `shadow_eval` | playbook composition, schedule | **schedule/cron** (exists); conditional control flow | — |

All seven honor the platform rules: external-subsystem calls (teacher API, the inference service) go direct; every `noetl.*` touch (dataset records, registry entries, event-log reads) goes through the server API per `data-access-boundary.md`; secrets (teacher API key) live in the keychain; each playbook ships span+metric+`execution_id` per `observability.md`.

### 6A.2 NoETL runtime capability gaps (tracked as their own items)

Playbook-based MLOps at training scale needs three platform capabilities NoETL does not have today. They are **design-flagged, not built** by this RFC, and each is its own tracked issue:

- **G1 — GPU container / k8s-Job dispatch tool.** A new tool kind that submits a Kubernetes Job (or container) with a GPU node-selector + resource request and returns a job handle. Today's tool kinds (http / python / postgres / playbook / …) can't launch a training or quantization container. Lands in `noetl/tools` (new kind) + `noetl/worker` (dispatch) + `noetl/ops` (GPU node pool + RBAC to create Jobs). Blocks: `finetune`, `package`.
- **G2 — Long-running async job orchestration.** A fine-tune runs for hours and must not hold a worker slot. The callback/hook pattern (`execution-model.md`) is the right shape, but needs concrete support: a job-completion callback/webhook + a poll/watch fallback, and long-timeout async resume so the playbook continues when the Job finishes. Lands in `noetl/server` (callback resume) + `noetl/worker` (job watch). Blocks: `finetune`, `package`.
- **G3 — Large binary artifact storage + model/dataset registry.** The result tier (noetl/ai-meta#104) materializes large *results* to GCS as Feather; model weights and datasets are GB binaries needing arbitrary blob put/get **plus a versioned registry in the catalog** (model + dataset entries with metadata, metrics, lineage, and an object-store pointer). Lands in `noetl/server` (catalog registry resource kind + blob tool) + `noetl/noetl`. Blocks: `dataset` (registry), `finetune`, `eval`, `package`.

> The GPU node pool itself is an ops/infra task (provisioned in Phase 3), not a runtime gap — but G1's dispatch tool depends on it existing.

### 6A.3 What this means for sequencing

`dataset_build`, `eval`, and `shadow_eval` run on **existing tool kinds today** (http + python + playbook + the planner flag from §6) — so **Phase 1 is not blocked** by the gaps, and the deterministic-floor + OpenAI-ceiling numbers can be produced immediately. `finetune` and `package` are **gated on G1–G3**; Phase 2 starts once those platform items land (they can be built in parallel with Phase 1). `deploy` reuses the existing ops deploy automation plus the catalog flag-flip.

---

## 7. Evaluation + success metrics

**Success metrics (vs OpenAI baseline, on the held-out eval + golden-replay set):**

| Metric | Definition | Target (provisional — confirm in Phase 1) |
|---|---|---|
| Tool-selection match | `first_tool` equals gold | ≥ 98% |
| Argument fidelity | `first_tool_arguments` key/value match (modulo mechanical fields filled by post-proc) | ≥ 95% exact, 100% schema-valid |
| Slot-update correctness | `slot_updates` deep-equals gold (ignoring key order) | ≥ 95% |
| Render-intent match | `render_intent.kind` equals gold | ≥ 98% |
| Widget-type selection | widget-type sequence equals gold (determinism) | ≥ 98% |
| **Widget-schema validity** | every emitted envelope validates (else runtime downgrades to `bot_text`) | **100%** (grammar-enforced) |
| Latency p50 / p95 (per pass) | local model vs OpenAI | ≤ OpenAI p50/p95 |
| End-to-end turn equivalence | full turn produces same tool + same widget classes as OpenAI on golden replays | ≥ 95% |

### Phased rollout

Per the §6A dogfooding requirement, each phase below is **delivered as the named NoETL playbook(s)**, not external scripts.

- **Phase 0 — RFC (this document).** Contract + plan + decisions. *No code/model/infra.*
- **Phase 1 — Dataset + baseline** → `automation/mlops/travel-slm/dataset_build` + `eval`. Build the teacher-bootstrapped dataset (§5) and the eval harness + metrics (§7) **as playbooks** (existing tool kinds — not gated on G1–G3); measure OpenAI (ceiling), deterministic Python (floor), and a no-fine-tune small-instruct (Option C) baseline. Decide final model size + serving mode from real numbers.
- **Phase 2 — Train / fine-tune** → `automation/mlops/travel-slm/finetune` + `package`. LoRA/QLoRA the chosen model + grammar-guided decoding; hit the §7 targets offline. **Gated on G1–G3** (capability gaps, §6A.2) — buildable in parallel with Phase 1.
- **Phase 3 — Serve + integrate behind flag** → `automation/mlops/travel-slm/deploy`. Stand up the in-cluster inference service + `automation/agents/mcp/travel-slm` playbook; wire the planner flags (`extraction_engine` / `render_engine` / `slm_shadow`). Kind-validate per `agents/rules/deployment-validation.md`. *Still defaults to OpenAI.*
- **Phase 4 — Shadow-eval vs OpenAI** → `automation/mlops/travel-slm/shadow_eval`. Run `slm_shadow: true` in a non-prod (or read-only-shadow) environment; collect match-rate + latency + widget-validity on live-shaped traffic; close the gaps.
- **Phase 5 — Gated cutover** → `automation/mlops/travel-slm/deploy` (flag-flip path). Flip `extraction_engine`/`render_engine` to `slm` per-pass, gated on the Phase-4 metrics meeting §7 targets, with instant rollback to `openai`/`deterministic` via the flag.
- **Ongoing — Scheduled retrain/eval** → `automation/mlops/travel-slm/retrain_orchestrator` on the schedule/cron mechanism, composing the above.

Each of Phases 1–5 is a child issue under the umbrella (§9).

---

## 8. Boundary & rules compliance

- **Execution model / data-access boundary** (`agents/rules/execution-model.md`, `data-access-boundary.md`): the SLM is an **external subsystem** to NoETL (like Duffel/Auth0/Google-Places). It touches no `noetl.*` data; it's called from a playbook step. ✅
- **Secrets** (`execution-model.md`): a local model needs **no business secret**; this *removes* the `openai-api-key` from the planner's critical path. ✅
- **Observability** (`observability.md`): the integration ships span + metrics + `execution_id` (§6). ✅
- **Deployment validation** (`deployment-validation.md`): the inference service + playbook are kind-validated before any GKE rollout (Phase 3). ✅
- **No prod change in Phases 0–2**; Phases 3–5 are flagged and default-off until the gated cutover.

---

## 9. Tracking

- **Umbrella:** noetl/travel#63 — "Travel domain SLM (replace OpenAI for intent + query construction + widget generation)" — labels `slm`, `ml`, `epic`, `enhancement`, `ai-task`.
- **Child issues (one per phase):** #64 dataset+baseline (P1), #65 train/fine-tune (P2), #66 serve+playbook+flag (P3), #67 shadow-eval (P4), #68 gated cutover (P5). Each phase is delivered as its named `automation/mlops/travel-slm/*` playbook (§6A, §7 rollout).
- **Capability-gap issues (§6A.2):** #70 G1 GPU container/k8s-Job dispatch tool, #71 G2 long-running async job orchestration, #72 G3 large-artifact storage + model/dataset registry. G1–G3 gate Phase 2 (`finetune`/`package`); Phase 1 (`dataset_build`/`eval`) is not blocked.
- Links: noetl/travel#60 (planner migration), noetl/ai-meta#137 (provider auth), noetl/ai-meta#130/#136 (latency), noetl/ai-meta#104 (result tier — basis for G3).
- Wiki: `travel-slm` page on the [travel wiki](https://github.com/noetl/travel/wiki/travel-slm).

---

## 10. Open decisions needed before Phase 1

1. **Model size / family.** Default to ~1–1.5B (Qwen2.5-1.5B-Instruct / Llama-3.2-1B-Instruct) and confirm after the Phase-1 baseline, or pin a preference now?
2. **CPU vs GPU serving.** CPU (cheaper, no GPU nodes, ~300–600 ms target) vs a small GPU node pool (L4/T4, <200 ms target). Affects node-pool/infra in Phase 3.
3. **Fine-tune vs prompt-a-small-instruct.** Commit to fine-tuning (Option A+B) as the target, with Option C only as the Phase-1 baseline? (RFC recommends yes.)
4. **One model two roles vs two models.** Single multi-task model with a role token (recommended) vs separate extractor/renderer models.
5. **Teacher budget.** OK to spend OpenAI `gpt-4o`/`gpt-4o-mini` tokens to bootstrap the dataset (§5)? Rough size of the seed corpus (e.g. 5k–20k turns)?
6. **Cutover aggressiveness.** Per-pass independent cutover (recommended: extraction first, then rendering) vs both-at-once; and the metric bar for flipping (RFC proposes the §7 targets).
7. **Serving stack.** vLLM / TGI (GPU) vs llama.cpp-server / Ollama (CPU) for the inference service — tie to decision #2.
8. **Replay access for the dataset.** Confirm we can replay historical Muno threads from the event log to build the real-traffic portion of the dataset + golden-replay eval set.

---

## 11. Status / Outcome (update — 2026-06-26)

> Appended after Phases 0–B shipped. The body above (§1–§10) is the
> original Phase-0 design and is kept verbatim for the record. This
> section is an honest status of where the project actually landed,
> which diverged from the Phase-0 assumptions in two important ways.
> Full narrative + numbers live on the wiki:
> [Travel-SLM-Journey](https://github.com/noetl/travel/wiki/Travel-SLM-Journey)
> and
> [Training-the-Travel-SLM](https://github.com/noetl/travel/wiki/Training-the-Travel-SLM).

### Teacher: OpenAI removed, Vertex Gemini in — and the floor surprise

OpenAI was **fully removed** from the SLM pipeline. The teacher is now
**Vertex Gemini (`gemini-2.5-flash`)** called over Workload Identity —
**no API key, no keychain secret** on the teacher path (landed in
noetl/ops#216 + noetl/travel#75).

The load-bearing finding came early and reshaped the project: **the raw
teacher scored *below* the deterministic oracle floor.** A bigger
general model, prompted with the contract, did not beat the rule-based
Python reference at this narrow structured-generation task — the raw
teacher even emitted the wrong key (`tool_id` instead of `tool`). The
fix was **not** a bigger model but **schema / grammar-constrained
decoding**: forcing the teacher's output through the extraction +
widget-envelope schemas (Vertex `responseSchema`) took schema validity
to 100% and tool/extract match up to the floor. That reframed the whole
effort around **constrained decoding + a small fine-tuned model** —
exactly the Hybrid A+B recommendation in §3, but for a sharper reason
than originally argued: at this task, *constraint beats scale*.

Consequently the §5/§7 "OpenAI as ceiling" framing is retired. The
**deterministic oracle is the authoritative labeler**, and the SLM is
measured as *accuracy over the deterministic floor*, not *fidelity to a
frontier ceiling*.

### Pipeline: Phase 1 dataset built, full MLOps lifecycle shipped

The §6A "MLOps-as-NoETL-playbooks" requirement is **real and shipped**.
The Phase-1 dataset is built, and the `finetune` / `eval` / `package`
playbooks landed on the G1/G2/G3 foundations (GPU/container Job
dispatch, long-running async, and the registry / artifact store) —
noetl/ops#219 (Phase-B finetune + eval(SLM) + package playbooks). The
G1–G3 capability gaps called out in §6A.2 are no longer blocking: they
were built, and the lifecycle runs on them.

### Local training: Apple Silicon (MLX), Qwen2.5-1.5B LoRA

Real fine-tuning now runs **locally on Apple Silicon via MLX** —
**Qwen2.5-1.5B with LoRA** — alongside the container/GPU path
(noetl/ops#220 + the v2/v3 synthetic corpus generator noetl/travel#76).
The v1→v2→v3 data-scaling iterations moved per-field match steadily up,
with **schema validity pinned at 100% throughout** (the grammar
guarantee from §3 holding in practice):

| Field match | v1 | v3 |
|---|---|---|
| `tool` | 0.56 | **0.94** |
| `render_intent` | 0.56 | **0.92** |
| `widget_type` | 0.38 | **0.79** |
| argument fidelity | 0.56 | **0.94** |
| slot updates | 0.63 | **0.94** |
| schema validity | 100% | **100%** |

### Honest current status — not yet at the production gate

The model is **not yet at the §7 production bar** (≥0.98 tool/render-
intent, ≥0.95 arg/slot). Most fields are at/near 0.94; the **lone
remaining blocker is `widget_type_match` (~0.79)** — specifically the
**render-generation pass for data-bearing widgets** (flight/hotel/
activity lists and the like), which is harder than the extraction-side
routing. Closing that gap is the **next iteration**: more / better-
targeted render examples for the data-bearing widget classes, not a new
architecture. Extraction-side routing is effectively production-ready;
rendering is the long pole.

### Reference

- **Merged work:** noetl/ops#216 + noetl/travel#75 (Vertex Gemini
  teacher), noetl/ops#219 (Phase-B finetune/eval/package playbooks),
  noetl/ops#220 + noetl/travel#76 (MLX local LoRA + v2/v3 corpus).
- **Wiki (full detail):**
  [Travel-SLM-Journey](https://github.com/noetl/travel/wiki/Travel-SLM-Journey)
  (the end-to-end story + the floor-surprise finding) and
  [Training-the-Travel-SLM](https://github.com/noetl/travel/wiki/Training-the-Travel-SLM)
  (the local MLX training how-to + per-version metrics).
