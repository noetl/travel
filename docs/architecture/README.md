# Architecture

Project-local architecture notes for muno.

## Pages

| page | covers |
| :-- | :-- |
| [business-catalog-firestore.md](business-catalog-firestore.md) | The **business catalog** — domain data (items, categories, attributes, reservations) in Firestore, reached from playbooks. Not EHDB, not the NoETL internal catalog. |
| [data-model.md](data-model.md) | The planner's **conversational** Firestore state — threads, events, calendar. Different concern, same database. |
| [event-sourcing.md](event-sourcing.md) | How a thread is event-sourced. |
| [widget-contract.md](widget-contract.md) | The closed widget envelope the SPA renders. |
| [agent-design.md](agent-design.md) | The itinerary agent's shape. |
| [calendar-design.md](calendar-design.md) | Calendar semantics. |
| [streaming-provider-turns.md](streaming-provider-turns.md) | Provider turn streaming. |
| [responsive-design.md](responsive-design.md) | Layout and breakpoints. |

⚠ **Two catalogs, one word.** The *internal* catalog holds NoETL's own objects and
lives in EHDB only. The *business* catalog holds this domain's data and lives
wherever the domain chooses — Firestore, here. The internal catalog holds the
playbook that reads the business data; it never holds the business data.
