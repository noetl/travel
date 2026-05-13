# Event Sourcing

Round 3 introduced `automation/agents/mcp/firestore` in `noetl/ops`. Muno uses it as the generic persistence layer for chat threads, widget submissions, tool calls, and itinerary projections.

Every user action and agent decision is represented as an event under a caller-chosen thread path, commonly `chat_threads/{threadId}/events`. The trip document is a projection over those events and can be rebuilt from the log.

`append_event` assigns a monotonic `seq` in a Firestore transaction and redacts sensitive headers before writing. `replay_events` reads the stream back in order. The local ai-meta helper `scripts/firestore_replay.sh` can inspect those streams until muno grows its own replay UX.
