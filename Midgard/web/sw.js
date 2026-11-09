// Service worker de Midgard Web: permite instalar la página como aplicación
// (Android, escritorio) y abrirla aunque Bifröst tarde en responder.
// Siempre pide primero la versión de la red; la copia guardada solo se usa sin red,
// así una actualización de Bifröst llega en cuanto se recarga la página.

const CACHE = "midgard-web-v1";

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const name of await caches.keys()) if (name !== CACHE) await caches.delete(name);
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin || url.pathname.endsWith("/server.json")) return;
  event.respondWith((async () => {
    try {
      const response = await fetch(request);
      if (response.ok) {
        const copy = response.clone();
        caches.open(CACHE).then((cache) => cache.put(request, copy)).catch(() => {});
      }
      return response;
    } catch (error) {
      const saved = await caches.match(request);
      if (saved) return saved;
      throw error;
    }
  })());
});
