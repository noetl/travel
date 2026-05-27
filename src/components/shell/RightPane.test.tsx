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

  it('shows region label from flat region_label key when nested region object is absent', () => {
    // Bug C: playbook final_slot_state may carry region_label / region_city_code
    // as flat scalars without a nested region object when only the scalar path
    // populated the state.  The panel must still show the region label.
    const html = renderToStaticMarkup(
      <RightPane
        slotState={{
          region_label: 'Paris',
          region_city_code: 'PAR',
          region_country_code: 'FR',
          region_kind: 'city',
          check_in_date: '2026-06-17',
          check_out_date: '2026-06-21',
          party: { adults: 1, children: [], rooms: 1 }
        }}
      />
    );

    expect(html).toContain('Region');
    expect(html).toContain('Paris');
    expect(html).toContain('Dates');
    expect(html).toContain('2026-06-17');
    expect(html).toContain('Party');
  });

  it('shows region label from nested region object when both nested and flat keys are present', () => {
    // Both paths populated (normalise_region_fields sets both).
    // The nested region.label takes precedence.
    const html = renderToStaticMarkup(
      <RightPane
        slotState={{
          region: { label: 'Paris', city_code: 'PAR', country_code: 'FR', kind: 'city' },
          region_label: 'Paris',
          region_city_code: 'PAR',
          check_in_date: '2026-06-17',
          check_out_date: '2026-06-21',
          party: { adults: 2, children: [], rooms: 1 }
        }}
      />
    );

    expect(html).toContain('Paris');
    expect(html).toContain('2026-06-17');
  });

  it('shows dates when populated', () => {
    const html = renderToStaticMarkup(
      <RightPane
        slotState={{
          check_in_date: '2026-08-10',
          check_out_date: '2026-08-14'
        }}
      />
    );
    expect(html).toContain('2026-08-10');
    expect(html).toContain('2026-08-14');
  });
});
