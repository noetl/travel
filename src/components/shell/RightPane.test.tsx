import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import '../../i18n';
import { RightPane } from './RightPane';

describe('RightPane', () => {
  it('surfaces all captured trip slots', () => {
    const html = renderToStaticMarkup(
      <RightPane
        slotState={{
          region: { label: 'Paris' },
          check_in_date: '2026-07-01',
          check_out_date: '2026-07-05',
          party: { adults: 2, children: [{ age: 3 }], rooms: 1 },
          star_rating_min: 4,
          budget_min: { amount: 1200, currency: 'USD' },
          budget_max: { amount: 2400, currency: 'USD' },
          bed_type: 'king',
          amenities_required: ['wifi', 'breakfast']
        }}
      />
    );

    expect(html).toContain('Region');
    expect(html).toContain('Paris');
    expect(html).toContain('Dates');
    expect(html).toContain('2026-07-01');
    expect(html).toContain('Party');
    expect(html).toContain('2 adults');
    expect(html).toContain('1 child');
    expect(html).toContain('Star rating');
    expect(html).toContain('4+');
    expect(html).toContain('Budget');
    expect(html).toContain('USD 1200');
    expect(html).toContain('USD 2400');
    expect(html).toContain('Bed type');
    expect(html).toContain('king');
    expect(html).toContain('Amenities');
    expect(html).toContain('wifi, breakfast');
  });
});
