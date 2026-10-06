# Travel regression suite

Regression cases expressed as NoETL playbooks, runnable locally, producing a machine-readable test
report.

**Methodology and rationale:** [QA with NoETL playbooks](https://github.com/noetl/travel/wiki/qa-with-noetl-playbooks)
— read that first if you are writing a new case.
**Manual prod validation** (a different job): [Validating the travel flows](https://github.com/noetl/travel/wiki/validating-the-travel-flows).

## Run it

```bash
noetl exec qa/regression/suite.yaml --runtime local \
  --set workload.repo="$PWD" \
  --set workload.workspace=/tmp/travel-qa
```

Reports land in the workspace:

| File | For |
|---|---|
| `report.json` | CI, dashboards, diffing between runs |
| `report.md` | humans — see [`examples/report.example.md`](examples/report.example.md) |
| `results/<case>.json` | one document per case, with every assertion |
| `evidence/<case>.log` | the full dispatch output for that case |

The suite **exits non-zero** when any case failed or errored, so a CI job that only checks the
exit status still cannot miss a regression.

One case, while iterating:

```bash
noetl exec qa/regression/cases/frontend-health.yaml --runtime local \
  --set workload.repo="$PWD" --set workload.workspace=/tmp/travel-qa
```

## Cases

| Case | Checks | Needs |
|---|---|---|
| [`profile-merge`](cases/profile-merge.yaml) | Saving profile section B must not wipe section A, and a read-back returns both | `gateway_url` for the live tier |
| [`frontend-health`](cases/frontend-health.yaml) | `team4.mestumre.dev` resolves, answers 200, serves a non-empty HTML body within budget | nothing |
| [`hotel-cards-smoke`](cases/hotel-cards-smoke.yaml) | hotel-cards parses, keeps its catalog path, reaches a terminal step, still declares its widget type | `server_endpoint` for the execution tier |
| [`dispatch-health`](cases/dispatch-health.yaml) | A trivial playbook still dispatches and completes in normal time — the tier-stall class | nothing |

Live tiers report **`blocked`** when their preconditions are absent. Blocked is **not** a pass; it
is missing coverage, reported as missing coverage. Set `--set workload.fail_on_blocked=true` in an
environment that is supposed to have every precondition, so silently losing a live check becomes a
build failure.

## Four verdicts

| Verdict | Meaning |
|---|---|
| `pass` | every assertion passed |
| `fail` | an assertion failed — a regression |
| `blocked` | preconditions absent; the case did not run |
| `error` | the harness itself broke, or a case asserted nothing |

A case cannot declare itself green: `pass` is computed from the assertions by
[`lib/qa_report.py`](lib/qa_report.py), never supplied.

## Self-test the harness

A runner that loses cases reports a pass it has not earned. `selftest/vanishing-case.yaml` dies
before writing any verdict; run it through the suite and **the suite must go red**:

```bash
noetl exec qa/regression/suite.yaml --runtime local \
  --set workload.repo="$PWD" --set workload.workspace=/tmp/travel-qa-selftest \
  --set workload.cases=frontend-health,../selftest/vanishing-case
# expected: error >= 1, suite_status "fail", non-zero exit
```

If that comes back green, stop trusting the reports until it is fixed.

## Writing a case

Follow the shape the existing four use — arrange, act, assert, report:

```yaml
executor:
  profile: local          # local runtime only
  version: noetl-runtime/1

workflow:
  - step: prepare         # arrange: validate inputs, make the workspace
  - step: probe           # act:     curl / dispatch, write evidence to a FILE
  - step: assert          # assert:  read the evidence, record assertions, exit non-zero on fail
  - step: end
    tool: { kind: noop }  # terminal noop only
```

Four constraints, each of them verified against the runtime rather than assumed:

1. **Local mode runs `shell`, `http`, `playbook`, `duckdb`, `auth`, `sink` — and silently skips
   everything else while still exiting 0.** A case built on `kind: python` executes nothing and
   reports success.
2. **Step results are not addressable from a later step.** `{{ previous_step.field }}` renders
   literally. Pass evidence between steps through files in the workspace.
3. **Assertions run under `env -u PYTHONOPTIMIZE python3`** with `qa_report.require_debug()`.
   Under `-O` the interpreter strips every `assert` and the case reports success having checked
   nothing.
4. **Arc conditions are a single comparison** wrapped in one `{{ }}`. Compound boolean conditions
   are mis-evaluated by the local runtime and fire when they should not.

The wiki page explains why each of these is a false-green source rather than a style preference.
