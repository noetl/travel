# Calendar Design

Round 5 intentionally uses Firestore as the only calendar data plane. The
calendar view is a Muno widget backed by documents that the itinerary agent
writes through `mcp/firestore`; no external calendar API is called.

## Rationale

Firestore is already the source of truth for the event-sourced trip planner.
Keeping calendar events in the same store avoids Google Workspace calendar
creation gates, avoids per-user OAuth during the tutorial, and keeps replay
simple: event docs are just another projection derived from the chat thread.

## Event Documents

Events live under either:

```text
users/{uid}/trips/{tripId}/events/{eventId}
chat_threads/{threadId}/trip/current/events/{eventId}
```

The guest path is used when the caller has no authenticated user id.

Each event has a type, start/end timestamps, timezone, title, location, notes,
optional Duffel order or hotel ids, and a reserved `google_calendar_event_id`
field that remains `null` in v1.

## Widget Lifecycle

The itinerary agent writes event documents after confirmation-style turns:

- Duffel test order: `flight_depart` and `flight_arrive` events per segment.
- Hotel selection: `check_in` and `check_out` events.
- User note: `user_note` event.

When the agent emits `itinerary_summary`, it also emits `calendar_view` with a
static `display_events` snapshot. When the user asks for the schedule, the
agent emits `calendar_view` with `events_path` so the frontend subscribes live
through the gateway subscription API.

Live mode requires a gateway session. The browser calls
`POST /api/subscriptions/firestore`, then receives `subscription/event` frames
over the existing `/events` stream. The browser does not hold Firebase web
configuration and does not connect to Firestore directly.

## Roadmap

External calendar sync is intentionally out of scope. If it becomes useful,
add it as a post-tutorial feature with per-user OAuth and explicit consent.
Possible future surfaces:

- ICS export for a single trip.
- Google Calendar push via user-owned OAuth tokens.
- Calendar event editing widgets that round-trip into the itinerary agent.
