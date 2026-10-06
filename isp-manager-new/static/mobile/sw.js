// Network-only account pages: no tokens, invoices or customer data in CacheStorage.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', event => {
  if (event.request.mode !== 'navigate' || event.request.method !== 'GET') return;
  event.respondWith(fetch(event.request).catch(() => new Response(
    '<!doctype html><html lang="es"><meta name="viewport" content="width=device-width,initial-scale=1"><title>INTER Flash · Sin conexión</title><body style="background:#081522;color:white;font:18px system-ui;padding:32px"><h1>Sin conexión</h1><p>Conéctate a internet para consultar tu cuenta. Tus datos no se guardan sin conexión.</p><button onclick="location.reload()" style="padding:16px">Reintentar</button></body></html>',
    {status:503,headers:{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'}}
  )));
});
