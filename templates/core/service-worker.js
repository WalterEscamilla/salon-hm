// Solo se conserva esta página pública. Las páginas privadas y los POST van a la red.
const CACHE_NAME = 'salon-hm-pwa-v1';
const OFFLINE_URL = '{% url "core:offline" %}';

self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const response = await fetch(new Request(OFFLINE_URL, {cache: 'reload', credentials: 'omit'}));
    if (!response.ok || response.redirected || !response.headers.get('Content-Type')?.includes('text/html')) {
      throw new Error('No se pudo preparar la pantalla sin conexión.');
    }
    const cache = await caches.open(CACHE_NAME);
    await cache.put(OFFLINE_URL, response);
  })());
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter(name => name.startsWith('salon-hm-pwa-') && name !== CACHE_NAME).map(name => caches.delete(name)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET' || event.request.mode !== 'navigate' || new URL(event.request.url).origin !== self.location.origin) return;
  event.respondWith((async () => {
    try {
      return await fetch(event.request);
    } catch {
      const cache = await caches.open(CACHE_NAME);
      const response = await cache.match(OFFLINE_URL);
      return new Response(response ? response.body : 'Sin conexión. Conéctate a internet y vuelve a abrir Salón HM.', {
        status: 503,
        headers: {'Content-Type': response ? 'text/html; charset=utf-8' : 'text/plain; charset=utf-8', 'Cache-Control': 'no-store'}
      });
    }
  })());
});
