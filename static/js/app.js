/*
 * JS aplikasi < 6 KB (rancangan §1.8). Tanpa framework build:
 * - HTMX otomatis mengirim header CSRF dari atribut body (lihat base.html).
 * - Alpine store `toasts` dipakai untuk notifikasi non-HTMX/HTMX.
 */
(function () {
  "use strict";

  document.addEventListener("alpine:init", function () {
    window.Alpine.store("toasts", {
      items: [],
      push: function (message, timeout) {
        var id = Date.now() + Math.random();
        this.items.push({ id: id, message: message });
        var self = this;
        window.setTimeout(function () {
          self.items = self.items.filter(function (item) {
            return item.id !== id;
          });
        }, timeout || 4000);
      },
      clear: function () {
        this.items = [];
      },
    });
  });
})();
