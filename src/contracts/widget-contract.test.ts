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

    expect(sampleEnvelopes).toHaveLength(27);
    expect(sampleTypes).toEqual(new Set(WIDGET_TYPES));
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
