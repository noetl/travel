export interface TravellerParty {
  adults?: number | null;
  children?: Array<{ age?: number | null }> | null;
  rooms?: number | null;
}

function plural(value: number, singular: string, pluralLabel = `${singular}s`) {
  return `${value} ${value === 1 ? singular : pluralLabel}`;
}

export function formatParty(party: TravellerParty | null | undefined): string {
  if (!party) return '';

  const parts: string[] = [];
  const adults = Number(party.adults || 0);
  if (adults > 0) {
    parts.push(plural(adults, 'adult'));
  }

  const children = Array.isArray(party.children) ? party.children : [];
  if (children.length > 0) {
    const ages = children
      .map((child) => (child?.age === null || child?.age === undefined ? null : `${child.age} yr${child.age === 1 ? '' : 's'}`))
      .filter(Boolean);
    parts.push(`${plural(children.length, 'child', 'children')}${ages.length ? ` (${ages.join(', ')})` : ''}`);
  }

  const rooms = Number(party.rooms || 0);
  if (rooms > 1) {
    parts.push(plural(rooms, 'room'));
  }

  return parts.join(' · ');
}

export function formatPossibleParty(value: unknown): string | null {
  if (!value) return null;
  if (typeof value === 'object') {
    return formatParty(value as TravellerParty) || null;
  }
  if (typeof value === 'string' && value.trim().startsWith('{')) {
    try {
      return formatParty(JSON.parse(value) as TravellerParty) || null;
    } catch {
      return null;
    }
  }
  return null;
}
