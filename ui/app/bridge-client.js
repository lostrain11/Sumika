// Shared transport for existing Sumika pages, whether hosted by the shell or
// loaded into a managed Harness page. The module's trusted asset origin owns
// the API; neither URL query strings nor model output can choose an endpoint.
const bridgeOrigin = new URL(import.meta.url).origin;

export async function bridgeFetch(path, options = {}) {
  const target = new URL(path, bridgeOrigin);
  if (target.origin !== bridgeOrigin || !target.pathname.startsWith('/api/')) {
    throw new Error('request is outside the Sumika API');
  }
  const headers = new Headers(options.headers);
  const method = (options.method || 'GET').toUpperCase();
  if (!['GET', 'HEAD'].includes(method) && !headers.has('X-Sumika-CSRF')) {
    const session = await globalThis.fetch(bridgeOrigin + '/api/manage/session', {
      signal: options.signal, credentials: 'omit', redirect: 'error', cache: 'no-store',
    });
    if (!session.ok) throw new Error(`Bridge session unavailable: HTTP ${session.status}`);
    const value = await session.json();
    if (typeof value.csrf !== 'string' || !value.csrf) throw new Error('Bridge session token missing');
    headers.set('X-Sumika-CSRF', value.csrf);
  }
  // No retry of a possibly executed write, and no credential-bearing redirect.
  return globalThis.fetch(target, {
    ...options, method, headers, credentials: 'omit', redirect: 'error', cache: 'no-store',
  });
}
