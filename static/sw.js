/* PWA — قشرة التطبيق + شاشة الطابور للعمل دون اتصال */
const CACHE = 'hms-shell-v4';
const SHELL = ['/ui/', '/ui/manifest.json', '/ui/icon.svg'];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;

  // بيانات الطابور: الشبكة أولًا مع حفظ آخر نسخة (تعمل دون اتصال)
  if (url.pathname === '/appointments/queue') {
    e.respondWith(
      fetch(e.request)
        .then((r) => {
          const clone = r.clone();
          caches.open(CACHE).then((c) => c.put(e.request, clone));
          return r;
        })
        .catch(() => caches.match(e.request))
    );
    return;
  }

  // ملفات الواجهة: الشبكة أولًا (أحدث نسخة دائمًا) ثم الكاش كاحتياط دون اتصال
  if (url.pathname.startsWith('/ui/')) {
    e.respondWith(
      fetch(e.request).then((r) => {
        const clone = r.clone();
        caches.open(CACHE).then((c) => c.put(e.request, clone));
        return r;
      }).catch(() => caches.match(e.request))
    );
  }
});
