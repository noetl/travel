import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { CalendarView } from './CalendarView';

const sampleEvent = {
  event_id: 'evt_1',
  type: 'flight_depart' as const,
  start_at: '2026-07-15T08:00:00-07:00',
  end_at: null,
  timezone: 'America/Los_Angeles',
  title: 'Depart SFO',
  location: 'SFO',
  notes: 'Duffel test order segment',
  source_order_id: 'ord_1',
  source_hotel_id: null,
  google_calendar_event_id: null
};

describe('CalendarView', () => {
  it('renders static display_events mode', () => {
    const html = renderToStaticMarkup(
      <CalendarView
        payload={{
          trip_id: 'trip_1',
          events_path: 'chat_threads/_smoke-calendar/trip/current/events',
          display_events: [sampleEvent],
          editable: true
        }}
        variantId="compact"
      />
    );

    expect(html).toContain('Depart SFO');
    expect(html).toContain('Flight departs');
  });

  it('renders live events_path mode without Firestore config', () => {
    const html = renderToStaticMarkup(
      <CalendarView
        payload={{
          trip_id: 'trip_1',
          events_path: 'chat_threads/_smoke-calendar/trip/current/events',
          editable: false,
          empty_state_text: 'No schedule yet'
        }}
        variantId="full"
      />
    );

    expect(html).toContain('No schedule yet');
  });
});
