# Implementation Plan: Travel playbooks

**Spec**: [spec.md](spec.md) | **Constitution**: [../../.specify/memory/constitution.md](../../.specify/memory/constitution.md)

## Technical context

- **DSL:** NoETL `apiVersion: noetl.io/v2`. Reference: https://noetl.ai/ and https://noetl.ai/llms.txt.
  Schema: https://noetl.ai/schema/v2/playbook.schema.json.
- **Runtime:** distributed (prod NoETL via `gateway.mestumre.dev`). Local runtime is not
  valid for python-step playbooks.
- **Storage:** Firestore via `automation/agents/mcp/firestore` (noetl/ops).
- **Gates:** `scripts/validate_playbook_schema.py`, `scripts/*_test.py` (CI:
  `.github/workflows/playbook-tests.yml`).
- **Tools:** `noetl` CLI ≥ 6.4.1, `scripts/trace_execution.py`, `scripts/profile_doc_read.py`.

## Constitution check

| Principle | How this plan satisfies it |
| :-- | :-- |
| I Validate Before Deploy | schema + guards before every register |
| II Runtime That Runs It | all verification on the gateway |
| III Read-Only Route | read trace + `updateTime` check per profile change |
| IV Honest Status | PR records execution id, version, catalog id, digest |
| V One Change, One PR | one task = one PR |
| VI noetl.ai | DSL lookups and schema from noetl.ai |
| VII Pin | `catalog get` saved before register |
| VIII Public | no ids, emails or profile contents in commits |

## Deploy procedure (per change)

Pin, then validate, then register, then verify (trace + Firestore), then record. The
exact commands are in [`docs/playbooks/AGENT-GUIDE.md` §4](../../docs/playbooks/AGENT-GUIDE.md).
