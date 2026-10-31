# Vendor JS (lokal, tanpa CDN saat runtime)

Semua berkas diunduh **sekali** saat pengembangan, di-commit, dan disajikan dari
`/static/vendor/`. Template tidak boleh memuat URL eksternal.

| Berkas | Versi | Sumber unduhan | Lisensi | SHA-256 |
|---|---|---|---|---|
| `htmx-2.0.4.min.js` | 2.0.4 | https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js | BSD-2-Clause | `e209dda5c8235479f3166defc7750e1dbcd5a5c1808b7792fc2e6733768fb447` |
| `alpine-3.14.9.min.js` | 3.14.9 | https://cdn.jsdelivr.net/npm/alpinejs@3.14.9/dist/cdn.min.js | MIT | `3ed1eed252488921df65e363d6715deb04d7f92aaedb9e52199fdf73cb1e0ad3` |
| `chart-4.4.7.umd.min.js` | 4.4.7 | https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js | MIT | `206b6e8bb00fc7bba2c7ee80ca41db3e9e05ba7be0aa35abeba9cfd5357f5d0e` |

Cara memverifikasi ulang:

```bash
sha256sum static/vendor/*
```

Catatan: Chart.js 4 memakai lisensi MIT. Alpine dan HTMX juga MIT/BSD-2; tidak ada
komponen berlisensi copyleft di runtime.

## Web font

Space Grotesk dilayani lokal dari `/static/fonts/` agar tipografi tetap konsisten
tanpa permintaan ke CDN saat aplikasi dibuka.

| Berkas | Versi | Sumber unduhan | Lisensi | SHA-256 |
|---|---|---|---|---|
| `space-grotesk-latin.woff2` | v22 | https://fonts.gstatic.com/s/spacegrotesk/v22/V8mDoQDjQSkFtoMM3T6r8E7mPbF4Cw.woff2 | SIL OFL 1.1 (`OFL.txt`) | `0640890476fc1198ab4de571fb658de443c4d85b66466ec09534a8737ab1ce9d` |
