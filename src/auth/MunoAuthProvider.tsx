import { Auth0Provider, useAuth0 } from '@auth0/auth0-react';
import type { ReactNode } from 'react';
import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { setSessionExpiredHandler } from '../api/noetlClient';
import {
  clearSession,
  getStoredSession,
  isGuestAllowed,
  loginToGateway,
  storeSession,
  validateGatewaySession
} from '../api/gatewaySession';
import { getAuthConfig } from './authConfig';

export interface MunoUser {
  sub?: string;
  name?: string;
  email?: string;
  picture?: string;
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

function AuthBridge({ children }: { children: ReactNode }) {
  const config = getAuthConfig();
  const {
    getAccessTokenSilently,
    getIdTokenClaims,
    isAuthenticated,
    isLoading,
    loginWithRedirect,
    logout,
    user
  } = useAuth0();
  const [gatewayUser, setGatewayUser] = useState<MunoUser | undefined>();
  const [isGatewayLinked, setIsGatewayLinked] = useState(false);
  const [isLinkingGateway, setIsLinkingGateway] = useState(false);
  const [gatewayError, setGatewayError] = useState<string | undefined>();
  const linkInFlight = useRef(false);
  const allowGuest = isGuestAllowed();

  const audience = config?.audience;
  const getAccessToken = useMemo(
    () => async () => {
      if (!isAuthenticated) return null;
      return getAccessTokenSilently(
        audience
          ? {
              authorizationParams: { audience }
            }
          : undefined
      );
    },
    [audience, getAccessTokenSilently, isAuthenticated]
  );

  useEffect(() => {
    setSessionExpiredHandler(() => {
      setIsGatewayLinked(false);
      setGatewayUser(undefined);
      setGatewayError('session_expired');
    });
    return () => setSessionExpiredHandler(undefined);
  }, []);

  useEffect(() => {
    if (isLoading) return;

    if (!isAuthenticated) {
      if (!allowGuest) {
        clearSession();
      }
      setIsGatewayLinked(false);
      setGatewayUser(undefined);
      setGatewayError(undefined);
      return;
    }

    if (linkInFlight.current) return;

    const linkGateway = async () => {
      linkInFlight.current = true;
      setIsLinkingGateway(true);
      setGatewayError(undefined);

      try {
        const existing = getStoredSession();
        if (existing?.token) {
          const validUser = await validateGatewaySession(existing.token);
          if (validUser) {
            setGatewayUser(validUser);
            setIsGatewayLinked(true);
            return;
          }
          clearSession();
        }

        const claims = await getIdTokenClaims();
        const rawIdToken = claims?.__raw;
        if (!rawIdToken) {
          throw new Error('Auth0 did not return an ID token for gateway login');
        }

        const gateway = await loginToGateway(rawIdToken, config?.domain || '');
        storeSession(gateway.sessionToken, gateway.expiresAt, gateway.user);
        setGatewayUser(gateway.user);
        setIsGatewayLinked(true);
      } catch (error) {
        clearSession();
        setIsGatewayLinked(false);
        setGatewayUser(undefined);
        setGatewayError(error instanceof Error ? error.message : 'Gateway login failed');
      } finally {
        setIsLinkingGateway(false);
        linkInFlight.current = false;
      }
    };

    void linkGateway();
  }, [allowGuest, config?.domain, getIdTokenClaims, isAuthenticated, isLoading]);

  const value = useMemo<MunoAuthState>(
    () => ({
      isAuthConfigured: true,
      isAuthenticated: isAuthenticated && isGatewayLinked,
      isLoading,
      isGatewayLinked,
      isLinkingGateway,
      allowGuest,
      canUseApp: allowGuest || (isAuthenticated && isGatewayLinked),
      gatewayError,
      user: gatewayUser || (user
        ? {
            sub: user.sub,
            name: user.name,
            email: user.email,
            picture: user.picture
          }
        : undefined),
      login: () =>
        loginWithRedirect({
          appState: { returnTo: window.location.pathname + window.location.search },
          authorizationParams: audience ? { audience } : undefined
        }),
      logout: () => {
        clearSession();
        setIsGatewayLinked(false);
        setGatewayUser(undefined);
        logout({ logoutParams: { returnTo: window.location.origin } });
      },
      getAccessToken
    }),
    [
      allowGuest,
      audience,
      gatewayError,
      gatewayUser,
      getAccessToken,
      isAuthenticated,
      isGatewayLinked,
      isLinkingGateway,
      isLoading,
      loginWithRedirect,
      logout,
      user
    ]
  );

  return <MunoAuthContext.Provider value={value}>{children}</MunoAuthContext.Provider>;
}

export function MunoAuthProvider({ children }: { children: ReactNode }) {
  const config = getAuthConfig();
  if (!config) {
    return <MunoAuthContext.Provider value={guestAuth}>{children}</MunoAuthContext.Provider>;
  }

  return (
    <Auth0Provider
      domain={config.domain}
      clientId={config.clientId}
      cacheLocation="localstorage"
      useRefreshTokens
      authorizationParams={{
        redirect_uri: `${window.location.origin}/callback`,
        ...(config.audience ? { audience: config.audience } : {})
      }}
      onRedirectCallback={(appState) => {
        window.history.replaceState({}, document.title, appState?.returnTo || '/');
      }}
    >
      <AuthBridge>{children}</AuthBridge>
    </Auth0Provider>
  );
}

export function useMunoAuth() {
  return useContext(MunoAuthContext);
}
