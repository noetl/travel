# Travel-domain SLM instance (`slm.config.yaml` #1)

The first filled-in config surface for the generic
`automation/mlops/slm` template pack (noetl/ops). Proves the platform RFC
([noetl/ai-meta#139](https://github.com/noetl/ai-meta/issues/139)) config
surface on a real domain. Phase A:
[noetl/ai-meta#140](https://github.com/noetl/ai-meta/issues/140) /
[noetl/travel#64](https://github.com/noetl/travel/issues/64).

## Files

| File | Role |
| :-- | :-- |
| `slm.config.yaml` | The one object travel writes (RFC §2.2). Drives the generic templates. |
| `oracle.py` | Deterministic labeling oracle — rule-based reimplementation of the planner's `extract_turn` + `render_widget_chat` contract. The zero-cost label floor + safety fallback. |
| `contracts/extract_output.schema.json` | Extraction output contract (slot_updates / tool_requests / render_intent). |
| `contracts/render_output.schema.json` | Render output contract (bot_message + widget envelopes; envelopes validated against `playbooks/widget-contract/*`). |
| `datasets/seed/travel_seed_turns.jsonl` | 45-turn curated seed corpus across all intents/tools, multi-turn, edge + adversarial cases. |

The widget schemas are reused from `playbooks/widget-contract/` (not
duplicated) — the config points at them via `widget_schema_dir`.

## Run (kind / local)

```bash
# from the ai-meta root
noetl exec repos/ops/automation/mlops/slm/dataset_build.yaml -r local \
  --set config=repos/travel/automation/mlops/slm/travel/slm.config.yaml
noetl exec repos/ops/automation/mlops/slm/eval.yaml -r local \
  --set config=repos/travel/automation/mlops/slm/travel/slm.config.yaml
```

Outputs land under `datasets/build/travel/v1/` (gitignored — regenerable):
`train.jsonl`, `eval.jsonl`, `manifest.json`, `eval_report.json`.

## Phase-A baseline (seed corpus, 45 turns → 29 train / 16 eval)

**Deterministic-oracle FLOOR + harness validation. OpenAI ceiling deferred.**

| Signal | Value |
| :-- | :-- |
| Dataset schema validity (extract / render / all 48 widget envelopes) | **100%** |
| Eval widget-schema validity | **1.0** (target 1.0) |
| Eval extract-schema / tool-vocab / render-intent-vocab validity | **1.0** |
| Match vs floor (tool / arg / slot / render-intent / widget-type) | **1.0** (harness sanity — deterministic candidate reproduces the floor) |
| Floor latency p50 / p95 | **sub-millisecond** (~0.02 ms p50; pure-Python rules) |
| Coverage | 9 render-intents, all 4 tools, 10 widget types |
| Gate | **passed** |

**Reading the baseline (what it de-risks for the model choice):**

- **Schema validity is already 100%** at the floor. The SLM target of 100%
  widget validity is achievable (and grammar-guided decoding makes it cheap);
  the model must *match* this, not improve it.
- **The floor latency is essentially free** (sub-ms). An SLM call will be
  ~hundreds of ms. So **the SLM must justify itself on accuracy over the
  deterministic floor, not on latency** — latency is a cost the SLM pays vs the
  floor, recovered only against the *OpenAI* path. This sharpens decision 2/7
  (CPU vs GPU serving) and decision 1 (model size).
- **The match-vs-floor 1.0 is the harness working, not a model score.** The
  load-bearing number that will rank model candidates — agreement with the
  **OpenAI ceiling** — needs teacher labels (next).

## What Phase 1 needs next

1. **OpenAI teacher budget** (RFC decision #6) — enable `teachers[0]` to
   produce higher-quality labels and the real **ceiling** (oracle↔teacher and,
   later, SLM↔teacher agreement). This is the number that ranks model
   candidates.
2. **Event-log replay access** (RFC decision #8) — replace/augment the
   synthetic seed with real Muno threads (via the server API, data-access
   boundary) for a golden-replay eval set.
3. **Model-choice decision** (RFC §10 decisions 1/3/4) — now informed by this
   baseline: size/family, one-model-two-roles vs two, fine-tune vs prompt.

`finetune` / `package` / `serve` remain gated on platform foundations
**G1** (GPU job dispatch), **G2** (long-async), **G3** (artifact storage +
registry) — see #144/#145/#146.

## Caveats (honest)

- The oracle is a faithful reimplementation of the documented contract, not yet
  the planner's exact inline code. Wiring the planner to delegate to this shared
  module (so they can't drift) is a tracked follow-up.
- Tool-response payloads in the render labels are deterministic fixtures (no
  live MCP calls in Phase A); real provider responses arrive via event-log
  replay.
- One known oracle gap surfaced by the adversarial corpus (`t032`): a
  region *correction* ("make it Paris not Miami") is not applied because the
  oracle only sets an empty slot. This is exactly the kind of case a teacher /
  fine-tuned SLM should fix — captured in the dataset as a documented floor
  limitation.
