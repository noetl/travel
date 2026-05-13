import { Auth0Provider, useAuth0 } from '@auth0/auth0-react';
import type { ReactNode } from 'react';
import { createContext, useContext, useEffect, useMemo } from 'react';
import { setAccessTokenProvider } from '../api/noetlClient';
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
  user?: MunoUser;
  login: () => Promise<void>;
  logout: () => void;
  getAccessToken: () => Promise<string | null>;
}

const guestAuth: MunoAuthState = {
  isAuthConfigured: false,
  isAuthenticated: false,
  isLoading: false,
  login: async () => undefined,
  logout: () => undefined,
  getAccessToken: async () => null
};

const MunoAuthContext = createContext<MunoAuthState>(guestAuth);

function AuthBridge({ children }: { children: ReactNode }) {
  const config = getAuthConfig();
  const {
    getAccessTokenSilently,
    isAuthenticated,
    isLoading,
    loginWithRedirect,
    logout,
    user
  } = useAuth0();

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
    setAccessTokenProvider(isAuthenticated ? getAccessToken : undefined);
    return () => setAccessTokenProvider(undefined);
  }, [getAccessToken, isAuthenticated]);

  const value = useMemo<MunoAuthState>(
    () => ({
      isAuthConfigured: true,
      isAuthenticated,
      isLoading,
      user: user
        ? {
            sub: user.sub,
            name: user.name,
            email: user.email,
            picture: user.picture
          }
        : undefined,
      login: () =>
        loginWithRedirect({
          appState: { returnTo: window.location.pathname + window.location.search },
          authorizationParams: audience ? { audience } : undefined
        }),
      logout: () => logout({ logoutParams: { returnTo: window.location.origin } }),
      getAccessToken
    }),
    [audience, getAccessToken, isAuthenticated, isLoading, loginWithRedirect, logout, user]
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
