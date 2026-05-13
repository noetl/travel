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
