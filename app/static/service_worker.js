//https://developers.google.com/web/fundamentals/primers/service-workers

// Font files
var fontFiles = [
	'/static/fonts/feather/feather.ttf',
];

//this is just an empty service worker so that the 'Install CB as an app' prompt appears in web browsers
self.addEventListener('install', function(event) {
  event.waitUntil(caches.open('core').then(function (cache) {
		fontFiles.forEach(function (file) {
			cache.add(new Request(file));
		});
		return;
	}));
});

self.addEventListener('fetch', function(event) {
    // Fonts
    // Offline-first
    if (request.url.includes('feather.ttf')) {
        event.respondWith(
            caches.match(request).then(function (response) {
                return response || fetch(request).then(function (response) {
                    // Return the requested file
                    return response;
                });
            })
        );
    }
});
