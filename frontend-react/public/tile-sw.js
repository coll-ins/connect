const CACHE = 'osm-tiles-v1';
const MAX = 3000;

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

async function trim(cache) {
  const keys = await cache.keys();
  if (keys.length > MAX) {
    await Promise.all(keys.slice(0, keys.length - MAX).map((k) => cache.delete(k)));
  }
}

self.addEventListener('fetch', (e) => {
  const host = new URL(e.request.url).hostname;
  if (host !== 'tile.openstreetmap.org' && !host.endsWith('.tile.openstreetmap.org')) return;
  e.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const hit = await cache.match(e.request);
    if (hit) return hit;
    try {
      const res = await fetch(e.request);
      if (res.ok || res.type === 'opaque') {
        cache.put(e.request, res.clone());
        trim(cache);
      }
      return res;
    } catch {
      return Response.error();
    }
  })());
});
