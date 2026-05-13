# Claude Code Entry Point

Read these files at session start:

1. `AGENTS.md`
2. `memory/current.md`
3. Latest entries in `memory/inbox/claude/` and `memory/inbox/codex/`
4. `docs/architecture/widget-contract.md`

## Quick Commands

- Add memory: `./scripts/memory_add.sh --kind=claude "<title>" "<summary>" "<tags>"`
- Compact memory: `./scripts/memory_compact.sh`
- Generate widget types: `./scripts/build_widget_contracts.sh`
- Smoke widget contracts: `npm run smoke:widgets`
- Fetch Figma: `./scripts/figma_fetch.sh file <file_key> --depth 2`

## Commit Conventions

- `chore: bootstrap muno ...`
- `feat(widgets): ...`
- `docs(architecture): ...`
- `memory(add): ...`
