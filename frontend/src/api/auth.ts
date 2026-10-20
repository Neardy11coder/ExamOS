/**
 * Authentication API client (M1-AUTH-3).
 *
 * Contracts (docs/04_API_CONTRACT.md §2, backend/app/api/v1/endpoints/auth.py):
 *   POST /api/v1/auth/register  → 201 RegisterResponse | 409
 *   POST /api/v1/auth/login     → 200 LoginResponse + cookies | 401
 *   POST /api/v1/auth/logout    → 204 (requires X-CSRF-Token header)
 *   GET  /api/v1/auth/me        → 200 UserPublic | 401
 *
 * CSRF: the backend sets a JS-readable cookie `examos_csrf` on login.
 * State-changing requests (logout) must echo it as `X-CSRF-Token`.
 * The cookie value is also returned in the LoginResponse body for
 * immediate use before the next page load re-reads the cookie.
 */

const BASE = '/api/v1';

export interface UserPublic {
  id: string;
  email: string;
  display_name: string;
  role: string;
}

export interface LoginResponse {
  user: UserPublic;
  csrf_token: string;
}

export interface RegisterResponse extends UserPublic {}

/** Read the CSRF token from the JS-readable cookie set by the backend. */
export function readCsrfCookie(): string | null {
  const match = document.cookie
    .split('; ')
    .find((row) => row.startsWith('examos_csrf='));
  return match ? decodeURIComponent(match.split('=')[1]) : null;
}

/** Extract the structured error message from a failed response, if available. */
async function extractErrorMessage(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json();
    return (
      body?.detail?.error?.message ??
      body?.detail?.message ??
      body?.message ??
      fallback
    );
  } catch {
    return fallback;
  }
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly code?: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export async function apiRegister(
  email: string,
  displayName: string,
  password: string,
): Promise<RegisterResponse> {
  const res = await fetch(`${BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ email, display_name: displayName, password }),
  });
  if (!res.ok) {
    const msg = await extractErrorMessage(
      res,
      res.status === 409
        ? 'Registration could not be completed. Check your details and try again.'
        : 'Registration failed. Please try again.',
    );
    throw new ApiError(res.status, msg);
  }
  return res.json();
}

export async function apiLogin(
  email: string,
  password: string,
): Promise<LoginResponse> {
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const msg = await extractErrorMessage(res, 'Invalid email or password.');
    throw new ApiError(res.status, msg);
  }
  return res.json();
}

export async function apiLogout(csrfToken: string): Promise<void> {
  const res = await fetch(`${BASE}/auth/logout`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': csrfToken,
    },
    credentials: 'include',
  });
  if (res.status !== 204 && !res.ok) {
    throw new ApiError(res.status, 'Logout failed.');
  }
}

export async function apiMe(): Promise<UserPublic> {
  const res = await fetch(`${BASE}/auth/me`, {
    method: 'GET',
    credentials: 'include',
  });
  if (!res.ok) {
    throw new ApiError(res.status, 'Not authenticated.');
  }
  return res.json();
}
