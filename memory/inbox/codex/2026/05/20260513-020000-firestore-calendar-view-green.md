# Firestore Calendar View

Status: GREEN for repository implementation and static/container validation.

Round 5 added the additive `calendar_view` widget contract, Material
`CalendarView` component, Firebase-backed live-read helper, Firestore-only
calendar data docs, demo-permissive rules file, and itinerary-agent calendar
event side effects.

No Google Calendar API or ICS export is used. The widget can render a static
`display_events` snapshot or subscribe to an `events_path` collection in
Firestore when permissive v1 rules are deployed by the operator.
