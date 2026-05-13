import type { ReactNode } from 'react';
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import {
  clearSession,
  getStoredSession,
  isGuestAllowed,
  loginToGateway,
  storeSession,
  validateGatewaySession
} from '../api/gatewaySession';
import { setSessionExpiredHandler } from '../api/noetlClient';
import { getAuthConfig } from './authConfig';

export interface MunoUser {
  sub?: string;
  name?: string;
  email?: string;
  picture?: string;
  [key: string]: unknown;
}

export interface MunoAuthState {
  isAuthConfigured: boolean;
  isAuthenticated: boolean;
  isLoading: boolean;
  isGatewayLinked: boolean;
  isLinkingGateway: boolean;
  allowGuest: boolean;
  canUseApp: boolean;
  gatewayError?: string;
  user?: MunoUser;
  login: () => Promise<void>;
  logout: () => void;
  getAccessToken: () => Promise<string | null>;
}

const AUTH_RETURN_TO_KEY = 'muno_auth_return_to';

const guestAuth: MunoAuthState = {
  isAuthConfigured: false,
  isAuthenticated: false,
  isLoading: false,
  isGatewayLinked: false,
  isLinkingGateway: false,
  allowGuest: isGuestAllowed(),
  canUseApp: isGuestAllowed(),
  login: async () => undefined,
  logout: () => undefined,
  getAccessToken: async () => null
};

const MunoAuthContext = createContext<MunoAuthState>(guestAuth);

function parseHashIdToken(hash = window.location.hash): string | null {
  if (!hash || hash.length < 2) return null;
  return new URLSearchParams(hash.slice(1)).get('id_token');
}

function base64UrlDecode(value: string): string {
  const base64 = value.replace(/-/g, '+').replace(/_/g, '/');
  const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, '=');
  return decodeURIComponent(
    atob(padded)
      .split('')
      .map((char) => `%${char.charCodeAt(0).toString(16).padStart(2, '0')}`)
      .join('')
  );
}

function userFromIdToken(idToken: string): MunoUser | undefined {
  const parts = idToken.split('.');
  if (parts.length < 2) return undefined;
  try {
    const claims = JSON.parse(base64UrlDecode(parts[1])) as MunoUser;
    return {
      sub: claims.sub,
      name: claims.name,
      email: claims.email,
      picture: claims.picture
    };
  } catch {
    return undefined;
  }
}

function buildAuthorizeUrl(returnTo: string): string {
  const config = getAuthConfig();
  if (!config) {
    throw new Error('Auth0 is not configured for this build');
  }

  sessionStorage.setItem(AUTH_RETURN_TO_KEY, returnTo);

  const redirectUri = `${window.location.origin}/callback`;
  const nonce = Math.random().toString(36).slice(2);
  const params = new URLSearchParams({
    response_type: 'id_token token',
    client_id: config.clientId,
    redirect_uri: redirectUri,
    scope: 'openid profile email',
    nonce
  });
  if (config.audience) {
    params.set('audience', config.audience);
  }

  return `https://${config.domain}/authorize?${params.toString()}`;
}

function clearAuthHash(returnTo?: string): void {
  const target = returnTo || `${window.location.pathname}${window.location.search}` || '/';
  window.history.replaceState({}, document.title, target);
}

function getReturnTo(): string {
  const stored = sessionStorage.getItem(AUTH_RETURN_TO_KEY);
  sessionStorage.removeItem(AUTH_RETURN_TO_KEY);
  if (!stored || !stored.startsWith('/')) return '/';
  return stored;
}

export function MunoAuthProvider({ children }: { children: ReactNode }) {
  const config = useMemo(() => getAuthConfig(), []);
  const allowGuest = isGuestAllowed();
  const [gatewayUser, setGatewayUser] = useState<MunoUser | undefined>();
  const [isLoading, setIsLoading] = useState(Boolean(config));
  const [isGatewayLinked, setIsGatewayLinked] = useState(false);
  const [isLinkingGateway, setIsLinkingGateway] = useState(false);
  const [gatewayError, setGatewayError] = useState<string | undefined>();

  useEffect(() => {
    setSessionExpiredHandler(() => {
      clearSession();
      setIsGatewayLinked(false);
      setGatewayUser(undefined);
      setGatewayError('session_expired');
    });
    return () => setSessionExpiredHandler(undefined);
  }, []);

  useEffect(() => {
    if (!config) return;
    let cancelled = false;

    const initialize = async () => {
      setIsLoading(true);
      setGatewayError(undefined);

      const idToken = parseHashIdToken();
      if (idToken) {
        setIsLinkingGateway(true);
        try {
          const gateway = await loginToGateway(idToken, config.domain);
          if (cancelled) return;
          const fallbackUser = userFromIdToken(idToken);
          storeSession(gateway.sessionToken, gateway.expiresAt, gateway.user || fallbackUser);
          setGatewayUser(gateway.user || fallbackUser);
          setIsGatewayLinked(true);
          clearAuthHash(getReturnTo());
        } catch (error) {
          if (cancelled) return;
          clearSession();
          clearAuthHash('/callback');
          setIsGatewayLinked(false);
          setGatewayUser(undefined);
          setGatewayError(error instanceof Error ? error.message : 'Gateway login failed');
        } finally {
          if (!cancelled) {
            setIsLinkingGateway(false);
            setIsLoading(false);
          }
        }
        return;
      }

      try {
        const existing = getStoredSession();
        if (existing?.token) {
          const validUser = await validateGatewaySession(existing.token);
          if (cancelled) return;
          if (validUser) {
            setGatewayUser(validUser);
            setIsGatewayLinked(true);
            return;
          }
          clearSession();
        } else if (!allowGuest) {
          clearSession();
        }
        if (!cancelled) {
          setIsGatewayLinked(false);
          setGatewayUser(undefined);
        }
      } catch (error) {
        if (!cancelled) {
          clearSession();
          setIsGatewayLinked(false);
          setGatewayUser(undefined);
          setGatewayError(error instanceof Error ? error.message : 'Gateway session validation failed');
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };

    void initialize();
    return () => {
      cancelled = true;
    };
  }, [allowGuest, config]);

  const login = useCallback(async () => {
    setGatewayError(undefined);
    const returnTo = `${window.location.pathname}${window.location.search}`;
    window.location.assign(buildAuthorizeUrl(returnTo === '/callback' ? '/' : returnTo));
  }, []);

  const logout = useCallback(() => {
    clearSession();
    setGatewayUser(undefined);
    setIsGatewayLinked(false);
    setGatewayError(undefined);
    window.location.assign('/');
  }, []);

  const getAccessToken = useCallback(async () => getStoredSession()?.token || null, []);

  const value = useMemo<MunoAuthState>(
    () => ({
      isAuthConfigured: Boolean(config),
      isAuthenticated: isGatewayLinked,
      isLoading,
      isGatewayLinked,
      isLinkingGateway,
      allowGuest,
      canUseApp: allowGuest || isGatewayLinked,
      gatewayError,
      user: gatewayUser,
      login,
      logout,
      getAccessToken
    }),
    [allowGuest, config, gatewayError, gatewayUser, getAccessToken, isGatewayLinked, isLinkingGateway, isLoading, login, logout]
  );

  return <MunoAuthContext.Provider value={value}>{children}</MunoAuthContext.Provider>;
}

export function useMunoAuth() {
  return useContext(MunoAuthContext);
}
