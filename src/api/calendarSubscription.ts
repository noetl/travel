/**
 * calendarSubscription.ts
 *
 * Replaces the `subscribeToCalendarEvents` export from
 * `gatewaySubscriptions.ts` with a transport that:
 *
 * 1. Reads the current calendar-event list synchronously on mount via
 *    `executePlaybook("travel/playbooks/catalog/calendar/list", ...)`.
 * 2. Listens for `playbook/state` frames on the existing NoETL SSE
 *    channel and re-runs the read playbook whenever a
 *    `playbook.completed` event arrives.
 *
 * ## Why `playbook/state` + `playbook.completed` instead of a named
 * `calendar.event.touched` SSE frame
 *
 * The gateway's `playbook_state.rs` listener only forwards events
 * whose `event_type` appears in `FORWARDED_EVENT_TYPES`:
 * `["step.exit", "playbook.completed", "playbook.failed"]`.
 * `calendar.event.touched` is a Firestore domain event stored in the
 * NoETL event log but is NOT currently multicasted as a named SSE
 * frame on the gateway's `/events` channel.  `playbook.completed` is
 * the earliest reliable signal the SPA can receive that the
 * orchestrator turn (which may have written calendar events) has
 * finished.  Round 3 can add a dedicated `calendar.event.touched` SSE
 * frame to the gateway if finer-grained filtering becomes necessary.
 *
 * ## Signature change vs old `gatewaySubscriptions.subscribeToCalendarEvents`
 *
 * Old: `subscribeToCalendarEvents(path: string, onItems)`
 *   where `path` was the raw Firestore collection path from
 *   `data.events_path`.
 *
 * New: `subscribeToCalendarEvents(trip_id, events_path, onItems, options?)`
 *   where `events_path` is still the raw collection path from the
 *   widget payload, kept as a fallback hint, and `trip_id` is the
 *   primary identifier the read playbook uses.  `events_path` is
 *   parsed to extract `user_uid` and `thread_path` so the read
 *   playbook can derive the correct Firestore collection path without
 *   those fields being added to `CalendarViewPayload` this round.
 *
 * `CalendarView.tsx` passes `data.trip_id` and `data.events_path`
 * (same fields it already accessed) — the swap is a one-import-line
 * change plus the extra `data.trip_id` argument.
 *
 * `events_path` may be null or missing (Round 3 will drop it from the
 * orchestrator output).  The module falls back gracefully: if
 * `events_path` is absent and `user_uid` cannot be parsed, `user_uid`
 * is sent as null and `thread_path` as '' — the read playbook will
 * raise a validation error, which is surfaced as a console.warn so the
 * widget stays in its last known state rather than crashing.
 */

import { addGatewaySSEListener, executePlaybook } from './noetlClient';

export type CalendarDoc = Record<string, unknown>;
type Unsubscribe = () => void;

interface CalendarSubscribeOptions {
  signal?: AbortSignal;
}

/**
 * Parse `user_uid` and `thread_path` from the Firestore collection path
 * that the orchestrator emits in `events_path`.
 *
 * Two shapes produced by the orchestrator:
 *   - authenticated: `users/{user_uid}/trips/{trip_id}/events`
 *   - anonymous:     `{thread_path}/trip/current/events`
 *     where thread_path is typically `chat_threads/{thread_id}`.
 *
 * Returns `{ user_uid, thread_path }` with best-effort values.
 * Either field may be '' / null when parsing fails — the read playbook
 * handles those gracefully (raises a clear validation error that
 * surfaces as a console.warn here).
 */
function parseWorkloadFromEventsPath(eventsPath: string | null | undefined): {
  user_uid: string | null;
  thread_path: string;
} {
  if (!eventsPath || !eventsPath.trim()) {
    return { user_uid: null, thread_path: '' };
  }

  const path = eventsPath.trim().replace(/^\/+/, '').replace(/\/+$/, '');

  // Shape: users/{user_uid}/trips/{trip_id}/events
  const usersMatch = /^users\/([^/]+)\/trips\/[^/]+\/events$/.exec(path);
  if (usersMatch) {
    return { user_uid: usersMatch[1], thread_path: '' };
  }

  // Shape: {thread_path}/trip/current/events
  // thread_path = everything before "/trip/current/events"
  const anonMatch = /^(.+)\/trip\/current\/events$/.exec(path);
  if (anonMatch) {
    return { user_uid: null, thread_path: anonMatch[1] };
  }

  // Unrecognised shape — pass as-is and let the playbook handle it.
  return { user_uid: null, thread_path: path };
}

/**
 * Extract `display_events` from the raw `executePlaybook` response.
 *
 * `executePlaybook` resolves to the envelope from the `playbook/result`
 * SSE frame.  The read playbook's final step emits:
 *   `{ display_events: [...], event_count: N, envelope: { ... } }`
 *
 * The gateway wraps it as `{ data: <that object>, ... }`.  We probe
 * both levels defensively.
 *
 * Returns the raw document array (one dict per Firestore document).
 * The caller's `toEvent(doc)` coercion handles field access.
 */
function parseDisplayEvents(result: unknown): CalendarDoc[] {
  if (!result || typeof result !== 'object') return [];

  const asRecord = result as Record<string, unknown>;

  // Prefer the top-level `data` key if present.
  const inner =
    asRecord.data && typeof asRecord.data === 'object'
      ? (asRecord.data as Record<string, unknown>)
      : asRecord;

  // Direct `display_events` key.
  if (Array.isArray(inner.display_events)) return inner.display_events as CalendarDoc[];

  // Nested under `envelope.payload.display_events`.
  const payload =
    inner.envelope &&
    typeof inner.envelope === 'object' &&
    (inner.envelope as Record<string, unknown>).payload;
  if (payload && typeof payload === 'object') {
    const events = (payload as Record<string, unknown>).display_events;
    if (Array.isArray(events)) return events as CalendarDoc[];
  }

  return [];
}

/**
 * subscribeToCalendarEvents
 *
 * Public API — drop-in replacement for the same-named export in
 * `gatewaySubscriptions.ts`.  The call site in `CalendarView.tsx`
 * changes from `subscribeToCalendarEvents(data.events_path, onItems)`
 * to `subscribeToCalendarEvents(data.trip_id, data.events_path, onItems)`.
 *
 * @param trip_id      Required.  The trip identifier, passed to the
 *                     read playbook so it can validate and route.
 * @param events_path  The Firestore collection path from the widget
 *                     payload.  Used to derive `user_uid` and
 *                     `thread_path` without changing `CalendarViewPayload`.
 *                     May be null or undefined — the module degrades
 *                     gracefully (console.warn, widget holds last state).
 * @param onItems      Callback invoked with the full document list after
 *                     each successful read.
 * @param options      Optional `{ signal }` for lifecycle management.
 * @returns            Unsubscribe function — removes the SSE listener
 *                     and aborts any in-flight playbook execution.
 */
export function subscribeToCalendarEvents(
  trip_id: string,
  events_path: string | null | undefined,
  onItems: (items: CalendarDoc[]) => void,
  options: CalendarSubscribeOptions = {}
): Unsubscribe {
  const controller = new AbortController();
  const sourceSignal = options.signal;
  let closed = false;
  let readInFlight = false;

  const abort = () => {
    controller.abort();
  };
  sourceSignal?.addEventListener('abort', abort, { once: true });

  // Derive workload fields once — they don't change during the
  // subscription lifetime.
  const { user_uid, thread_path } = parseWorkloadFromEventsPath(events_path);

  /**
   * Execute the read playbook and emit the result to `onItems`.
   *
   * Race handling: if a `playbook.completed` signal arrives while a
   * re-read is already in flight, we skip the new request (guarded by
   * `readInFlight`).  The in-flight read finishes shortly after and
   * emits the latest state — no events are lost because the read
   * playbook always returns the complete sorted list from Firestore.
   * This is "skip duplicate signal, trust latest read" rather than
   * debounce or strict FIFO serialization.  It is safe because the
   * read playbook is idempotent.
   */
  async function runRead(): Promise<void> {
    if (closed || readInFlight) return;
    readInFlight = true;
    try {
      const result = await executePlaybook(
        'travel/playbooks/catalog/calendar/list',
        {
          trip_id,
          thread_path: thread_path || '',
          user_uid: user_uid || null,
        },
        { signal: controller.signal }
      );
      if (!closed) {
        onItems(parseDisplayEvents(result));
      }
    } catch (error: unknown) {
      if (closed) return;
      if (error instanceof DOMException && error.name === 'AbortError') return;
      // Suppress transport errors — same policy as the old
      // `subscribeToCollection`: keep the widget in its current state
      // rather than showing a broken card on transient failures.
      console.warn('[calendarSubscription] read playbook error:', error);
    } finally {
      readInFlight = false;
    }
  }

  // Phase 1: initial read on mount.
  void runRead();

  // Phase 2: re-read whenever any playbook completes on the SSE channel.
  // The itinerary-planner that writes calendar events emits a
  // `playbook.completed` event when it finishes; that is the signal
  // the SPA uses to know the calendar may need refreshing.
  //
  // This listener is intentionally broad: any `playbook.completed`
  // event triggers a re-read, including completions from unrelated
  // playbooks (e.g. the calendar list playbook itself).  The read is
  // cheap and idempotent, so extra re-reads are acceptable.  A future
  // round can filter by checking that the completing execution belongs
  // to the itinerary-planner, once the widget payload carries a
  // `source_execution_id` field.
  const removeStateListener = addGatewaySSEListener('playbook/state', (event: MessageEvent) => {
    if (closed) return;
    try {
      const message = JSON.parse(event.data as string) as Record<string, unknown>;
      const params = (message?.params || {}) as Record<string, unknown>;
      const eventType = String(params.event_type || '').trim();
      if (eventType !== 'playbook.completed') return;
      void runRead();
    } catch {
      // Ignore malformed frames — same policy as handlePlaybookState.
    }
  });

  return () => {
    closed = true;
    sourceSignal?.removeEventListener('abort', abort);
    removeStateListener();
    controller.abort();
  };
}
