// Service Worker der Web-App: App-Dateien offline, Preisdaten frisch mit Rückfall auf den Cache.
const VERSION = "__VERSION__";
const SHELL = `ladekrone-app-${VERSION}`;
const DATA = "ladekrone-data";
const MAX_DATA_ENTRIES = 120;
// Stil und Skripte tragen die Version in der Adresse. So kann nie eine neue Datei
// auf eine alte aus dem Cache treffen, etwa ein neues app.js auf ein altes pricing.js.
const SHELL_FILES = [
  "./",
  `app.css?v=${VERSION}`,
  `app.js?v=${VERSION}`,
  `pricing.js?v=${VERSION}`,
  `i18n.js?v=${VERSION}`,
  "manifest.webmanifest",
  "datenschutz.html",
  "privacy.html",
  "icons/icon-192.png",
  "icons/icon-512.png",
  "../assets/icon.svg",
  "../assets/fonts/atkinson-400.woff2",
  "../assets/fonts/atkinson-700.woff2",
  "../assets/fonts/bricolage.woff2",
];

self.addEventListener("install", (event) => {
  // cache: "reload" umgeht den HTTP-Cache, damit wirklich die Dateien dieser Version im Cache landen.
  const files = SHELL_FILES.map((url) => new Request(url, { cache: "reload" }));
  event.waitUntil(caches.open(SHELL).then((cache) => cache.addAll(files)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("ladekrone-app-") && k !== SHELL).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

async function trim(cache) {
  const keys = await cache.keys();
  for (const key of keys.slice(0, Math.max(0, keys.length - MAX_DATA_ENTRIES))) await cache.delete(key);
}

async function fromCache(request) {
  const cached = await caches.match(request);
  if (!cached) return null;
  const headers = new Headers(cached.headers);
  headers.set("x-ladekrone-cache", "1");
  return new Response(await cached.blob(), { status: cached.status, statusText: cached.statusText, headers });
}

// Preisdaten: immer zuerst das Netz, damit niemand alte Preise sieht.
async function networkFirst(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(DATA);
      await cache.delete(request);
      await cache.put(request, response.clone());
      trim(cache);
    }
    return response;
  } catch (error) {
    const cached = await fromCache(request);
    if (cached) return cached;
    throw error;
  }
}

// App-Dateien: genau diese Adresse aus dem Cache, sonst aus dem Netz. Eine Datei mit
// anderer Version (?v=…) gilt nur als Notbehelf, wenn das Netz fehlt.
async function cacheFirst(request) {
  const cache = await caches.open(SHELL);
  const cached = await cache.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) cache.put(request, response.clone());
    return response;
  } catch {
    return (await cache.match(request, { ignoreSearch: true })) || Response.error();
  }
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.includes("/v1/")) {
    event.respondWith(networkFirst(request));
  } else if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.match("./", { ignoreSearch: true }).then((r) => r || Response.error())));
  } else {
    event.respondWith(cacheFirst(request));
  }
});
