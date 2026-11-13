// Service worker do OpenFlow (app mobile): deixa o app abrir sem rede e avisa de versões novas. A versão abaixo é carimbada pelo servidor
// (GET /sw.js): quando o OpenFlow do computador é atualizado, este arquivo muda, o navegador instala o novo e o app pergunta ao usuário se quer atualizar agora.
const VERSION = '__OPENFLOW_VERSION__';
const CACHE = 'flow-shell-' + VERSION;

self.addEventListener('install', () => { /* sem skipWaiting: quem decide é o usuário (mensagem SKIP_WAITING) */ });
self.addEventListener('activate', (e) => {
  e.waitUntil((async () => {
    for (const k of await caches.keys()) if (k.startsWith('flow-shell-') && k !== CACHE) await caches.delete(k);
    await self.clients.claim();
  })());
});
self.addEventListener('message', (e) => { if (e.data && e.data.type === 'SKIP_WAITING') self.skipWaiting(); });

// Rede primeiro (sempre a versão atual do computador); sem rede, o que já foi visto. APIs, jogos hospedados e mídias nunca passam pelo cache.
self.addEventListener('fetch', (e) => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/play/')) return;
  e.respondWith((async () => {
    try {
      const res = await fetch(req);
      if (res.ok && res.status === 200) { const c = await caches.open(CACHE); c.put(req, res.clone()).catch(() => {}); }
      return res;
    } catch (err) {
      const hit = await caches.match(req) || (req.mode === 'navigate' ? await caches.match('/') : null);
      if (hit) return hit;
      throw err;
    }
  })());
});
