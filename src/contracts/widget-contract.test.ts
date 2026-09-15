import { describe, expect, it } from 'vitest';
import Ajv from 'ajv';
import addFormats from 'ajv-formats';
import sampleEnvelopes from './sampleEnvelopes.json';
import { WIDGET_TYPES } from './widgets';
import flightCardSchema from '../../playbooks/widget-contract/flight_card.schema.json';
import hotelCardSchema from '../../playbooks/widget-contract/hotel_card.schema.json';
import itinerarySummarySchema from '../../playbooks/widget-contract/itinerary_summary.schema.json';

describe('widget contract fixtures', () => {
  it('keeps one sample envelope for every widget type', () => {
    const sampleTypes = new Set(sampleEnvelopes.map((item) => item.widget_type));

    // Every widget type still has at least one sample. The count is derived
    // rather than hardcoded so adding a version-N sample for an existing type
    // does not read as a missing widget (adiona/frontend#21 added a schema_version
    // 2 flight_card alongside the version 1 one).
    expect(sampleTypes).toEqual(new Set(WIDGET_TYPES));
    expect(sampleEnvelopes.length).toBeGreaterThanOrEqual(WIDGET_TYPES.length);
  });

  it('keeps the version-2 flight_card sample alongside the version-1 one', () => {
    // schema_version 2 is ADDITIVE: version 1 payloads stay valid, so both
    // versions must keep validating for the whole migration window.
    const flightCards = sampleEnvelopes.filter((item) => item.widget_type === 'flight_card');
    expect(new Set(flightCards.map((item) => item.schema_version))).toEqual(new Set([1, 2]));

    const ajv = new Ajv({ allErrors: true, strict: false });
    addFormats(ajv);
    const validate = ajv.compile(flightCardSchema);
    for (const card of flightCards) {
      expect(validate(card.payload), ajv.errorsText(validate.errors)).toBe(true);
    }
  });

  it('requires numeric hotel fields inside itinerary summaries', () => {
    const ajv = new Ajv({ allErrors: true, strict: false });
    addFormats(ajv);
    ajv.addSchema(flightCardSchema);
    ajv.addSchema(hotelCardSchema);
    const validate = ajv.compile(itinerarySummarySchema);
    const base = {
      destination: 'Paris',
      dates: { from: '2026-08-01', to: '2026-08-05' },
      traveller_party: { adults: 2 },
      picked_hotel: {
        hotel_id: 'hotel_1',
        name: 'Central Stay',
        score: 8.7,
        photos: [],
        amenities: [],
        currency: 'EUR'
      }
    };

    expect(validate({
      ...base,
      picked_hotel: {
        ...base.picked_hotel,
        price_per_night: '180',
        location: { lat: '48.85', lng: '2.35', city: 'Paris' }
      }
    })).toBe(false);

    expect(validate({
      ...base,
      picked_hotel: {
        ...base.picked_hotel,
        price_per_night: 180,
        location: { lat: 48.85, lng: 2.35, city: 'Paris' }
      }
    })).toBe(true);
  });
});
