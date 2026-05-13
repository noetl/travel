# Firestore Data Model

Initial convention for the trip-planner agent:

```text
users/{uid}
  chat_threads/{threadId}
    events/{eventId}
    trips/{tripId}
      api_calls/{callId}
      calendar_events/{eventId}
```

The Firestore MCP tools remain generic and do not enforce this structure. The itinerary-planner playbook in Round 4b chooses these paths and owns projection updates.

## Calendar Events

Round 5 keeps calendar data inside Firestore. There is no Google Calendar API
push and no ICS export in v1.

Authenticated users store events at:

```text
users/{uid}/trips/{tripId}/events/{eventId}
```

Guest threads store events at:

```text
chat_threads/{threadId}/trip/events/{eventId}
```

The itinerary agent writes documents with this shape:

```json
{
  "type": "flight_depart",
  "start_at": "2026-07-15T08:00:00-07:00",
  "end_at": null,
  "timezone": "America/Los_Angeles",
  "title": "Depart SFO",
  "location": "SFO",
  "notes": "Duffel test-mode flight segment",
  "source_order_id": "ord_123",
  "source_hotel_id": null,
  "created_at": "2026-05-13T02:00:00Z",
  "updated_at": "2026-05-13T02:00:00Z",
  "google_calendar_event_id": null
}
```

`type` is one of `flight_depart`, `flight_arrive`, `check_in`, `check_out`,
`activity`, or `user_note`.

`google_calendar_event_id` is reserved for a possible future integration and
is never read or written by the Round 5 Firestore-only implementation.
