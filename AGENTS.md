# Muno AI Instructions

## Scope

Applies to the entire `muno` repository.

## Mission

Build and maintain the Adiona/muno trip-planner app: frontend shell, widget contracts, trip-planner playbooks, project documentation, scripts, and project-local AI memory.

## Hard Rules

1. This repository is public; never commit secrets, `.env` files, credentials, API tokens, or `node_modules`.
2. Widget schemas under `playbooks/widget-contract/` are the contract source of truth.
3. `src/contracts/widgets.ts` is generated from schemas and committed for IDE support.
4. Widget components are JSON stubs until Round 6b replaces them with real Material rendering.
5. Browser writes to Firestore must go through NoETL MCP tools, not direct privileged credentials.
6. Memory updates are append-only through Git history.

## Validation

Before shipping code changes, run:

```bash
npm run type-check
npm run build
npm run smoke:widgets
```

## Working on NoETL playbooks (`playbooks/**`)

Read **[`docs/playbooks/AGENT-GUIDE.md`](docs/playbooks/AGENT-GUIDE.md)** before changing,
debugging or deploying a playbook. The same content is an installable skill:
[`docs/playbooks/noetl-travel-playbooks.skill`](docs/playbooks/noetl-travel-playbooks.skill)
(source in `.claude/skills/noetl-travel-playbooks/`). These rules are binding and are also
in the constitution, [`.specify/memory/constitution.md`](.specify/memory/constitution.md):

1. **Use noetl.ai for the DSL**, not memory. Start at https://noetl.ai/llms.txt. The reference
   and explorer page is https://noetl.ai/.
2. **Validate before every register:**
   `python3 scripts/validate_playbook_schema.py <file.yaml>` against
   https://noetl.ai/schema/v2/playbook.schema.json must print OK. Also run the repo guards
   (`scripts/*_test.py`).
3. **Test on the gateway (`--context gke-prod`), not locally,** for playbooks with
   `kind: python` steps. The local runtime skips or refuses them, so a local run of
   `profile.yaml` never reaches Firestore and doesn't route `read_only` correctly.
4. **Pin, register, verify.** Save the registered content first
   (`noetl --context gke-prod catalog get <path>`). Then register
   (`noetl --context gke-prod register playbook --file <file.yaml>`), then prove the new
   behaviour with an execution trace (`scripts/trace_execution.py <id>`).
5. **Gateway saves write the signed-in user's own profile.** Test with a QA account.
6. **One change per PR.** Specs: `specs/001-travel-playbooks/`. Report status honestly:
   "registered" is not "verified".
