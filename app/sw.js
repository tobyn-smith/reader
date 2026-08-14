// caches the app and its vendored libraries so it works with no network after
// the first visit. nothing the visitor loads is ever cached, because nothing
// the visitor loads ever reaches this worker.

const CACHE = 'schedule-reader-v54'

const SHELL = [
  './',
  './index.html',
  './running.html',
  './manifest.webmanifest',
  './icon-192.png',
  './icon-512.png',
  './icon-maskable.png',
  './app.css',
  './print.css',
  './app.js',
  './render.js',
  './cite.js',
  './grades.js',
  './store.js',
  './version.js',
  './extract-worker.js',
  './parse-worker.js',
]

self.addEventListener('install', (event) => {
  // bypass the http cache when filling the shell. github pages serves with
  // max-age=600, and installing through that cache can pin a stale stylesheet
  // into a brand new worker, which keeps an old page alive for another visit.
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(SHELL.map((url) => new Request(url, { cache: 'reload' }))))
      .then(() => self.skipWaiting())
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) => Promise.all(names.filter((n) => n !== CACHE).map((n) => caches.delete(n))))
      .then(() => self.clients.claim())
  )
})

self.addEventListener('fetch', (event) => {
  const request = event.request
  if (request.method !== 'GET') return

  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return

  event.respondWith(
    caches.match(request).then((hit) => {
      if (hit) return hit
      return fetch(request).then((response) => {
        // pyodide and pdf.js are large and versioned, so they are worth keeping
        if (response.ok && (url.pathname.includes('/vendor/') || SHELL.some((p) => url.pathname.endsWith(p.slice(1))))) {
          const copy = response.clone()
          caches.open(CACHE).then((cache) => cache.put(request, copy))
        }
        return response
      })
    })
  )
})
