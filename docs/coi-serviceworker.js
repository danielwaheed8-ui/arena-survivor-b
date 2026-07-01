// This used to enable cross-origin isolation (COEP), but that BLOCKED the
// pygame-web runtime CDN (its files lack the CORP header). This replacement
// simply unregisters itself and reloads, so the page ends up with NO COEP and
// the runtime loads normally.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    try { await self.registration.unregister(); } catch (e) {}
    const clients = await self.clients.matchAll({ type: 'window' });
    for (const client of clients) {
      try { client.navigate(client.url); } catch (e) {}
    }
  })());
});
// No fetch handler: do not touch any requests.
