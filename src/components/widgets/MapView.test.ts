import { afterEach, describe, expect, it, vi } from 'vitest';
import { buildStaticMapUrl } from './MapView';
import type { MapViewPayload } from '../../contracts/widgets';

const KEY = 'BROWSER_KEY_123';

const payload: MapViewPayload = {
  center: { lat: 48.8566, lng: 2.3522 },
  zoom: 12,
  markers: [
    { lat: 48.86, lng: 2.35, label: 'Hotel A', hotel_id: 'a', state: 'normal' },
    { lat: 48.87, lng: 2.34, label: 'Hotel B', hotel_id: 'b', state: 'selected' }
  ]
};

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('buildStaticMapUrl — graceful static-map fallback for map_view', () => {
  it('builds a keyed Static Maps URL from the payload center/zoom', () => {
    vi.stubEnv('VITE_GOOGLE_MAPS_KEY', KEY);
    const url = buildStaticMapUrl(payload);
    expect(url.startsWith('https://maps.googleapis.com/maps/api/staticmap')).toBe(true);
    expect(url).toContain('center=48.8566%2C2.3522');
    expect(url).toContain('zoom=12');
    expect(url).toContain(`key=${KEY}`);
  });

  it('adds one marker parameter per payload marker', () => {
    vi.stubEnv('VITE_GOOGLE_MAPS_KEY', KEY);
    const url = new URL(buildStaticMapUrl(payload));
    expect(url.searchParams.getAll('markers')).toHaveLength(2);
  });

  it('returns a keyless URL when no key is configured (still a valid static-map URL)', () => {
    vi.stubEnv('VITE_GOOGLE_MAPS_KEY', '');
    const url = buildStaticMapUrl(payload);
    expect(url.startsWith('https://maps.googleapis.com/maps/api/staticmap')).toBe(true);
    expect(url).not.toContain('key=');
  });
});
