// FM26 Analyst service worker (phone only): network first, falling back to the last copy when the PC can't be
// reached, so the app opens instantly and still shows your last data offline. Sign-in pages are never cached.
const CACHE = "fm26-v1";
const SHELL = ["/", "/static/app.js", "/static/coach.js", "/static/style.css", "/static/icon-192.png"];
const CDN = "https://cdnjs.cloudflare.com";

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => Promise.all(SHELL.map((u) =>
    fetch(u, { credentials: "include" }).then((r) => r.ok && !r.redirected && c.put(u, r)).catch(() => {})))));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

const offline = () => new Response(JSON.stringify({ detail: "Offline - your PC can't be reached right now." }),
  { status: 503, headers: { "Content-Type": "application/json" } });

async function marked(res) {         // tell the page this came from the offline copy
  const h = new Headers(res.headers);
  h.set("X-FM-Cached", res.headers.get("Date") || "1");
  return new Response(await res.blob(), { status: res.status, headers: h });
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET") return;
  if (url.origin === CDN) {           // chart libraries: versioned, so cache first
    e.respondWith(caches.match(req).then((hit) => hit || fetch(req).then((r) => {
      if (r.ok) caches.open(CACHE).then((c) => c.put(req, r.clone()));
      return r;
    })));
    return;
  }
  if (url.origin !== location.origin) return;
  if (url.pathname.startsWith("/auth/") || url.pathname === "/login" || url.pathname === "/pair") return;
  e.respondWith(fetch(req).then((r) => {
    if (r.ok && !r.redirected && r.type === "basic") {
      const copy = r.clone();
      caches.open(CACHE).then((c) => c.put(req.mode === "navigate" ? "/" : req, copy));
    }
    return r;
  }).catch(async () => {
    const hit = await caches.match(req.mode === "navigate" ? "/" : req);
    if (hit) return url.pathname.startsWith("/api/") ? marked(hit) : hit;
    return offline();
  }));
});
