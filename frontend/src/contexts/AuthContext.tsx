/**
 * AuthContext — application-level authentication state (M1-AUTH-3).
 *
 * Responsibilities:
 *   - Holds the current user identity (UserPublic | null) and CSRF token.
 *   - Performs a silent GET /auth/me on mount to restore session from cookie.
 *   - Exposes login(), logout(), and register() actions that update state.
 *   - Never stores the JWT directly; reads CSRF from login response body
 *     and keeps it in memory so state-changing requests can include it.
 *
 * Usage:
 *   Wrap <App /> with <AuthProvider>. Consume with useAuth().
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';

import {
  type UserPublic,
  apiLogin,
  apiLogout,
  apiMe,
  apiRegister,
  readCsrfCookie,
} from '../api/auth';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AuthState {
  /** Null while loading or unauthenticated. */
  user: UserPublic | null;
  /** True only during the initial session-restore fetch. */
  isLoading: boolean;
  /** In-memory CSRF token; sourced from login response or cookie. */
  csrfToken: string | null;
}

export interface AuthActions {
  login(email: string, password: string): Promise<void>;
  logout(): Promise<void>;
  register(email: string, displayName: string, password: string): Promise<UserPublic>;
}

const AuthContext = createContext<(AuthState & AuthActions) | undefined>(undefined);

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserPublic | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [csrfToken, setCsrfToken] = useState<string | null>(null);

  // On mount: attempt silent session restore via /auth/me.
  // If the HttpOnly cookie is present and valid the server returns the user.
  useEffect(() => {
    let cancelled = false;
    apiMe()
      .then((u) => {
        if (!cancelled) {
          setUser(u);
          // Re-read the CSRF cookie — it was set at login time and survives
          // page reloads because it is a regular (non-HttpOnly) cookie.
          setCsrfToken(readCsrfCookie());
        }
      })
      .catch(() => {
        // 401 = no valid session; this is the normal unauthenticated path.
        if (!cancelled) {
          setUser(null);
          setCsrfToken(null);
        }
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const resp = await apiLogin(email, password);
    setUser(resp.user);
    setCsrfToken(resp.csrf_token);
  }, []);

  const logout = useCallback(async () => {
    const token = csrfToken ?? readCsrfCookie() ?? '';
    await apiLogout(token);
    setUser(null);
    setCsrfToken(null);
  }, [csrfToken]);

  const register = useCallback(
    async (email: string, displayName: string, password: string): Promise<UserPublic> => {
      return apiRegister(email, displayName, password);
    },
    [],
  );

  return (
    <AuthContext.Provider value={{ user, isLoading, csrfToken, login, logout, register }}>
      {children}
    </AuthContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useAuth(): AuthState & AuthActions {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used inside <AuthProvider>');
  }
  return ctx;
}
