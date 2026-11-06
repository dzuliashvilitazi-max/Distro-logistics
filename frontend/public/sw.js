const VERSION = "v4";
const SHELL_CACHE = `distro-shell-${VERSION}`;
const ASSET_CACHE = `distro-assets-${VERSION}`;
const SHELL_URLS = ["/", "/manifest.json", "/favicon.ico", "/favicon-16.png", "/favicon-32.png", "/icon-192.png", "/icon-512.png", "/icon-maskable-192.png", "/icon-maskable-512.png", "/apple-touch-icon.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL_URLS)).then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => ![SHELL_CACHE, ASSET_CACHE].includes(k)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  // API calls, bank callbacks and cross-origin requests always go to the network.
  if (url.origin !== self.location.origin || url.pathname.startsWith("/api")) return;

  if (request.mode === "navigate") {
    // Network first so deploys show up immediately; cached shell keeps the app opening offline.
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(SHELL_CACHE).then((cache) => cache.put("/", copy));
          return response;
        })
        .catch(() => caches.match("/")),
    );
    return;
  }

  // Static files (hashed bundles, icons, fonts): serve from cache instantly, refresh in background.
  event.respondWith(
    caches.open(ASSET_CACHE).then(async (cache) => {
      const cached = await cache.match(request);
      const network = fetch(request)
        .then((response) => {
          if (response.ok) cache.put(request, response.clone());
          return response;
        })
        .catch(() => cached);
      return cached || network;
    }),
  );
});

self.addEventListener("message", (event) => {
  if (event.data === "SKIP_WAITING") self.skipWaiting();
});

self.addEventListener("push", (event) => {
  let data = {};
  console.info("[Distro Push] Push event received", { hasPayload: Boolean(event.data) });
  try {
    data = event.data ? event.data.json() : {};
  } catch (error) {
    console.warn("[Distro Push] Could not parse push payload", { error: error.name });
    data = { body: event.data && event.data.text() };
  }
  const url = new URL(data.url || "/", self.location.origin).href;
  const title = data.title || "Distro Logistics";
  event.waitUntil(
    self.registration.showNotification(title, {
      body: data.body || "",
      icon: "/icon-192.png",
      badge: "/icon-192.png",
      // Same tag collapses duplicates (e.g. the in-page order alert and this push for one notification).
      tag: data.tag || undefined,
      renotify: !!data.tag,
      data: { url },
    }).then(() => {
      console.info("[Distro Push] System notification displayed", {
        notificationId: data.notification_id || null,
      });
    }).catch((error) => {
      console.error("[Distro Push] Could not display system notification", { error: error.name });
      throw error;
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || self.location.origin + "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(async (clients) => {
      const open = clients.find((c) => new URL(c.url).origin === self.location.origin);
      if (!open) return self.clients.openWindow(target);
      await open.focus();
      // The running app routes client-side, so no reload and no lost state.
      open.postMessage({ type: "PUSH_NAVIGATE", url: target });
      return undefined;
    }),
  );
});
