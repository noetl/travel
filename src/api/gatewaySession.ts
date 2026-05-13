export interface GatewayUser {
  email?: string;
  display_name?: string;
  name?: string;
  sub?: string;
  roles?: string[];
  [key: string]: unknown;
}

export interface GatewaySession {
  token: string;
  expiresAt?: string;
  user?: GatewayUser;
}

export interface GatewayLoginResult {
  sessionToken: string;
  expiresAt?: string;
  user?: GatewayUser;
}

export const SESSION_TOKEN_KEY = 'session_token';
export const USER_INFO_KEY = 'user_info';

function stripTrailingSlash(value: string): string {
  return value.replace(/\/+$/, '');
}

function stripApiSuffix(value: string): string {
  return value.replace(/\/api\/?$/, '');
}

function deriveGatewayBaseFromHost(hostname: string): string {
  if (!hostname || hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '::1') {
    return 'https://gateway.mestumre.dev';
  }
  if (hostname === 'gateway.mestumre.dev' || hostname.startsWith('gateway.')) {
    return `https://${hostname}`;
  }
  const parts = hostname.split('.');
  if (parts.length >= 2) {
    return `https://gateway.${parts.slice(-2).join('.')}`;
  }
  return 'https://gateway.mestumre.dev';
}

export function getGatewayBaseUrl(): string {
  const explicit = import.meta.env.VITE_GATEWAY_BASE_URL?.trim();
  if (explicit) {
    return stripTrailingSlash(stripApiSuffix(explicit));
  }

  const apiBase = import.meta.env.VITE_NOETL_API_BASE_URL?.trim();
  if (apiBase) {
    return stripTrailingSlash(stripApiSuffix(apiBase));
  }

  if (typeof window !== 'undefined') {
    return deriveGatewayBaseFromHost(window.location.hostname);
  }

  return 'https://gateway.mestumre.dev';
}

export function getGatewayApiBaseUrl(): string {
  const explicitApi = import.meta.env.VITE_NOETL_API_BASE_URL?.trim();
  if (explicitApi) {
    return stripTrailingSlash(explicitApi);
  }
  return `${getGatewayBaseUrl()}/api`;
}

export function isGuestAllowed(): boolean {
  return import.meta.env.VITE_ALLOW_GUEST === 'true';
}

export function getStoredSession(): GatewaySession | null {
  const token = localStorage.getItem(SESSION_TOKEN_KEY);
  if (!token) return null;

  const userValue = localStorage.getItem(USER_INFO_KEY);
  let user: GatewayUser | undefined;
  if (userValue) {
    try {
      user = JSON.parse(userValue) as GatewayUser;
    } catch {
      user = undefined;
    }
  }

  return { token, user };
}

export function storeSession(token: string, expiresAt?: string, user?: GatewayUser): void {
  localStorage.setItem(SESSION_TOKEN_KEY, token);
  if (user) {
    localStorage.setItem(USER_INFO_KEY, JSON.stringify(user));
  }
  if (expiresAt) {
    localStorage.setItem(`${SESSION_TOKEN_KEY}_expires_at`, expiresAt);
  }
}

export function clearSession(): void {
  localStorage.removeItem(SESSION_TOKEN_KEY);
  localStorage.removeItem(USER_INFO_KEY);
  localStorage.removeItem(`${SESSION_TOKEN_KEY}_expires_at`);
}

export function withSessionHeader(headers: HeadersInit = {}, token: string): HeadersInit {
  return { ...headers, Authorization: `Bearer ${token}` };
}

export async function loginToGateway(auth0Token: string, auth0Domain: string): Promise<GatewayLoginResult> {
  const response = await fetch(`${getGatewayBaseUrl()}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      auth0_token: auth0Token,
      auth0_domain: auth0Domain
    })
  });

  if (!response.ok) {
    let detail = '';
    try {
      const payload = await response.json();
      detail = payload?.error || payload?.message || JSON.stringify(payload);
    } catch {
      try {
        detail = (await response.text()).slice(0, 300);
      } catch {
        detail = '';
      }
    }
    throw new Error(detail ? `Gateway login failed (${response.status}): ${detail}` : `Gateway login failed (${response.status})`);
  }

  const data = (await response.json()) as {
    session_token?: string;
    expires_at?: string;
    user?: GatewayUser;
  };

  if (!data.session_token) {
    throw new Error('Gateway login did not return a session token');
  }

  return {
    sessionToken: data.session_token,
    expiresAt: data.expires_at,
    user: data.user
  };
}

export async function validateGatewaySession(token: string): Promise<GatewayUser | null> {
  const response = await fetch(`${getGatewayBaseUrl()}/api/auth/validate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_token: token })
  });

  if (!response.ok) return null;

  const data = (await response.json()) as { valid?: boolean; user?: GatewayUser };
  if (!data.valid) return null;
  return data.user || null;
}
