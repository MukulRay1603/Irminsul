/* Irminsul's service worker: keeps the app shell on the device so the page opens offline.

   - /static/* and the manifest: cache-first. The server stamps VERSION with a hash of web/,
     so every deploy installs a fresh cache and the old ones are removed on activate.
   - The page itself (/): network-first, so a deploy shows up at once; the cached copy is
     the fallback when there is no connection.
   - /ask*, /quota, /health, /api/*: network-only. Offline, they answer 503 with a plain
     message the app already knows how to show.
   - /art/* and other sites (fonts, YouTube): left alone, straight to the network.
*/
const VERSION = "__VERSION__";
const CACHE = `irminsul-${VERSION}`;
const OFFLINE = "You're offline. Answers need a connection.";
const SHELL = [
  "/", "/manifest.webmanifest",
  "/static/app.css", "/static/planner.css", "/static/patches.css",
  "/static/answers.js", "/static/app.js", "/static/planner.js", "/static/patches.js", "/static/pwa.js",
  "/static/icons/icon-192.png", "/static/icons/favicon-32.png",
];
const NETWORK_ONLY = /^\/(ask|quota|health|api\/)/;

self.addEventListener("install", event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    // One missing file must not stop the install: the rest still make the page work offline
    await Promise.all(SHELL.map(url => cache.add(new Request(url, { cache: "reload" })).catch(() => {})));
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) if (key.startsWith("irminsul-") && key !== CACHE) await caches.delete(key);
    await self.clients.claim();
  })());
});

function offlineJson() {
  return new Response(JSON.stringify({ detail: OFFLINE }), {
    status: 503, headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

function offlinePage() {
  const html = `<!doctype html><html lang="en" data-mode="dark"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Irminsul (offline)</title><link rel="stylesheet" href="/static/app.css"></head>
<body class="offline-page"><main><img src="/static/icons/icon-192.png" alt="" width="96" height="96">
<h1>IRMINSUL</h1><p role="status">${OFFLINE}</p><a href="/">Try again</a></main></body></html>`;
  return new Response(html, { status: 503, headers: { "content-type": "text/html; charset=utf-8" } });
}

async function cacheFirst(request) {
  const cached = await caches.match(request, { ignoreSearch: true });
  if (cached) return cached;
  const res = await fetch(request);
  if (res.ok) (await caches.open(CACHE)).put(request, res.clone());
  return res;
}

async function page(request) {
  try {
    const res = await fetch(request);
    if (res.ok && new URL(request.url).pathname === "/") (await caches.open(CACHE)).put("/", res.clone());
    return res;
  } catch {
    return (await caches.match("/")) || offlinePage();
  }
}

self.addEventListener("fetch", event => {
  const { request } = event, url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (NETWORK_ONLY.test(url.pathname)) return event.respondWith(fetch(request).catch(offlineJson));
  if (request.method !== "GET") return;
  if (request.mode === "navigate") return event.respondWith(page(request));
  if (url.pathname.startsWith("/static/") || url.pathname === "/manifest.webmanifest") {
    event.respondWith(cacheFirst(request).catch(() => Response.error()));
  }
});
