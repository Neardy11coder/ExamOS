/**
 * Cloudflare Pages Function Reverse Proxy for ExamOS API
 *
 * Route: /api/* -> BACKEND_ORIGIN/api/*
 *
 * Security & Reliability Requirements:
 * 1. Origin Validation:
 *    - Validates BACKEND_ORIGIN environment variable.
 *    - Rejects origin containing credentials (username/password), query strings, or hash fragments.
 *    - Requires HTTPS in production (non-localhost).
 *    - Rejects any client-controlled redirection of backend destination.
 * 2. Request Integrity:
 *    - Preserves HTTP methods (GET, POST, PUT, PATCH, DELETE, OPTIONS, HEAD).
 *    - Preserves URL path and raw search / query string parameters.
 *    - Preserves request payloads for methods with bodies.
 *    - Forwards authentication (`Authorization`) and CSRF tokens (`X-CSRF-Token`).
 * 3. Header Sanitization:
 *    - Strips hop-by-hop headers (RFC 7230 §6.1) including any headers nominated
 *      in the incoming `Connection` header.
 *    - Strips incoming `Host` header to ensure upstream receives correct target host.
 *    - Forwards client IP via `CF-Connecting-IP` as `X-Forwarded-For`.
 *    - Sets `X-Forwarded-Host` and `X-Forwarded-Proto`.
 * 4. Cookie Integrity:
 *    - Preserves multiple `Set-Cookie` headers independently using `response.headers.getSetCookie()`.
 *    - Accurately strips upstream `Domain=` attributes (without breaking other attributes or trailing semicolons)
 *      so cookies attach strictly to the Cloudflare Pages frontend host.
 *    - Preserves all cookie security attributes: HttpOnly, Secure, SameSite, Max-Age, Path, Expires.
 * 5. Safe Response & Error Handling:
 *    - Returns generic 502 Bad Gateway upon upstream network failure or timeout without leaking internals or credentials.
 *    - Never logs tokens, cookies, or secrets.
 *    - Handles redirects safely without automatic following (`redirect: 'manual'`).
 */

interface Env {
  BACKEND_ORIGIN: string;
}

interface PagesFunctionEvent {
  request: Request;
  env: Env;
  params: Record<string, string | string[]>;
  waitUntil: (promise: Promise<unknown>) => void;
  next: (input?: Request | string, init?: RequestInit) => Promise<Response>;
  data: Record<string, unknown>;
}

// Standard hop-by-hop headers per RFC 7230 §6.1
const STANDARD_HOP_BY_HOP = [
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade',
];

/**
 * Validates the backend origin strictly.
 * Returns parsed URL on success, throws Error with description on validation failure.
 */
export function validateBackendOrigin(rawOrigin: string | undefined): URL {
  if (!rawOrigin || typeof rawOrigin !== 'string') {
    throw new Error('BACKEND_ORIGIN environment variable is missing.');
  }

  const trimmed = rawOrigin.trim();
  if (!trimmed) {
    throw new Error('BACKEND_ORIGIN cannot be empty.');
  }

  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    throw new Error('BACKEND_ORIGIN is not a valid URL.');
  }

  // Reject credentials in origin
  if (parsed.username || parsed.password) {
    throw new Error('BACKEND_ORIGIN must not contain credentials.');
  }

  // Reject search parameters or hash fragments in origin definition
  if (parsed.search || parsed.hash) {
    throw new Error('BACKEND_ORIGIN must not contain query parameters or fragments.');
  }

  // Reject path in origin definition (must be protocol + host + optional port only)
  if (parsed.pathname && parsed.pathname !== '/') {
    throw new Error('BACKEND_ORIGIN must be an origin without a subpath.');
  }

  // Protocol validation: HTTPS required for production domains
  const isLocalhost =
    parsed.hostname === 'localhost' ||
    parsed.hostname === '127.0.0.1' ||
    parsed.hostname === '[::1]';

  if (!isLocalhost && parsed.protocol !== 'https:') {
    throw new Error('BACKEND_ORIGIN must use HTTPS protocol in production.');
  }

  return parsed;
}

/**
 * Strips Domain attributes from a Set-Cookie string so that the cookie
 * binds cleanly to the Cloudflare Pages frontend domain.
 */
export function stripCookieDomain(cookieHeader: string): string {
  // Matches '; Domain=example.com' or '; domain=.example.com' with optional surrounding whitespace
  // Replaces with empty string or cleans up semicolons
  return cookieHeader
    .replace(/;\s*Domain=[^;]+/gi, '')
    .trim();
}

/**
 * Safely processes and rewrites upstream redirect Location headers.
 *
 * Requirements:
 * 1. Safe root-relative paths remain relative (e.g. '/dashboard').
 * 2. Safe path-relative references remain relative (e.g. 'dashboard', '../login', './test').
 * 3. Query-only and fragment-only references remain valid (e.g. '?tab=1', '#section').
 * 4. Absolute backend-origin URLs are rewritten to the Pages origin.
 * 5. Legitimate absolute external HTTP(S) URLs remain unchanged.
 * 6. Protocol-relative URLs (e.g. '//evil.com') are rejected.
 * 7. Backslash-normalized external destinations (e.g. '/\\evil.com', '\\evil.com') are rejected.
 * 8. Non-HTTP schemes (e.g. 'javascript:', 'data:', 'mailto:') are rejected.
 * 9. Malformed values do not produce unsafe Location headers (returns null).
 */
export function sanitizeLocationHeader(
  rawLocation: string | null | undefined,
  backendOrigin: URL,
  requestUrl: URL
): string | null {
  if (!rawLocation) return null;
  const trimmed = rawLocation.trim();
  if (!trimmed) return null;

  // Reject any backslashes completely to prevent backslash-normalized external destinations (/\evil.com, \evil.com, etc.)
  if (trimmed.includes('\\')) {
    return null;
  }

  // Check if raw string is an absolute URL with a scheme
  let isAbsolute = false;
  let parsedAbsolute: URL | null = null;
  try {
    parsedAbsolute = new URL(trimmed);
    isAbsolute = true;
  } catch {
    // Not an absolute URL
  }

  if (isAbsolute && parsedAbsolute) {
    // Only permit standard HTTP/HTTPS schemes for absolute redirects
    if (parsedAbsolute.protocol !== 'http:' && parsedAbsolute.protocol !== 'https:') {
      return null;
    }

    // If destination matches internal Railway backend origin, rewrite to current Pages origin
    if (parsedAbsolute.origin.toLowerCase() === backendOrigin.origin.toLowerCase()) {
      const rewritten = new URL(
        parsedAbsolute.pathname + parsedAbsolute.search + parsedAbsolute.hash,
        requestUrl.origin
      );
      return rewritten.toString();
    }

    // Legitimate external absolute URL -> preserve unchanged
    return parsedAbsolute.toString();
  }

  // Not an absolute URL with scheme -> relative reference
  // Reject protocol-relative URLs (//evil.com)
  if (trimmed.startsWith('//')) {
    return null;
  }

  // Resolve relative reference against incoming requestUrl
  let resolved: URL;
  try {
    resolved = new URL(trimmed, requestUrl);
  } catch {
    return null;
  }

  // Enforce that resolved origin strictly matches incoming Pages origin
  if (resolved.origin.toLowerCase() !== requestUrl.origin.toLowerCase()) {
    return null;
  }

  // Safe relative reference: return as-is
  return trimmed;
}

/**
 * Collects hop-by-hop header names from standard list plus the incoming Connection header.
 */
function getHopByHopHeaders(incomingHeaders: Headers): Set<string> {
  const hopByHop = new Set<string>(STANDARD_HOP_BY_HOP);

  const connectionHeader = incomingHeaders.get('connection');
  if (connectionHeader) {
    for (const token of connectionHeader.split(',')) {
      const trimmed = token.trim().toLowerCase();
      if (trimmed) {
        hopByHop.add(trimmed);
      }
    }
  }

  return hopByHop;
}

export async function onRequest(context: PagesFunctionEvent): Promise<Response> {
  const { request, env } = context;

  let backendUrl: URL;
  try {
    backendUrl = validateBackendOrigin(env.BACKEND_ORIGIN);
  } catch (valErr) {
    return new Response(
      JSON.stringify({
        detail: 'Gateway Configuration Error: Invalid backend origin configuration.',
      }),
      {
        status: 502,
        headers: {
          'Content-Type': 'application/json',
          'Cache-Control': 'no-store',
        },
      }
    );
  }

  const incomingUrl = new URL(request.url);

  // Strictly bind destination to backendUrl's origin: prevent client-controlled target overrides
  const targetUrl = new URL(incomingUrl.pathname + incomingUrl.search, backendUrl.origin);

  // Compute hop-by-hop headers for sanitization
  const hopByHop = getHopByHopHeaders(request.headers);

  // Prepare sanitized forward headers
  const forwardHeaders = new Headers();
  request.headers.forEach((value, key) => {
    const lowerKey = key.toLowerCase();
    if (lowerKey === 'host' || hopByHop.has(lowerKey)) {
      return;
    }
    forwardHeaders.set(key, value);
  });

  // Explicit proxy forwarding metadata
  forwardHeaders.set('X-Forwarded-Host', incomingUrl.host);
  forwardHeaders.set('X-Forwarded-Proto', incomingUrl.protocol.replace(':', ''));

  const clientIp = request.headers.get('cf-connecting-ip');
  if (clientIp) {
    forwardHeaders.set('X-Forwarded-For', clientIp);
  }

  const method = request.method.toUpperCase();
  const hasBody = !['GET', 'HEAD'].includes(method) && request.body !== null;

  try {
    const upstreamResponse = await fetch(targetUrl.toString(), {
      method,
      headers: forwardHeaders,
      body: hasBody ? request.body : undefined,
      redirect: 'manual', // Do not automatically follow upstream redirects
    });

    const responseHopByHop = getHopByHopHeaders(upstreamResponse.headers);

    // Build response headers for client
    const responseHeaders = new Headers();
    upstreamResponse.headers.forEach((value, key) => {
      const lowerKey = key.toLowerCase();
      if (responseHopByHop.has(lowerKey) || lowerKey === 'set-cookie') {
        return;
      }
      if (lowerKey === 'location') {
        const sanitizedLoc = sanitizeLocationHeader(value, backendUrl, incomingUrl);
        if (sanitizedLoc) {
          responseHeaders.set('Location', sanitizedLoc);
        }
        return;
      }
      responseHeaders.set(key, value);
    });

    // Handle multiple Set-Cookie headers independently
    const rawSetCookies =
      typeof upstreamResponse.headers.getSetCookie === 'function'
        ? upstreamResponse.headers.getSetCookie()
        : (upstreamResponse.headers.get('set-cookie') ? [upstreamResponse.headers.get('set-cookie')!] : []);

    for (const cookieStr of rawSetCookies) {
      const sanitized = stripCookieDomain(cookieStr);
      responseHeaders.append('Set-Cookie', sanitized);
    }

    return new Response(upstreamResponse.body, {
      status: upstreamResponse.status,
      statusText: upstreamResponse.statusText,
      headers: responseHeaders,
    });
  } catch (_err) {
    // Upstream network failure, DNS error, or timeout
    // Returns generic error message with zero sensitive logs or credential leaks
    return new Response(
      JSON.stringify({
        detail: 'Bad Gateway: Unable to reach backend application service.',
      }),
      {
        status: 502,
        headers: {
          'Content-Type': 'application/json',
          'Cache-Control': 'no-store',
        },
      }
    );
  }
}
