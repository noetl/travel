import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { WidgetRenderer } from './WidgetRenderer';

describe('WidgetRenderer', () => {
  it('renders HotelBeds activity lists', () => {
    const html = renderToStaticMarkup(
      <WidgetRenderer
        envelope={{
          widget_type: 'activity_list',
          variant: 'default',
          schema_version: 1,
          payload: {
            title: 'Things to do',
            items: [{
              activity_code: 'act_1',
              name: 'Seine River Cruise',
              type: 'TICKET',
              country: 'France',
              currency: 'EUR',
              amount_from: 35,
              modalities_count: 2,
              description: 'Scenic cruise past Paris landmarks.',
              ctas: ['view_details', 'add_to_itinerary']
            }],
            total_count: 1,
            filter_summary: 'Paris, 2 travellers'
          }
        }}
      />
    );

    expect(html).toContain('Things to do');
    expect(html).toContain('Seine River Cruise');
    expect(html).not.toContain('unknown widget_type');
  });

  it('renders HotelBeds transfer lists', () => {
    const html = renderToStaticMarkup(
      <WidgetRenderer
        envelope={{
          widget_type: 'transfer_list',
          variant: 'default',
          schema_version: 1,
          payload: {
            title: 'Airport transfers',
            items: [{
              transfer_id: 'xfer_1',
              transfer_type: 'SHARED',
              vehicle_name: 'Shared shuttle',
              category_name: 'Shared',
              total_amount: 44.4,
              currency: 'EUR',
              direction: 'DEPARTURE',
              detail: 'CDG to Paris city centre.',
              ctas: ['view_details', 'add_to_itinerary']
            }],
            total_count: 1,
            route_summary: 'CDG to Paris'
          }
        }}
      />
    );

    expect(html).toContain('Airport transfers');
    expect(html).toContain('Shared shuttle');
    expect(html).not.toContain('unknown widget_type');
  });

  // Prod execution 368219441512587264 (2026-10-13): the "No matching flights"
  // card carried `message`/`ctas` and no `description`, so the booking flow
  // showed this fallback instead of the card.
  const noFlights = {
    title: 'No matching flights',
    reason_code: 'no_flight_results',
    blocking_constraints: [],
    alternatives: ['flexible_dates', 'nearby_airports'],
  };

  it('rejects the error_card shape prod emitted (message/ctas, no description)', () => {
    const html = renderToStaticMarkup(
      <WidgetRenderer
        envelope={{
          widget_type: 'error_card',
          variant: 'default',
          schema_version: 1,
          payload: { ...noFlights, message: 'The airline search returned no flights.', ctas: ['flexible_dates'] }
        }}
      />
    );
    expect(html).toContain('template mismatch');
  });

  it('renders the planner error_card with description and its machine-readable fields', () => {
    const html = renderToStaticMarkup(
      <WidgetRenderer
        envelope={{
          widget_type: 'error_card',
          variant: 'default',
          schema_version: 1,
          payload: {
            ...noFlights,
            description: 'The airline search returned no flights for this route and date.',
            retry_action_id: 'retry:mcp/duffel.search_offers',
            contact_support: false
          }
        }}
      />
    );
    expect(html).not.toContain('template mismatch');
    expect(html).toContain('No matching flights');
    expect(html).toContain('returned no flights');
  });

  it('renders a flight_list that carries the ranked groups', () => {
    const html = renderToStaticMarkup(
      <WidgetRenderer
        envelope={{
          widget_type: 'flight_list',
          variant: 'default',
          schema_version: 1,
          payload: {
            title: 'Flight options',
            items: [],
            total_count: 0,
            currency: 'USD',
            groups: { best_value: { offer_id: 'off_1' } }
          }
        }}
      />
    );
    expect(html).not.toContain('template mismatch');
  });
});
