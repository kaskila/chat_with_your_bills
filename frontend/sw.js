// Service worker: lets the installed app open even when the computer cannot be reached.
//
// Only the app itself (HTML, CSS, JavaScript, icons) is cached. Receipt data, photos and
// answers (/api/...) are never cached, so nothing private or stale is kept on the phone.
// App files are fetched from the computer first (so updates show at once); the cached copy is
// used only when the computer does not answer within a few seconds.

const CACHE = "bills-app-v2";
const SHELL = [
  "/", "/index.html", "/manifest.webmanifest", "/css/styles.css",
  "/js/app.js", "/js/api.js", "/js/ui.js", "/js/charts.js", "/js/jobs.js", "/js/camera.js", "/js/resize.js",
  "/js/pages/upload.js", "/js/pages/receipts.js", "/js/pages/receipt.js", "/js/pages/dashboard.js",
  "/js/pages/chat.js", "/js/pages/lab.js", "/js/pages/eval.js", "/js/pages/system.js",
  "/icons/icon-192.png", "/icons/icon-512.png",
];
const TIMEOUT_MS = 4000;

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

function isAppFile(request) {
  const url = new URL(request.url);
  return request.method === "GET" && url.origin === self.location.origin && !url.pathname.startsWith("/api/")
    && !url.pathname.startsWith("/docs") && !url.pathname.startsWith("/openapi");
}

async function networkFirst(request) {
  const cache = await caches.open(CACHE);
  const key = request.mode === "navigate" ? "/index.html" : request;
  try {
    const response = await Promise.race([
      fetch(request),
      new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), TIMEOUT_MS)),
    ]);
    if (response.ok) cache.put(key, response.clone());
    return response;
  } catch (error) {
    const cached = await cache.match(key);
    if (cached) return cached;
    throw error;
  }
}

self.addEventListener("fetch", (event) => {
  if (isAppFile(event.request)) event.respondWith(networkFirst(event.request));
  // Everything else (the API) goes straight to the network, untouched.
});
