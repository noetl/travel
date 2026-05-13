import { describe, expect, it } from 'vitest';
import { getAuthConfig } from './authConfig';

describe('getAuthConfig', () => {
  it('falls back to the GUI Auth0 SPA config when env values are absent', () => {
    expect(getAuthConfig({} as ImportMetaEnv)).toMatchObject({
      domain: 'mestumre-development.us.auth0.com',
      clientId: 'Jqop7YoaiZalLHdBRo5ScNQ1RJhbhbDN'
    });
  });

  it('uses explicit Vite env overrides when provided', () => {
    expect(
      getAuthConfig({
        VITE_AUTH0_DOMAIN: 'example.auth0.com',
        VITE_AUTH0_CLIENT_ID: 'client-id',
        VITE_AUTH0_AUDIENCE: 'https://api.example.test'
      } as unknown as ImportMetaEnv)
    ).toEqual({
      domain: 'example.auth0.com',
      clientId: 'client-id'
    });
  });
});
