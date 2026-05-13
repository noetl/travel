# Itinerary Agent 4b

Status: GREEN for repository implementation and static validation.

Round 4b added the Muno itinerary-planner playbook at
`playbooks/itinerary-planner.yaml`. The agent processes one input event per
invocation, appends the input through `mcp/firestore.append_event`, projects
`slot_state`, dispatches one MCP tool request when needed, persists a replay
fixture under `api_calls/{call_id}`, validates the widget envelope shape, and
returns the first widget as execution-level `render`.

Supporting files:

- `playbooks/agent/system_prompt_extraction.md`
- `playbooks/agent/system_prompt_chat.md`
- `playbooks/agent/widget_envelope_examples.md`
- `playbooks/deployment/register-with-noetl.sh`
- `scripts/itinerary_agent_smoke.sh`
- `docs/architecture/agent-design.md`

Hotels remain Amadeus-only and all provider calls are test-mode. The playbook
contains deterministic fallback extraction/rendering so smoke runs can still
exercise event and widget shapes when live LLM/tool access is unavailable.
