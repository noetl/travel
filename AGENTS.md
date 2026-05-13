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
