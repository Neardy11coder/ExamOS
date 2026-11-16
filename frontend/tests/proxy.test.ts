/**
 * Unit and functional test suite for Cloudflare Pages Reverse Proxy
 *
 * Verifies:
 * 1. BACKEND_ORIGIN validation (empty, credentials, query parameters, pathnames, HTTP vs HTTPS).
 * 2. stripCookieDomain logic (removes domain, preserves HttpOnly, Secure, SameSite, Max-Age, Path).
 * 3. Multiple Set-Cookie header handling and independent preservation.
 * 4. Request preservation (GET, POST, DELETE, URL query strings, body payload).
 * 5. Header sanitization (Host removal, hop-by-hop stripping, Connection-nominated headers, IP forwarding).
 * 6. Upstream failure handling (generic 502 Bad Gateway, no credential leaks).
 * 7. Redirect preservation (manual redirect pass-through).
 */

import { strict as assert } from 'node:assert';
import { onRequest, validateBackendOrigin, stripCookieDomain, sanitizeLocationHeader } from '../functions/api/[[path]].ts';

async function runTests() {
  console.log('--- Starting Cloudflare Pages Reverse Proxy Unit & Functional Tests ---');

  // Test 1: validateBackendOrigin positive tests
  console.log('Test 1: Origin validation positive tests');
  {
    const prodUrl = validateBackendOrigin('https://examos-backend.up.railway.app');
    assert.equal(prodUrl.origin, 'https://examos-backend.up.railway.app');

    const prodUrlWithSlash = validateBackendOrigin('https://examos-backend.up.railway.app/');
    assert.equal(prodUrlWithSlash.origin, 'https://examos-backend.up.railway.app');

    const localhostUrl = validateBackendOrigin('http://127.0.0.1:8000');
    assert.equal(localhostUrl.origin, 'http://127.0.0.1:8000');
  }

  // Test 2: validateBackendOrigin negative tests
  console.log('Test 2: Origin validation negative tests');
  {
    assert.throws(() => validateBackendOrigin(''), /empty|missing/i);
    assert.throws(() => validateBackendOrigin(undefined), /missing/i);
    assert.throws(() => validateBackendOrigin('not-a-url'), /not a valid URL/i);
    assert.throws(() => validateBackendOrigin('http://examos-prod.railway.app'), /must use HTTPS/i);
    assert.throws(() => validateBackendOrigin('https://user:pass@examos.railway.app'), /must not contain credentials/i);
    assert.throws(() => validateBackendOrigin('https://examos.railway.app?query=1'), /must not contain query/i);
    assert.throws(() => validateBackendOrigin('https://examos.railway.app#frag'), /must not contain query parameters or fragments/i);
    assert.throws(() => validateBackendOrigin('https://examos.railway.app/subpath'), /without a subpath/i);
  }

  // Test 3: stripCookieDomain
  console.log('Test 3: stripCookieDomain removes domain, preserves security flags');
  {
    const c1 = 'examos_access=token123; Path=/; Domain=up.railway.app; HttpOnly; Secure; SameSite=Lax';
    const s1 = stripCookieDomain(c1);
    assert.equal(s1, 'examos_access=token123; Path=/; HttpOnly; Secure; SameSite=Lax');

    const c2 = 'examos_csrf=csrf456; domain=.railway.app; Path=/; Secure; SameSite=Lax';
    const s2 = stripCookieDomain(c2);
    assert.equal(s2, 'examos_csrf=csrf456; Path=/; Secure; SameSite=Lax');

    const c3 = 'test=123; Path=/; HttpOnly';
    const s3 = stripCookieDomain(c3);
    assert.equal(s3, 'test=123; Path=/; HttpOnly');
  }

  // Helper to create mock event
  function createMockContext(req: Request, origin: string = 'https://backend.railway.internal') {
    return {
      request: req,
      env: { BACKEND_ORIGIN: origin },
      params: {},
      waitUntil: () => {},
      next: async () => new Response('next'),
      data: {},
    };
  }

  // Test 4: Request method, query, body preservation, and header sanitization
  console.log('Test 4: Request forwarding and sanitization');
  {
    const originalFetch = globalThis.fetch;
    let interceptedUrl = '';
    let interceptedMethod = '';
    let interceptedHeaders: Headers | null = null;
    let interceptedBody = '';

    globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      interceptedUrl = input.toString();
      interceptedMethod = init?.method || 'GET';
      interceptedHeaders = new Headers(init?.headers);
      if (init?.body) {
        if (typeof init.body === 'string') {
          interceptedBody = init.body;
        } else if (init.body instanceof ReadableStream) {
          // Read from stream
          const reader = init.body.getReader();
          const chunks: Uint8Array[] = [];
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            if (value) chunks.push(value);
          }
          interceptedBody = Buffer.concat(chunks).toString('utf-8');
        } else {
          interceptedBody = String(init.body);
        }
      }
      return new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }) as any;

    try {
      // POST request with body, query string, hop-by-hop headers
      const clientReq = new Request('https://frontend.pages.dev/api/v1/auth/login?source=nav&ref=123', {
        method: 'POST',
        headers: {
          'Host': 'frontend.pages.dev',
          'Content-Type': 'application/json',
          'Authorization': 'Bearer test-jwt-token',
          'X-CSRF-Token': 'test-csrf-token',
          'Connection': 'keep-alive, X-Custom-Hop',
          'Keep-Alive': 'timeout=5',
          'X-Custom-Hop': 'should-be-stripped',
          'CF-Connecting-IP': '203.0.113.195',
        },
        body: JSON.stringify({ email: 'user@example.com' }),
      });

      const res = await onRequest(createMockContext(clientReq, 'https://backend.railway.internal'));
      assert.equal(res.status, 200);

      // Verify URL and query preservation
      assert.equal(interceptedUrl, 'https://backend.railway.internal/api/v1/auth/login?source=nav&ref=123');
      assert.equal(interceptedMethod, 'POST');
      assert.equal(interceptedBody, JSON.stringify({ email: 'user@example.com' }));

      // Verify header sanitization
      assert.equal(interceptedHeaders?.get('host'), null);
      assert.equal(interceptedHeaders?.get('connection'), null);
      assert.equal(interceptedHeaders?.get('keep-alive'), null);
      assert.equal(interceptedHeaders?.get('x-custom-hop'), null);

      // Verify forwarded headers
      assert.equal(interceptedHeaders?.get('authorization'), 'Bearer test-jwt-token');
      assert.equal(interceptedHeaders?.get('x-csrf-token'), 'test-csrf-token');
      assert.equal(interceptedHeaders?.get('x-forwarded-host'), 'frontend.pages.dev');
      assert.equal(interceptedHeaders?.get('x-forwarded-proto'), 'https');
      assert.equal(interceptedHeaders?.get('x-forwarded-for'), '203.0.113.195');
    } finally {
      globalThis.fetch = originalFetch;
    }
  }

  // Test 5: Multiple Set-Cookie headers preservation
  console.log('Test 5: Multiple Set-Cookie header handling');
  {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async () => {
      const headers = new Headers();
      headers.append('Set-Cookie', 'examos_access=token1; Domain=backend.railway.internal; Path=/; HttpOnly; Secure; SameSite=Lax');
      headers.append('Set-Cookie', 'examos_csrf=csrf2; Domain=backend.railway.internal; Path=/; Secure; SameSite=Lax');

      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers,
      });
    }) as any;

    try {
      const clientReq = new Request('https://frontend.pages.dev/api/v1/auth/login', { method: 'POST' });
      const res = await onRequest(createMockContext(clientReq, 'https://backend.railway.internal'));

      // If getSetCookie exists on Response Headers
      const cookies = typeof res.headers.getSetCookie === 'function'
        ? res.headers.getSetCookie()
        : [res.headers.get('set-cookie') || ''];

      assert.equal(cookies.length, 2);
      assert.ok(cookies[0].includes('examos_access=token1'));
      assert.ok(!cookies[0].includes('Domain='));
      assert.ok(cookies[0].includes('HttpOnly'));
      assert.ok(cookies[0].includes('Secure'));

      assert.ok(cookies[1].includes('examos_csrf=csrf2'));
      assert.ok(!cookies[1].includes('Domain='));
      assert.ok(cookies[1].includes('Secure'));
    } finally {
      globalThis.fetch = originalFetch;
    }
  }

  // Test 6: Upstream failure and timeout
  console.log('Test 6: Upstream error produces generic 502 with zero leak');
  {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async () => {
      throw new Error('Connection refused to sensitive internal database host postgres-internal:5432 with password secret123');
    }) as any;

    try {
      const clientReq = new Request('https://frontend.pages.dev/api/v1/health');
      const res = await onRequest(createMockContext(clientReq, 'https://backend.railway.internal'));

      assert.equal(res.status, 502);
      const data = await res.json();
      assert.equal(data.detail, 'Bad Gateway: Unable to reach backend application service.');
      assert.ok(!JSON.stringify(data).includes('secret123'));
      assert.ok(!JSON.stringify(data).includes('postgres-internal'));
    } finally {
      globalThis.fetch = originalFetch;
    }
  }

  // Test 7: Redirect response handling & Location rewriting
  console.log('Test 7: Comprehensive redirect handling and security tests');
  {
    const originalFetch = globalThis.fetch;
    const backendOrigin = 'https://backend.railway.internal';

    // 7.1 Safe root-relative paths remain relative
    {
      for (const rootRel of ['/api/v1/exams/active', '/dashboard', '/exams/123/take']) {
        globalThis.fetch = (async () => new Response(null, {
          status: 307,
          headers: { 'Location': rootRel },
        })) as any;

        const req = new Request('https://frontend.pages.dev/api/v1/exams/current');
        const res = await onRequest(createMockContext(req, backendOrigin));
        assert.equal(res.status, 307);
        assert.equal(res.headers.get('location'), rootRel);
      }
    }

    // 7.2 Safe path-relative references remain relative
    {
      for (const pathRel of ['dashboard', '../login', './overview', 'settings/profile']) {
        globalThis.fetch = (async () => new Response(null, {
          status: 302,
          headers: { 'Location': pathRel },
        })) as any;

        const req = new Request('https://frontend.pages.dev/api/v1/auth/session');
        const res = await onRequest(createMockContext(req, backendOrigin));
        assert.equal(res.status, 302);
        assert.equal(res.headers.get('location'), pathRel);
      }
    }

    // 7.3 Query-only and fragment-only references remain valid
    {
      for (const ref of ['?tab=results', '?page=2&filter=active', '#summary', '#section-2']) {
        globalThis.fetch = (async () => new Response(null, {
          status: 302,
          headers: { 'Location': ref },
        })) as any;

        const req = new Request('https://frontend.pages.dev/api/v1/exams/456');
        const res = await onRequest(createMockContext(req, backendOrigin));
        assert.equal(res.status, 302);
        assert.equal(res.headers.get('location'), ref);
      }
    }

    // 7.4 Absolute internal Railway redirect rewritten to frontend Pages origin
    {
      globalThis.fetch = (async () => new Response(null, {
        status: 302,
        headers: { 'Location': 'https://backend.railway.internal/api/v1/auth/callback?ref=xyz#target' },
      })) as any;

      const req = new Request('https://frontend.pages.dev/api/v1/auth/start');
      const res = await onRequest(createMockContext(req, backendOrigin));
      assert.equal(res.status, 302);
      assert.equal(res.headers.get('location'), 'https://frontend.pages.dev/api/v1/auth/callback?ref=xyz#target');
    }

    // 7.5 Absolute external redirect preserved as-is
    {
      for (const extUrl of [
        'https://external-auth.example.com/oauth/authorize?client_id=123',
        'http://external-partner.org/auth',
      ]) {
        globalThis.fetch = (async () => new Response(null, {
          status: 302,
          headers: { 'Location': extUrl },
        })) as any;

        const req = new Request('https://frontend.pages.dev/api/v1/oauth/login');
        const res = await onRequest(createMockContext(req, backendOrigin));
        assert.equal(res.status, 302);
        assert.equal(res.headers.get('location'), extUrl);
      }
    }

    // 7.6 Protocol-relative URLs rejected
    {
      for (const protoRel of ['//evil.com', '//evil.com/phish', '///evil.com']) {
        globalThis.fetch = (async () => new Response(null, {
          status: 302,
          headers: { 'Location': protoRel },
        })) as any;

        const req = new Request('https://frontend.pages.dev/api/v1/redirect-test');
        const res = await onRequest(createMockContext(req, backendOrigin));
        assert.equal(res.status, 302);
        assert.equal(res.headers.get('location'), null, `Protocol-relative '${protoRel}' must be omitted`);
      }
    }

    // 7.7 Backslash-normalized external destinations rejected
    {
      for (const backslashDest of [
        '/\\evil.com',
        '\\evil.com',
        '\\\\evil.com',
        '/\\/evil.com',
        'foo\\bar',
        'https://evil.com\\@frontend.pages.dev',
      ]) {
        globalThis.fetch = (async () => new Response(null, {
          status: 302,
          headers: { 'Location': backslashDest },
        })) as any;

        const req = new Request('https://frontend.pages.dev/api/v1/redirect-test');
        const res = await onRequest(createMockContext(req, backendOrigin));
        assert.equal(res.status, 302);
        assert.equal(res.headers.get('location'), null, `Backslash-normalized '${backslashDest}' must be omitted`);
      }
    }

    // 7.8 Non-HTTP schemes rejected
    {
      for (const nonHttp of [
        'javascript:alert(1)',
        'data:text/html,evil',
        'mailto:admin@example.com',
        'vbscript:msgbox(1)',
        'file:///etc/passwd',
      ]) {
        globalThis.fetch = (async () => new Response(null, {
          status: 302,
          headers: { 'Location': nonHttp },
        })) as any;

        const req = new Request('https://frontend.pages.dev/api/v1/redirect-test');
        const res = await onRequest(createMockContext(req, backendOrigin));
        assert.equal(res.status, 302);
        assert.equal(res.headers.get('location'), null, `Non-HTTP scheme '${nonHttp}' must be omitted`);
      }
    }

    // 7.9 Malformed and empty values do not produce unsafe Location headers
    {
      for (const malformed of ['http://[invalid-url', 'http://', '   ', '']) {
        globalThis.fetch = (async () => new Response(null, {
          status: 302,
          headers: { 'Location': malformed },
        })) as any;

        const req = new Request('https://frontend.pages.dev/api/v1/redirect-test');
        const res = await onRequest(createMockContext(req, backendOrigin));
        assert.equal(res.status, 302);
        assert.equal(res.headers.get('location'), null, `Malformed location '${malformed}' must be omitted`);
      }
    }

    // 7.10 Redirect response without Location header handled cleanly
    {
      globalThis.fetch = (async () => new Response(null, { status: 302 })) as any;

      const req = new Request('https://frontend.pages.dev/api/v1/no-loc');
      const res = await onRequest(createMockContext(req, backendOrigin));
      assert.equal(res.status, 302);
      assert.equal(res.headers.get('location'), null);
    }

    // 7.11 Cookie behavior during redirects (Set-Cookie preserved alongside rewritten Location)
    {
      globalThis.fetch = (async () => {
        const headers = new Headers();
        headers.set('Location', 'https://backend.railway.internal/api/v1/dashboard');
        headers.append('Set-Cookie', 'examos_access=redirect_token; Domain=backend.railway.internal; Path=/; HttpOnly; Secure; SameSite=Lax');
        headers.append('Set-Cookie', 'examos_csrf=redirect_csrf; Domain=backend.railway.internal; Path=/; Secure; SameSite=Lax');
        return new Response(null, {
          status: 303,
          headers,
        });
      }) as any;

      const req = new Request('https://frontend.pages.dev/api/v1/auth/finalize');
      const res = await onRequest(createMockContext(req, backendOrigin));
      assert.equal(res.status, 303);
      assert.equal(res.headers.get('location'), 'https://frontend.pages.dev/api/v1/dashboard');

      const cookies = typeof res.headers.getSetCookie === 'function'
        ? res.headers.getSetCookie()
        : [res.headers.get('set-cookie') || ''];
      assert.equal(cookies.length, 2);
      assert.ok(cookies[0].includes('examos_access=redirect_token'));
      assert.ok(!cookies[0].includes('Domain='));
      assert.ok(cookies[0].includes('HttpOnly'));
      assert.ok(cookies[1].includes('examos_csrf=redirect_csrf'));
      assert.ok(!cookies[1].includes('Domain='));
    }

    globalThis.fetch = originalFetch;
  }

  // Test 8: Invalid BACKEND_ORIGIN configuration returns 502
  console.log('Test 8: Invalid BACKEND_ORIGIN returns 502');
  {
    const clientReq = new Request('https://frontend.pages.dev/api/v1/health');
    const res = await onRequest(createMockContext(clientReq, ''));
    assert.equal(res.status, 502);
    const data = await res.json();
    assert.ok(data.detail.includes('Invalid backend origin'));
  }

  // Test 9: DELETE method preservation
  console.log('Test 9: DELETE method preservation');
  {
    const originalFetch = globalThis.fetch;
    let interceptedMethod = '';
    globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
      interceptedMethod = init?.method || '';
      return new Response(null, { status: 204 });
    }) as any;

    try {
      const clientReq = new Request('https://frontend.pages.dev/api/v1/questions/123', { method: 'DELETE' });
      const res = await onRequest(createMockContext(clientReq, 'https://backend.railway.internal'));
      assert.equal(res.status, 204);
      assert.equal(interceptedMethod, 'DELETE');
    } finally {
      globalThis.fetch = originalFetch;
    }
  }

  // Test 10: Direct unit testing of sanitizeLocationHeader for backslash and path variants
  console.log('Test 10: sanitizeLocationHeader comprehensive unit tests');
  {
    const backendOrigin = new URL('https://backend.railway.internal');
    const requestUrl = new URL('https://frontend.pages.dev/api/v1/auth/login');

    // 1. /\\evil.com
    assert.equal(sanitizeLocationHeader('/\\evil.com', backendOrigin, requestUrl), null);
    // 2. Single-backslash relative destination
    assert.equal(sanitizeLocationHeader('\\login', backendOrigin, requestUrl), null);
    assert.equal(sanitizeLocationHeader('path\\dest', backendOrigin, requestUrl), null);
    // 3. Double-backslash destination
    assert.equal(sanitizeLocationHeader('\\\\evil.com', backendOrigin, requestUrl), null);
    // 4. Normal relative path
    assert.equal(sanitizeLocationHeader('dashboard', backendOrigin, requestUrl), 'dashboard');
    assert.equal(sanitizeLocationHeader('../login', backendOrigin, requestUrl), '../login');
    // 5. Root-relative path
    assert.equal(sanitizeLocationHeader('/dashboard', backendOrigin, requestUrl), '/dashboard');
    // 6. Query-only reference
    assert.equal(sanitizeLocationHeader('?tab=1', backendOrigin, requestUrl), '?tab=1');
    // 7. Fragment-only reference
    assert.equal(sanitizeLocationHeader('#section', backendOrigin, requestUrl), '#section');
    // 8. Internal absolute backend URL -> rewritten to Pages origin
    assert.equal(
      sanitizeLocationHeader('https://backend.railway.internal/dashboard?tab=1#view', backendOrigin, requestUrl),
      'https://frontend.pages.dev/dashboard?tab=1#view'
    );
    // 9. External absolute HTTPS URL -> preserved
    assert.equal(
      sanitizeLocationHeader('https://login.partner.edu/oauth', backendOrigin, requestUrl),
      'https://login.partner.edu/oauth'
    );
    // 10. Non-HTTP schemes -> null
    assert.equal(sanitizeLocationHeader('javascript:alert(1)', backendOrigin, requestUrl), null);
    assert.equal(sanitizeLocationHeader('data:text/html,evil', backendOrigin, requestUrl), null);
  }

  console.log('--- ALL PROXY TESTS PASSED SUCCESSFULLY (10/10) ---');
}

runTests().catch((err) => {
  console.error('Test suite failed:', err);
  process.exit(1);
});
