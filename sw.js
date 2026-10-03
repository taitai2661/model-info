const CACHE_VERSION = "v3";
const SHELL_CACHE = `model-info-shell-${CACHE_VERSION}`;
const DATA_CACHE = `model-info-data-${CACHE_VERSION}`;
const DATA_CACHE_LIMIT = 400;

const SHELL_ASSETS = [
  "./",
  "./index.html",
  "./api.html",
  "./web/style.css",
  "./web/api.css",
  "./web/app.js",
  "./web/api.js",
  "./web/i18n.js",
  "./favicon.svg",
  "./apple-touch-icon.png",
  "./icon-192.png",
  "./icon-512.png",
  "./site.webmanifest",
];

const offlineResponse = (path) => new Response(
  JSON.stringify({ error: "offline", path }),
  { status: 504, headers: { "Content-Type": "application/json" } }
);

async function trimCache(cache, limit) {
  const keys = await cache.keys();
  const excess = keys.length - limit;
  for (const request of keys.slice(0, excess)) {
    await cache.delete(request);
  }
}

async function storeResponse(cache, request, response, limit) {
  try {
    if (response.ok) {
      await cache.put(request, response.clone());
      if (limit) await trimCache(cache, limit);
    } else {
      await cache.delete(request);
    }
  } catch (e) {}
}

async function revalidate(cache, request, limit) {
  return fetch(request, { cache: "no-cache" })
    .then((response) => {
      storeResponse(cache, request, response, limit);
      return response;
    })
    .catch(() => null);
}

async function shellCache() {
  return caches.open(SHELL_CACHE);
}

async function dataCache() {
  return caches.open(DATA_CACHE);
}

async function staleWhileRevalidate(request, limit) {
  const cache = await dataCache();
  const cached = await cache.match(request);
  const network = revalidate(cache, request, limit);
  if (cached) return cached;
  const response = await network;
  return response || offlineResponse(new URL(request.url).pathname);
}

async function shellFirst(request) {
  const cache = await shellCache();
  const cached = await cache.match(request);
  if (cached) {
    revalidate(cache, request, 0);
    return cached;
  }
  const response = await revalidate(cache, request, 0);
  return response || Response.error();
}

async function navigationNetworkFirst(request) {
  const cache = await shellCache();
  try {
    const response = await fetch(request);
    if (response.ok) await cache.put(request, response.clone());
    return response;
  } catch (e) {
    return (await cache.match(request)) || (await cache.match("./index.html")) || Response.error();
  }
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    shellCache()
      .then((cache) => cache.addAll(SHELL_ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys
          .filter((key) => key !== SHELL_CACHE && key !== DATA_CACHE)
          .map((key) => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    event.respondWith(navigationNetworkFirst(request));
    return;
  }

  if (url.pathname.startsWith(`${new URL(self.registration.scope).pathname}v1/`)) {
    event.respondWith(staleWhileRevalidate(request, DATA_CACHE_LIMIT));
    return;
  }

  event.respondWith(shellFirst(request));
});
