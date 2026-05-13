export interface AuthConfig {
  domain: string;
  clientId: string;
  audience?: string;
}

export function getAuthConfig(env: ImportMetaEnv = import.meta.env): AuthConfig | null {
  const domain = env.VITE_AUTH0_DOMAIN?.trim();
  const clientId = env.VITE_AUTH0_CLIENT_ID?.trim();
  const audience = env.VITE_AUTH0_AUDIENCE?.trim();

  if (!domain || !clientId) return null;
  return { domain, clientId, audience: audience || undefined };
}
