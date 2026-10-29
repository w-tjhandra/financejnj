/*
 * JS aplikasi < 6 KB (rancangan §1.8). Tanpa framework build:
 * - HTMX otomatis mengirim header CSRF dari atribut body (lihat base.html).
 * - Alpine store `toasts` dipakai untuk notifikasi non-HTMX/HTMX.
 */
(function () {
  "use strict";

  // Form master memakai 400/422 untuk error validasi. HTMX secara default
  // tidak menukar respons non-2xx; izinkan agar pesan error tampil di panel.
  document.addEventListener("htmx:beforeSwap", function (event) {
    var status = event.detail.xhr.status;
    if (status === 400 || status === 409 || status === 422) {
      event.detail.shouldSwap = true;
      event.detail.isError = false;
    }
  });

  // HX-Trigger: {"toast": {"msg": "..."}} dari view.
  document.body.addEventListener("toast", function (event) {
    var message = event.detail && event.detail.msg;
    if (!message || !window.Alpine) {
      return;
    }
    window.Alpine.store("toasts").push(message, 4000);
  });

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
