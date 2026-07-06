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
});
