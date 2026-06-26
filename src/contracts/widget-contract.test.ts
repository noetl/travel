import { describe, expect, it } from 'vitest';
import sampleEnvelopes from './sampleEnvelopes.json';
import { WIDGET_TYPES } from './widgets';

describe('widget contract fixtures', () => {
  it('keeps one sample envelope for every widget type', () => {
    const sampleTypes = new Set(sampleEnvelopes.map((item) => item.widget_type));

    expect(sampleEnvelopes).toHaveLength(26);
    expect(sampleTypes).toEqual(new Set(WIDGET_TYPES));
  });
});
