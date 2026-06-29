import { afterEach, describe, expect, it, vi } from 'vitest';
import { withMapsKey } from './widgetUtils';

const KEY = 'BROWSER_KEY_123';

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('withMapsKey — append the browser key to keyless Google photo URLs', () => {
  it('appends the key to a keyless static-maps URL', () => {
    vi.stubEnv('VITE_GOOGLE_MAPS_KEY', KEY);
    const url = 'https://maps.googleapis.com/maps/api/staticmap?center=48.85%2C2.35&zoom=13';
    const out = withMapsKey(url);
    expect(out).toContain(`key=${KEY}`);
    expect(out.startsWith('https://maps.googleapis.com/maps/api/staticmap')).toBe(true);
  });

  it('appends the key to a keyless Places photo media URL', () => {
    vi.stubEnv('VITE_GOOGLE_MAPS_KEY', KEY);
    const url = 'https://places.googleapis.com/v1/places/X/photos/Y/media?maxWidthPx=400';
    expect(withMapsKey(url)).toContain(`key=${KEY}`);
  });

  it('does not double-add a key when one is already present', () => {
    vi.stubEnv('VITE_GOOGLE_MAPS_KEY', KEY);
    const url = 'https://maps.googleapis.com/maps/api/staticmap?center=1,2&key=EXISTING';
    const out = withMapsKey(url);
    expect(out).toBe(url);
    expect(out).not.toContain(KEY);
  });

  it('leaves non-Google hosts (e.g. HotelBeds) untouched', () => {
    vi.stubEnv('VITE_GOOGLE_MAPS_KEY', KEY);
    const url = 'https://photos.hotelbeds.com/giata/original/00/000001/000001a_hb_a_001.jpg';
    expect(withMapsKey(url)).toBe(url);
  });

  it('returns the url unchanged when no browser key is configured', () => {
    vi.stubEnv('VITE_GOOGLE_MAPS_KEY', '');
    const url = 'https://maps.googleapis.com/maps/api/staticmap?center=1,2';
    expect(withMapsKey(url)).toBe(url);
  });

  it('returns junk/non-URL input unchanged (no throw)', () => {
    vi.stubEnv('VITE_GOOGLE_MAPS_KEY', KEY);
    expect(withMapsKey('[REDACTED]')).toBe('[REDACTED]');
    expect(withMapsKey('')).toBe('');
  });
});
