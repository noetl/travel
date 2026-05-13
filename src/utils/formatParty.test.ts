import { describe, expect, it } from 'vitest';
import { formatParty, formatPossibleParty } from './formatParty';

describe('formatParty', () => {
  it('returns an empty string for nullish input', () => {
    expect(formatParty(null)).toBe('');
    expect(formatParty(undefined)).toBe('');
  });

  it('formats adults without children or rooms', () => {
    expect(formatParty({ adults: 1, children: [], rooms: 1 })).toBe('1 adult');
    expect(formatParty({ adults: 2, children: [], rooms: 1 })).toBe('2 adults');
  });

  it('formats children with ages', () => {
    expect(formatParty({ adults: 2, children: [{ age: 3 }], rooms: 1 })).toBe('2 adults · 1 child (3 yrs)');
    expect(formatParty({ adults: 2, children: [{ age: 3 }, { age: 7 }], rooms: 2 })).toBe(
      '2 adults · 2 children (3 yrs, 7 yrs) · 2 rooms'
    );
  });

  it('handles missing child ages and missing rooms', () => {
    expect(formatParty({ adults: 1, children: [{}] })).toBe('1 adult · 1 child');
  });

  it('formats JSON-encoded party slot values', () => {
    expect(formatPossibleParty('{"adults":2,"children":[{"age":3}],"rooms":1}')).toBe('2 adults · 1 child (3 yrs)');
  });
});
