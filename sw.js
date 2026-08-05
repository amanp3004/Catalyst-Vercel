// Catalyst service worker
// Handles: (1) basic offline caching of the app shell, (2) push notifications via Firebase Cloud Messaging.

// Bumped v1 -> v2 so returning visitors' browsers detect this file changed
// (byte-for-byte comparison), install this new worker, and the activate
// handler below purges the old v1 cache that was serving stale index.html.
const CACHE_NAME = "catalyst-shell-v2";
const SHELL_FILES = [
  "./",
  "./index.html",
  "./manifest.json",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_FILES))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  // Never cache the data JSON — it must always be fresh.
  if (event.request.url.includes("/data/")) return;

  // Network-first, falling back to cache only when offline. This is the
  // opposite of the previous cache-first strategy, which was the actual
  // cause of "always need to hard refresh" — a cache-first shell serves
  // whatever was cached on first install forever, regardless of how many
  // times the real index.html on the server changes afterward. Network-
  // first means every visit checks the server first (near-instant on a
  // normal connection), and only falls back to the cached copy if the
  // network request genuinely fails (e.g. offline).
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const clone = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});

// ---------------------------------------------------------------------------
// Firebase Cloud Messaging — background push handling
// ---------------------------------------------------------------------------

importScripts("https://www.gstatic.com/firebasejs/10.12.2/firebase-app-compat.js");
importScripts("https://www.gstatic.com/firebasejs/10.12.2/firebase-messaging-compat.js");

// TODO: paste your Firebase web config here (from Firebase Console → Project
// Settings → General → Your apps → Web app). These values are safe to be
// public — they identify the project, they are not secret credentials.
firebase.initializeApp({
  apiKey: "AIzaSyB63bgKMs5atlnWwkJP7ZnSPFwNLMVT0u4",
  authDomain: "catalyst-5823f.firebaseapp.com",
  projectId: "catalyst-5823f",
  storageBucket: "catalyst-5823f.firebasestorage.app",
  messagingSenderId: "993238629123",
  appId: "1:993238629123:web:8f9b45f8de59a790600736",
  measurementId: "G-XNB4KR8P77"
});

const messaging = firebase.messaging();

messaging.onBackgroundMessage((payload) => {
  const title = payload.notification?.title || "Catalyst";
  const options = {
    body: payload.notification?.body || "",
    icon: "./icons/icon-192.png",
    badge: "./icons/icon-192.png",
    data: { url: payload.data?.url || "./" },
  };
  self.registration.showNotification(title, options);
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data?.url || "./";
  event.waitUntil(
    clients.matchAll({ type: "window" }).then((windowClients) => {
      for (const client of windowClients) {
        if (client.url.includes(location.origin) && "focus" in client) {
          return client.focus();
        }
      }
      if (clients.openWindow) return clients.openWindow(url);
    })
  );
});
