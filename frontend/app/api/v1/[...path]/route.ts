import { NextRequest } from 'next/server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const base = process.env.BACKEND_URL || 'http://127.0.0.1:8000';
  const target = `${base.replace(/\/$/, '')}/api/v1/${path.map(encodeURIComponent).join('/')}${request.nextUrl.search}`;
  const headers = new Headers();
  const auth = request.headers.get('authorization') || (process.env.BACKEND_API_KEY ? `Bearer ${process.env.BACKEND_API_KEY}` : null);
  if (auth) headers.set('authorization', auth);
  for (const name of ['content-type', 'accept', 'last-event-id', 'x-correlation-id']) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body: ['GET', 'HEAD'].includes(request.method) ? undefined : request.body,
      duplex: 'half',
      cache: 'no-store',
      signal: request.signal,
    } as RequestInit & { duplex: 'half' });
    const outgoing = new Headers();
    for (const name of ['content-type', 'cache-control', 'x-correlation-id', 'x-accel-buffering']) {
      const value = upstream.headers.get(name);
      if (value) outgoing.set(name, value);
    }
    if (upstream.headers.get('content-type')?.includes('text/event-stream')) {
      outgoing.set('cache-control', 'no-cache, no-transform');
      outgoing.set('x-accel-buffering', 'no');
    }
    return new Response(upstream.body, { status: upstream.status, headers: outgoing });
  } catch {
    return Response.json({ code: 'BACKEND_UNAVAILABLE', message: 'The backend is not reachable.', correlation_id: crypto.randomUUID() }, { status: 503 });
  }
}

export { proxy as GET, proxy as POST, proxy as PATCH, proxy as DELETE };
