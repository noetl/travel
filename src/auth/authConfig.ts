export interface AuthConfig {
  domain: string;
  clientId: string;
  audience?: string;
}

const DEFAULT_AUTH0_DOMAIN = 'mestumre-development.us.auth0.com';
const DEFAULT_AUTH0_CLIENT_ID = 'Jqop7YoaiZalLHdBRo5ScNQ1RJhbhbDN';

export function getAuthConfig(env: ImportMetaEnv = import.meta.env): AuthConfig | null {
  const domain = env.VITE_AUTH0_DOMAIN?.trim() || DEFAULT_AUTH0_DOMAIN;
  const clientId = env.VITE_AUTH0_CLIENT_ID?.trim() || DEFAULT_AUTH0_CLIENT_ID;
  const audience = env.VITE_AUTH0_AUDIENCE?.trim();

  return { domain, clientId, audience: audience || undefined };
}
