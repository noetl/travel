# Muno

Muno is the Adiona trip-planner project home base for NoETL. It contains the trip-planner frontend, widget contract schemas, project-local playbooks, documentation, scripts, and AI working memory.

## Development

```bash
npm install
npm run dev
npm run type-check
npm run build
npm run smoke:widgets
```

The first shipped surface is intentionally skeletal: widget components validate the wire envelope and render JSON stubs. Round 6b replaces those stubs with real Material renderers.

## Source of Truth

- Widget schemas: `playbooks/widget-contract/*.schema.json`
- Generated TypeScript types: `src/contracts/widgets.ts`
- Architecture: `docs/architecture/widget-contract.md`
- Scoping context: `noetl/ai-meta sync/issues/2026-05-12-trip-planner-app-scoping.md`
