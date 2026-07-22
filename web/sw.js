/* Service worker — makes the app shell load OFFLINE.

   The briefing DATA lives in IndexedDB (saved by index.html on every "Get
   briefing"); this worker only makes the page itself openable without a network
   so those saved briefings can be viewed in the air. Bump CACHE on any shell
   change so clients pick up the new version.

   Strategy:
   - App shell ("/", manifest, icons): cache-first, refreshed in the background.
   - Everything else (incl. POST /briefing, /feedback): straight to network —
     never cached, never intercepted offline. */
const CACHE = "notamwx-shell-v3";   // v3: what's-new box. Bump on every shell
                                    // change — a stale cache would show the
                                    // release note a launch later than it says.
const SHELL = ["/", "/manifest.json", "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", function (e) {
  e.waitUntil(caches.open(CACHE).then(function (c) { return c.addAll(SHELL); }));
  self.skipWaiting();
});

self.addEventListener("activate", function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.filter(function (k) { return k !== CACHE; })
                            .map(function (k) { return caches.delete(k); }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener("fetch", function (e) {
  const req = e.request;
  if (req.method !== "GET") return;                 // POST /briefing etc. -> network
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;  // third-party -> network

  const isShell = req.mode === "navigate" || SHELL.indexOf(url.pathname) !== -1;
  if (!isShell) return;                             // only the shell is cached

  // Cache-first for the shell, with a background refresh; fall back to the
  // cached "/" for any navigation when both cache and network miss.
  e.respondWith(
    caches.match(req).then(function (hit) {
      const net = fetch(req).then(function (res) {
        if (res && res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then(function (c) { c.put(req, copy); });
        }
        return res;
      }).catch(function () { return hit || caches.match("/"); });
      return hit || net;
    })
  );
});
