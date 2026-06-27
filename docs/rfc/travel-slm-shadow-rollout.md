# RFC: Travel SLM shadow rollout + data flywheel

- **Status:** Draft (design / assessment only — no code, no infra, no prod change)
- **Owner:** Muno / NoETL travel
- **Tracking:** noetl/travel#67 (shadow-eval) under umbrella noetl/travel#63;
  platform umbrella noetl/ai-meta#139
- **Builds on:** [`docs/rfc/travel-slm.md`](travel-slm.md) (the functional spec + oracle design),
  the v1→v3 training journey, and the negative v4 render iteration
- **Companion wiki:** [Travel SLM — track record](https://github.com/noetl/travel/wiki/Travel-SLM-Journey)
- **Scope of this document:** how to put the v3 SLM to work in **shadow mode** in
  the planner, the promotion gate from shadow→primary, how shadow traffic becomes
  the real training corpus we are missing (the data flywheel), the realistic
  serving options with an operator infra checklist, and an honest assessment of
  where shadow is safe to start. **Nothing here trains a model, stands up infra,
  or modifies the planner. Every infra item is flagged as an operator decision.**

---

## 0. TL;DR

1. The two planner LLM passes — `extract_turn` and `render_widget_chat` — **do
   not call OpenAI today**. They run the deterministic heuristic oracle (regex
   slot-filling + rule-based widget selection). The `ai_provider: openai` /
   `gpt-4o` workload fields are vestigial provenance (`llm_contract.fallback_used:
   true`). This is the single most important fact for framing the rollout (§1).
2. **Shadow mode** runs the v3 SLM in parallel with the live oracle path on real
   turns, logs both outputs + the chosen one, and **never touches the
   user-facing response**. The comparison engine already exists: `slm_eval.py`
   computes per-field agreement vs the oracle + schema validity + latency (§2).
3. The **promotion gate** is per-field agreement on *real traffic* (not synthetic),
   schema validity, latency, and cost — with a hard fallback rule: any invalid or
   low-confidence SLM output yields to the live path (§3).
4. The **data flywheel** is the strategic payoff: shadow logging + `slm_replay.py`
   turns production turns into a labelable corpus, so the next training iteration
   uses **real** data instead of the synthetic seed corpus that capped v1→v4 (§4).
5. **Serving** a 1.5B LoRA realistically means one of: a local MLX endpoint for a
   tiny internal pilot, or a CPU/GPU in-cluster service behind an `mcp/travel-slm`
   playbook for prod. Each has a precise operator checklist (§5).
6. **Honest assessment:** v3 is right on 4/5 fields and 100% schema-valid but
   short of the gate on `widget_type` for data-bearing widgets. Shadow is safe to
   start everywhere (it is non-serving by definition); promotion is safe first for
   **extract-side routing + shallow widgets**, and gated for flight/hotel list
   widgets until the flywheel clears `widget_type` (§6).

---

## 1. Current state: the "live path" is the deterministic oracle, not OpenAI

The earlier RFC ([`travel-slm.md`](travel-slm.md)) described the two passes as
"today declared as OpenAI calls." Reading the current planner source pins down
the reality precisely, and it changes the shadow framing:

### 1.1 Where the two passes live

| Pass | Step | Location | What it actually runs today |
| :-- | :-- | :-- | :-- |
| Extraction | `extract_turn` | `playbooks/itinerary-planner.yaml:167` (`kind: python`) | Deterministic heuristics: `_city_hint` (8 hardcoded cities), `_flight_route` regex, `_date_hint`, `_party_hint`, rule-based `render_intent`. **No network call.** |
| Chat-render | `render_widget_chat` | `playbooks/itinerary-planner.yaml:1439` (`kind: python`) | Deterministic widget-envelope builder from `slot_state` + `render_intent` + tool summary. **No network call.** |

Confirmed by source: there is no `import openai`, no `chat/completions`, no
`generativelanguage`/Vertex call anywhere in `playbooks/` or `automation/`. The
only `gpt-4o` references are the vestigial workload fields
(`itinerary-planner.yaml:39-41`) and a comment in `slm.config.yaml`. The
`extract_turn` step builds an `llm_contract` dict (`itinerary-planner.yaml:733`)
that hardcodes `"fallback_used": True` — i.e. it records "an LLM *would* have run
here; the heuristic fallback produced this instead."

### 1.2 Why this matters for shadow

The deterministic oracle is **also the labeler** the whole SLM effort trains
against (`slm.config.yaml` → `extract_role.deterministic_oracle`, and
`slm_eval.py` measures every candidate against the oracle as the FLOOR). So:

- **The live path == the oracle == the labeler.** Today, "agreement vs the live
  path" and "agreement vs the oracle" are the *same measurement*. That is a gift
  for shadow: the comparison ground truth is free and already implemented.
- **The oracle is brittle, and that is the opportunity.** It only knows 8 cities
  (`_city_hint`) and a fixed airport-code table. A real user asking about Tokyo,
  Berlin, Rome, or phrasing a date the regex misses gets `region=None` →
  `collect_missing` forever. On the real-traffic distribution the oracle silently
  *fails*, and those exact turns are the highest-value training examples the
  synthetic corpus never contained. Shadow mode is how we *find* them.

### 1.3 The exact integration point

Both passes already emit a clean, structured result that downstream steps read by
name. The SLM produces the **same shape** — `SlmRunner.run_turn(turn)` returns
`{"extract": ..., "render": ...}` (`slm_infer.py:521`), deliberately mirroring the
oracle's `run_turn` so the eval engine treats it as just another candidate
(`slm_eval.py` docstring). The shadow step therefore consumes the same inputs as
`extract_turn`/`render_widget_chat` and compares against their outputs.

- **Extract inputs** (what the SLM conditions on): the user turn text, loaded slot
  state, recent thread events — already assembled at `extract_turn.input`
  (`itinerary-planner.yaml:171-183`).
- **Extract outputs to compare** (`extract_turn` result, `:769-788`):
  `first_tool`, `first_tool_arguments`, `render_intent`, `captured_slots`
  (slot_updates), `json_str`.
- **Render inputs**: `extract_turn` result + tool summary + render intent
  (`render_widget_chat.input`, `:1443-1453`).
- **Render outputs to compare** (`render_widget_chat` result):
  `first_widget` (the widget envelope: `widget_type`, `variant`, `payload`),
  `bot_message`.

---

## 2. Shadow architecture

### 2.1 Principle

> The SLM produces extract/render outputs **in parallel** with the live oracle
> path. The live path still serves the user. Both outputs + the chosen one are
> logged for comparison. The SLM output **never** reaches the user-facing
> response while in shadow.

### 2.2 Planner integration (non-blocking side branch)

The planner is a DAG with exclusive arcs. `render_widget_chat` depends on
`extract_turn`; the finalize chain depends on `render_widget_chat`. The shadow
work is added as a **side branch that nothing on the critical path reads**:

```
normalize_input ─► extract_turn ─► persist_turn_docs ─► …tool calls… ─► render_widget_chat ─► finalize
                        │                                                      │
                        └──► shadow_slm_extract ──► (captures live extract_turn ──┐
                                                     output for comparison)        │
                                                                                   ▼
                                              render_widget_chat ──► shadow_slm_render ──► log_shadow_comparison
```

Concretely (proposed, not yet written):

- **`shadow_slm_extract`** — a new step gated on
  `when: "{{ workload.slm_shadow.enabled | default(false) and (sample gate) }}"`.
  It reads the *same* inputs as `extract_turn`, calls the SLM endpoint
  (§5), and emits a structured event carrying `{slm_extract, live_extract,
  agreement_per_field, slm_latency_ms, schema_valid, fell_back}`. Its `next` arc
  points **only** to `log_shadow_comparison` — never to `persist_turn_docs` or
  `render_widget_chat`.
- **`shadow_slm_render`** — same pattern after `render_widget_chat`, comparing
  the SLM widget envelope vs the live one. Its `next` points only to the log sink.
- **`log_shadow_comparison`** — writes the comparison record to the event log
  (and a Firestore `shadow/` doc path for quick dashboarding). This is the
  flywheel's capture point (§4).

Because `render_widget_chat` and the finalize chain read **only** `extract_turn`
(never the shadow steps), the user-facing response is provably unchanged: removing
the shadow branch entirely would leave the served output bit-identical.

### 2.3 The toggle / flag surface (proposed workload block)

```yaml
# itinerary-planner.yaml workload (proposed; default OFF = today's behavior)
workload:
  slm_shadow:
    enabled: false                 # master switch; OFF = no SLM call at all
    endpoint: ""                   # SLM inference service URL (§5)
    model_urn: "registry://muno/travel/model/travel_slm_multitask/3"
    timeout_ms: 800                # SLM call budget; on timeout → record fell_back, skip
    sample_rate: 1.0               # fraction of turns to shadow (cost control)
    compare_render: true           # also shadow the render pass
    constrained_decode: true       # SLM_CONSTRAINED_DECODE (extract enums; the clean win)
    constrain_render: false        # SLM_CONSTRAIN_RENDER (OFF — v4 negative result, §6)
```

Two invariants the implementation must hold:

1. **Shadow never blocks or alters the served turn.** The shadow step runs after
   its live counterpart, on a bounded timeout, on a dead-end arc. A shadow failure
   (timeout, endpoint down, decode error) records `fell_back=true` and is a no-op
   for the user.
2. **Default OFF.** With `slm_shadow.enabled=false` the planner is byte-identical
   to today — the step's `when` short-circuits before any SLM call.

### 2.4 Reuse: the comparison engine already exists

`slm_eval.py` already implements exactly the per-turn comparison shadow needs:
given a candidate producer and the oracle, it computes per-field agreement
(`tool_match`, `render_intent_match`, `widget_type_match`, `arg_match`,
`slot_match`), schema validity, and candidate latency p50/p95
(`slm_eval.py:218-244`, candidate=`slm` path at `:187-218`). Shadow logging
should emit records in the **same field shape** so the offline analysis is the
existing eval engine pointed at the captured real-traffic corpus — no new metric
code, just a new data source.

---

## 3. Promotion gate (shadow → primary)

Promotion is **per pass and per intent/widget class**, not a single global flip
(§6 explains why). For a given class to graduate from shadow→primary, all of:

### 3.1 Quantitative criteria (measured on real shadow traffic, not synthetic)

| Field / dimension | Gate | Rationale |
| :-- | :-- | :-- |
| Schema validity | **100%** of SLM outputs in-class pass `validate_envelope` | Non-negotiable: an invalid envelope breaks the SPA. v3 already holds 100%. |
| `tool_match` (extract) | **≥ 0.98** agreement vs oracle on real turns | Wrong tool = wrong provider call = wrong itinerary. v3: 0.94 (synthetic). |
| `render_intent_match` (extract) | **≥ 0.98** | Drives which widget branch fires. v3: 0.92 (synthetic). |
| `arg_match` / `slot_match` (extract) | **≥ 0.97** | Wrong args = wrong search. v3: 0.94 / 0.94 (synthetic). |
| `widget_type_match` (render) | **≥ 0.98** *for the class being promoted* | The known blocker; passes for shallow widgets, fails for list widgets (§6). |
| Latency p95 | **≤ live-path p95 + budget** (target: p95 ≤ 800 ms; must beat OpenAI-RTT had it existed) | The SLM must not regress the turn. Oracle floor is sub-ms; the SLM bar is "fast enough," set explicitly by the operator. |
| Cost per turn | **≤ approved $/1k turns** for the serving option (§5) | Decision-ready number the operator signs off per serving choice. |

The agreement numbers above are stated **against the oracle**, because today the
oracle is the live path. Two refinements as the flywheel matures:

- **vs the live path:** the operating definition during shadow — does the SLM
  match what we actually served?
- **vs the oracle on real traffic:** once real turns are teacher-labeled (§4),
  agreement is measured against the *teacher/oracle label of the real turn*, which
  exposes cases where the **oracle itself was wrong** (e.g. unknown city). Here the
  SLM can and should *exceed* the oracle — that is the whole point of replacing a
  brittle heuristic with a learned model.

### 3.2 Sample-size + stability criteria

- A class promotes only after **≥ N real turns** observed in that class (operator
  sets N per traffic volume; suggested floor 500/class) and the agreement holds
  across **≥ 2 weeks** with no regression. No promotion off a single good day.

### 3.3 Fallback rule (always on, in shadow *and* after promotion)

> Any SLM output that is **schema-invalid**, **below a confidence threshold**, or
> **times out** falls back to the live (oracle) path for that turn.

After promotion the SLM becomes primary for its class, but the oracle stays wired
as the fallback producer. The fallback is silent to the user (the oracle's output
is what the SPA already expects) and is **counted** as a metric
(`slm_fallback_total{reason,class}`) so a rising fallback rate is an automatic
rollback signal. This mirrors the constrained-decode coercion already in
`slm_infer.py` (`_constrain_extract`/`_constrain_render`, `:248-294`), which
repairs a proposed output toward schema-validity before it is ever trusted.

### 3.4 Rollback

A single workload flag flip (`slm_shadow.enabled=false`, or a per-class
`primary_class` allowlist) reverts to the oracle with zero redeploy. The promotion
ladder (§6.3) is therefore fully reversible at each rung.

---

## 4. Data flywheel — shadow traffic becomes the real corpus

This is the strategic core. **The real bottleneck has never been the model — it's
that v1→v4 trained on a synthetic seed corpus** (45→950 hand-built turns). Shadow
mode is, first and foremost, the data-collection mechanism that fixes that.

### 4.1 The loop

```
real user turns ─► planner (oracle serves) ─► shadow_slm_* logs {turn, live_out, slm_out, chosen}
       │                                                              │
       │                                                              ▼
       │                                              event log + Firestore shadow/ docs
       │                                                              │
       ▼                                                              ▼
   slm_replay.ingest(base_url, …)  ◄──────────────────────  real-traffic execution details
       │  (redacts PII, parses extract_turn node, emits replay_corpus.jsonl)
       ▼
   dataset_build  ──►  RE-LABEL each real turn with the teacher (constrained Vertex Gemini)
       │              and/or the oracle; teacher fills the gaps where the oracle was wrong
       ▼
   G3 dataset (registry://muno/travel/dataset/…)  ──►  finetune (v_next)  ──►  eval  ──►  shadow again
```

### 4.2 The mechanism already exists

- **`slm_replay.py`** ingests the NoETL server event log into a labelable corpus:
  `ingest(base_url, path, limit, …)` walks real execution details, parses the
  `extract_turn` node (`_parse_prod_extract`, `:106`) and slot state
  (`_parse_slot_state`, `:154`), **redacts free text + payloads**
  (`redact_text`/`redact_payload`, `:51-85`), and writes `replay_corpus.jsonl`
  tagged `source: event_log_replay` (`:173-229`). Config comes from the org's
  `slm.config.yaml` `data.event_log_replay` block.
- **`slm_teacher.py`** is the constrained-decoding labeler (Vertex Gemini with
  `responseSchema`) that produced the Phase-1 result "grammar-constrained decoding
  beats a bigger model." It re-labels real turns the oracle can't (unknown cities,
  novel phrasings), producing supervision the synthetic corpus never had.
- **`dataset_build`** already reads either the seed corpus or the replay corpus and
  re-labels each input — the Phase-1 design explicitly anticipated this swap.

So the flywheel is **wiring, not new invention**: point `dataset_build` at the
replay corpus instead of the seed corpus, and the next training iteration trains
on production reality.

### 4.3 Why this clears the v3/v4 plateau

v4 was a *negative* result: more synthetic render samples + a payload-complete
render constraint did **not** clear `widget_type`, and the render constraint
crashed deep list widgets (lmfe `force_json_field_order` doesn't compose with
`anyOf`). The lesson recorded in the journey: **we were out of signal in the
synthetic data**, especially for the `show_flights`↔`show_hotels` boundary and the
data-bearing list widgets. Real shadow traffic supplies exactly that signal —
real flight/hotel result payloads, real user phrasings, real city distribution —
which is the missing ingredient for the next render iteration (the per-type
single-schema constraint noted as the next lever).

### 4.4 Privacy / safety

- Replay redaction (`redact_text`/`redact_payload`) runs at ingest. The shadow log
  must store **structured fields + redacted text only** — no raw PII, no
  credentials (per `agents/rules/safety.md` and the response-redaction contract).
- The shadow corpus is a tenant-data artifact: it lives in the tenant's storage,
  not in ai-meta, and not in any public repo.

---

## 5. Serving options + operator infra checklist

v3 is a Qwen2.5-1.5B **LoRA adapter** served via MLX on Apple Silicon today
(`backend: mlx` in `SlmRunner`). To serve it where the planner can call it, it
needs an inference endpoint. The G1/G2 (container/GPU job dispatch) and G3
(registry) foundations are merged but flag-gated / undeployed. Three realistic
options, smallest ask first.

> **All infra/IAM/flag items below are OPERATOR DECISIONS.** This RFC provisions
> nothing. Each option lists exactly what the operator must approve.

### Option A — Local MLX endpoint (tiny internal pilot only)

Run `SlmRunner(backend="mlx")` behind a thin FastAPI/`mlx_lm.server` on an Apple
Silicon Mac; the planner reaches it over a tunnel.

- **Use for:** a single-developer / staging shadow pilot to validate wiring and
  collect the first real turns. **Not** a prod path.
- **Operator checklist:**
  - [ ] Approve a dev Mac as the pilot host (already how v3 runs).
  - [ ] Approve a tunnel from the kind/staging cluster to the Mac endpoint (no public exposure).
  - [ ] Set `slm_shadow.endpoint` to the tunnel URL on a **staging** planner workload only.
  - [ ] No new IAM, no GPU pool, no GKE change.
- **Cost:** ~zero marginal (existing hardware). **Latency:** MLX 1.5B on M-series is interactive; fine for shadow.

### Option B — CPU in-cluster service (realistic low-QPS prod)

Serve a quantized 1.5B (GGUF via llama.cpp, or ONNX) on CPU in GKE behind an
`mcp/travel-slm` playbook (the §139 recommendation). A 1.5B int4 model runs on CPU
at low QPS without a GPU pool.

- **Use for:** prod shadow + early primary at Muno's current traffic.
- **Operator checklist:**
  - [ ] Approve a new Deployment + Service `travel-slm` in the cluster (CPU request/limit, replicas).
  - [ ] Approve the adapter→GGUF/ONNX conversion + bake into the image **or** fetch from G3 registry at boot (needs G3 deployed — currently flag-gated).
  - [ ] Approve an `mcp/travel-slm` catalog playbook (HTTP to the service) — per execution-model, the SLM call is a playbook step, not a gateway/worker DB touch.
  - [ ] Decide auth: in-cluster service-to-service (no external secret) — no keychain credential needed (no external subsystem).
  - [ ] Set per-component resource sizing + a `deployment-specification` wiki page (per `wiki-maintenance.md` Rule 2a) before rollout.
  - [ ] Kind-validate before GKE (per `deployment-validation.md`).
- **Cost:** one CPU Deployment's footprint. **Latency:** higher than GPU but bounded; verify against the §3 p95 gate during shadow.

### Option C — GPU-backed service on GKE (scale / higher QPS)

Serve Qwen2.5-1.5B + LoRA via vLLM or TGI on a GPU node pool, behind the same
`mcp/travel-slm` playbook. Uses G1 GPU placement (node_selector/tolerations,
tools#82 v3.19.0) + G2 job dispatch + G3 registry.

- **Use for:** if shadow shows CPU latency/QPS is insufficient, or when traffic grows.
- **Operator checklist:**
  - [ ] **Approve a GPU node pool** on GKE (instance type, min/max, cost). This is the largest single ask.
  - [ ] Build + push a vLLM/TGI serving image with the adapter (multi-arch, per worker image lifecycle).
  - [ ] **Workload Identity binding** for the serving SA to read the G3 artifact store (mirrors the `noetl-worker-mcp@` WI pattern from #137) — explicit IAM, operator-only.
  - [ ] Deploy G3 registry routes (currently flag-gated / undeployed) so the service resolves `registry://muno/travel/model/travel_slm_multitask/3`.
  - [ ] PVC for model/adapter cache; KEDA scaler if autoscaling the service.
  - [ ] `deployment-specification` wiki page (env vars, ports, probes, sizing) per Rule 2a.
  - [ ] Kind-validate (CPU stub or a single GPU node) before GKE.
- **Cost:** GPU node-hours — the operator sets the budget (ties to G6 cost controls, ai-meta#149). **Latency:** lowest.

### Recommendation

Start shadow on **Option A** (zero infra, immediate real-traffic capture), and in
parallel ask the operator to scope **Option B** as the prod shadow/primary target.
Hold **Option C** until shadow data proves CPU latency/QPS is the binding
constraint — don't provision a GPU pool on a hypothesis.

---

## 6. Honest assessment — where shadow is safe to start, and the path to primary

### 6.1 What v3 actually is

The v3 eval (144-turn synthetic eval split, constrained decode):

| Field | v3 | Gate | Verdict |
| :-- | :-- | :-- | :-- |
| `tool_match` | 0.94 | 0.98 | close, not there |
| `render_intent_match` | 0.92 | 0.98 | close, not there |
| `arg_match` | 0.94 | 0.97 | close |
| `slot_match` | 0.94 | 0.97 | close |
| `widget_type_match` | **0.79** | 0.98 | **the blocker** |
| schema validity | **100%** | 100% | **pass** |

v3 (`registry://muno/travel/model/travel_slm_multitask/3`) is the best model to
date; v4/v4b did not beat it. The `widget_type` gap is concentrated on the
**data-bearing list widgets** (`flight_list`/`show_flights`,
`hotel_list`/`show_hotels`), where the render constraint also *regresses*
(`anyOf` + `force_json_field_order` truncation → 0.30). On the **shallow widgets**
(`bot_text`, `collect_missing` inputs, the summary pair, `order_confirmation`) the
render constraint is a clean win.

### 6.2 Where shadow is safe to start

Shadow is **safe everywhere** — by construction it never serves the user (§2.2).
The question is really *where promotion is safe*, and the answer follows the
per-field strengths:

- **Promote-eligible first (extract side):** tool routing (`first_tool`),
  `render_intent`, and slot/arg extraction — once real-traffic agreement clears
  §3.1. These are where the SLM most clearly *beats the brittle oracle* on the
  real distribution (unknown cities the oracle drops entirely).
- **Promote-eligible next (render, shallow):** `bot_text`, `collect_missing`,
  summary, `order_confirmation` widgets — v3 + extract-only constraint is reliable
  here.
- **Gated (render, list widgets):** `show_flights`/`flight_list`,
  `show_hotels`/`hotel_list` — keep on the oracle until the flywheel-fed next
  iteration (per-type single-schema constraint + real list payloads) clears
  `widget_type`. Do **not** promote these on v3.

### 6.3 Staged path to primary (each rung reversible)

1. **Rung 0 — Shadow all (Option A).** Wire shadow, capture real turns, start the
   flywheel. SLM serves nothing. *Exit:* ≥N turns/class captured, wiring verified.
2. **Rung 1 — Promote extract routing.** SLM becomes primary for `first_tool` +
   `render_intent` + slots/args; render stays oracle. Oracle is fallback. *Exit:*
   §3.1 extract gates hold ≥2 weeks on real traffic.
3. **Rung 2 — Promote shallow render.** SLM primary for shallow widgets +
   `bot_text`; list widgets stay oracle. *Exit:* §3.1 render gate holds for shallow
   classes.
4. **Rung 3 — Retrain on real data (flywheel iteration v_next).** Re-train with the
   real corpus + teacher labels; target the `widget_type` list-widget gap with the
   per-type single-schema render constraint. Shadow v_next.
5. **Rung 4 — Promote list-widget render** only if v_next clears the
   `widget_type` gate on real traffic. Otherwise stay at Rung 2; the oracle keeps
   serving list widgets indefinitely — a safe, correct steady state.

At every rung the fallback rule (§3.3) and the single-flag rollback (§3.4) hold,
so the worst case of any promotion is a silent revert to the oracle the user
already gets today.

---

## 6b. Implementation status (Option A built + kind-validated)

Option A (local MLX pilot) is **built and validated end-to-end on kind/local**
(review-only; not on prod). What shipped:

| Piece | Where | What |
| :-- | :-- | :-- |
| Serving endpoint | `noetl/ops` `lib/slm_serve.py` | stdlib `http.server` over `SlmRunner`; `POST /extract`, `POST /render`, `GET /healthz`; loads the v3 LoRA, returns the planner's shapes + `schema_valid`. |
| Split inference | `noetl/ops` `lib/slm_infer.py` | `SlmRunner.run_extract` / `run_render` so each shadow pass is one model call. |
| Shadow core | `noetl/ops` `lib/slm_shadow.py` | `ShadowClient` + per-field agreement extractors identical to `slm_eval`. |
| Validation harness | `noetl/ops` `lib/slm_shadow_validate.py` | drives the endpoint over real eval turns vs the oracle; writes shadow records. |
| Data flywheel | `noetl/ops` `lib/slm_replay.py` `--shadow` | reads shadow-leaf records from the event log → corpus → `dataset_build --corpus`. |
| Planner shadow branch | `noetl/travel` `playbooks/itinerary-planner.yaml` | `workload.slm_shadow` block (default OFF) + an INCLUSIVE fork at `render_widget_chat` to a single `shadow_slm_compare` terminal leaf. |
| Orchestrator self-test | `noetl/travel` `playbooks/slm/shadow-selftest.yaml` | isolated planner-shaped playbook proving the mechanism on the real Rust orchestrator without the Firestore/MCP stack. |

### Design refinement found during the build — one leaf, not a chain

The RFC §2.2 sketch (`shadow_slm_extract → shadow_slm_render →
log_shadow_comparison`) was collapsed to a **single `shadow_slm_compare` leaf**.
Reason, observed on kind: the Rust orchestrator marks the whole execution
terminal the instant the main path's terminal step (`final_result`) completes,
then drives no further commands (`drive: execution is terminal; no further
orchestrate dispatch`). A multi-hop parallel shadow chain has its tail hop
orphaned when the slow SLM render outlives `final_result`. A single leaf is
dispatched at the fork, runs to completion in parallel, and persists its result
(the comparison record) in the event log even after the execution goes terminal
— no orphaned hop. The fork uses `next.spec.mode: inclusive` (the orchestrator's
"all matching arcs fire" mode) so the main arc and the shadow arc both fire when
enabled; with `enabled=false` the shadow arc's `when` is false → `step.skipped`,
and the response chain is byte-identical to today.

### Kind validation results (2026-06-27, review-only)

- **Agreement on real turns** (`slm_shadow_validate`, v3, 22-turn stratified
  eval covering all 11 widget classes): `tool_match` 0.86, `arg_match` 0.86,
  `slot_match` 0.86, `render_intent_match` 0.82, **`widget_type_match` 0.73**,
  schema validity **100%** (extract + render), latency p50 ≈ 2.9 s extract /
  3.4 s render on this Mac. `widget=False` lands exactly on the data-bearing
  list widgets (`show_flights`/`flight_list`, `show_hotels`/`hotel_list`) — the
  §6 blocker, faithfully reproduced on a live shadow harness, no fall-backs.
- **(a) shadow capture** — on the kind orchestrator the `shadow_slm_compare`
  leaf wrote a `slm_shadow_comparison` record to the event log carrying BOTH the
  live and the SLM extract+render, per-field agreement, `schema_valid`, real
  endpoint latencies (worker pod → host MLX endpoint via
  `host.containers.internal`), `chosen: live`, `fell_back: false`.
- **(b) byte-identical response** — the self-test's `final_response` was
  **byte-identical** between a shadow-OFF and a shadow-ON run on the same input;
  shadow ON only added the `shadow_slm_compare` leaf (the OFF run shows it as
  `step.skipped`). The served turn is provably unaffected.
- **(c) flywheel** — `slm_replay --shadow` pulled the shadow record from the
  event log into a corpus (redacted text + the live label as `prod_extract` +
  the SLM output), and `dataset_build --corpus` re-labeled it into a training
  dataset (`travel/shadow_flywheel`, 100% schema validity). A shadow turn
  became training data.

The real `itinerary-planner.yaml` shadow branch carries the identical wiring;
it was not executed end-to-end on kind because the full planner requires the
Firestore + MCP provider stack (not provisioned on kind). The self-test
exercises the identical mechanism on the same orchestrator, and the planner
edit is purely additive (the diff touches only `render_widget_chat`'s `next`
mode + one new arc + one new terminal leaf step + the `workload.slm_shadow`
block).

### Operator turn-on (prod) — a single change, NOT executed here

Shadow stays OFF on prod. To turn it on later, the operator (1) stands up the
endpoint per Option A, then (2) flips two `itinerary-planner` workload fields:

```yaml
workload:
  slm_shadow:
    enabled: true
    endpoint: "<reachable slm_serve URL>"   # e.g. the tunnel to the pilot Mac
```

Re-register the planner and the next turns shadow. Rollback is the inverse
single flag (`enabled: false`). No code change, no redeploy.

## 7. What this RFC does NOT do

- It does not modify `itinerary-planner.yaml` (the shadow steps in §2.2 are a
  proposal, not a diff).
- It does not train a model, build a serving image, or stand up any service.
- It does not provision GPU pools, IAM bindings, secrets, or GKE changes — those
  are the §5 operator checklists.
- It does not touch OQ5, the event-store cutover, or any production config.

## 8. Open decisions for the operator

1. **Serving target:** approve Option A for pilot now? Scope Option B for prod?
2. **Latency + cost gates:** set the explicit p95 budget and $/1k-turns ceiling per
   serving option (§3.1).
3. **Promotion sample size N** per class and the stability window (§3.2).
4. **Shadow corpus storage location** (tenant storage) and retention (§4.4).
5. **G3 registry deployment** — needed for Option B/C boot-time artifact fetch;
   currently flag-gated.
6. **Whether to keep list-widget render on the oracle permanently** if v_next
   doesn't clear the gate (Rung 5 is optional).

---

## Related

- [Travel-domain SLM RFC](travel-slm.md) — the functional spec + oracle/contract design.
- [Travel SLM — track record](https://github.com/noetl/travel/wiki/Travel-SLM-Journey) — the v1→v4 journey + numbers.
- [Training the Travel SLM](https://github.com/noetl/travel/wiki/Training-the-Travel-SLM) — the reproducible how-to.
- [Playbook: itinerary-planner](https://github.com/noetl/travel/wiki/playbook-itinerary-planner) — the consuming playbook.
- [Widget contract](https://github.com/noetl/travel/wiki/widget-contract) — the render-output schema the SLM must satisfy.
- Platform umbrella: noetl/ai-meta#139 (Domain-SLM platform); G-foundations #144/#145 (G1/G2), #146 (G3), #150 (loop engine), #149 (cost controls).
