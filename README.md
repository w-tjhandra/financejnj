# Telur Finance

Aplikasi pencatatan keuangan & stok peternakan telur. Monolit Django server-rendered
(HTMX + Alpine + Chart.js lokal), PostgreSQL 16, tanpa CDN.

Status: **fondasi (T-005a)** — auth, layout, health check, pipeline aset. Modul bisnis menyusul.

## Menjalankan

Prasyarat: Docker 24+ dengan `docker compose`.

```bash
cp .env.example .env      # opsional; nilai default compose sudah cukup untuk dev
docker compose build
docker compose up -d      # db + app; migrasi dijalankan otomatis oleh entrypoint
```

Buka http://localhost:8000 — diarahkan ke `/masuk`. Belum ada user: buat manual

```bash
docker compose run --rm app python manage.py createsuperuser
```

Health check: `curl http://localhost:8000/healthz` → `{"status":"ok","db":"ok"}`.

## Deploy ke Ubuntu dengan PostgreSQL native

Compose produksi tidak membuat container PostgreSQL. Django berjalan di Docker
dan terhubung ke PostgreSQL yang terpasang langsung di host Ubuntu melalui
`host.docker.internal`. Pastikan PostgreSQL memiliki database `financejnj` dan
user `financeuser` dengan hak akses yang sesuai.

Salin template lalu atur domain, password user PostgreSQL yang sebenarnya, dan
secret Django acak di server:

```bash
cp .env.production.example .env
openssl rand -base64 48  # isi DJANGO_SECRET_KEY dengan hasilnya
chmod 600 .env
nano .env
```

Pasang client PostgreSQL agar script dapat membuat backup sebelum deploy:

```bash
sudo apt install postgresql-client
```

Compose menambahkan alias host Docker untuk `host.docker.internal`. PostgreSQL
native biasanya hanya listen di localhost, jadi atur `listen_addresses` agar
menerima koneksi dari gateway Docker, lalu tambahkan aturan `pg_hba.conf` untuk
subnet network Compose. Script membuat backup dari host melalui
`POSTGRES_BACKUP_HOST` (default `127.0.0.1`); sesuaikan jika PostgreSQL Anda
mendengarkan di alamat lain. Ambil gateway Docker default dan subnet Compose:

```bash
docker network inspect bridge \
  --format '{{(index .IPAM.Config 0).Gateway}}'
docker network inspect telur-finance_telur-network \
  --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}'
```

Jangan membuka port 5432 ke internet. Batasi `pg_hba.conf` dan firewall hanya
untuk subnet Docker yang diperlukan. Jika memakai UFW, jangan menambahkan aturan
yang mengizinkan port 5432 dari semua alamat. Setelah mengubah konfigurasi
PostgreSQL, restart service PostgreSQL. Isi `DJANGO_ALLOWED_HOSTS` dan
`DJANGO_CSRF_TRUSTED_ORIGINS` sesuai domain.

Password database yang pernah dibagikan sebaiknya diganti sebelum deploy; jangan
simpan password asli di Git. `POSTGRES_PASSWORD` di `.env` harus cocok dengan
password user PostgreSQL yang aktif.

Jalankan script deploy. Pada checkout Git, script menarik branch `main`; pada
folder source yang diunggah/manual, script memakai file yang sudah ada tanpa
`git pull`. Script membuat backup database, membangun aplikasi, menyesuaikan
ownership volume static/media, lalu menyalakan Django dan Caddy tanpa
membuat/menghapus PostgreSQL:

```bash
./deploy.sh
docker compose --env-file .env -f docker-compose.prod.yml ps
docker compose --env-file .env -f docker-compose.prod.yml logs -f app
```

Di produksi, service `period-locker` memeriksa penutupan periode setiap menit.
Pada tanggal 1 setelah pukul 00.05 WIB, service mengunci bulan sebelumnya.
Jika service baru pulih setelah tanggal 1, ia mengejar penguncian yang tertunda.
Periode yang sudah dikunci dapat dibuka kembali melalui aplikasi dengan alasan
yang tercatat di audit. Jika urutan kunci belum lengkap, periode tidak dikunci
paksa; periksa log service dan selesaikan periode yang tertinggal:

```bash
docker compose --env-file .env -f docker-compose.prod.yml logs -f period-locker
```

Tanggal mulai penggunaan aplikasi diisi terpisah dari tanggal mulai usaha.
Kunci Periode menampilkan 12 bulan terbaru sampai bulan berjalan; gunakan
pencarian bulan untuk membuka riwayat lain dan tautan rekap untuk melihat atau
mengekspor XLSX.

Port publik 80/443 tetap dikelola web server yang sudah ada di host. Caddy
container hanya bind ke `127.0.0.1:8080` (atau nilai `PROXY_PORT` di `.env`)
dan melayani HTTP di belakang reverse proxy tersebut. Untuk Nginx, konfigurasi
proxy pada virtual host HTTPS yang sudah ada dapat menggunakan:

```nginx
location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Pastikan virtual host meneruskan `/static/` dan `/media/` ke upstream ini juga,
agar Caddy menyajikan file dari volume. Konfigurasi TLS dan redirect
HTTP-ke-HTTPS tetap di web server host; Caddy tidak mengelola sertifikat domain
ini. PostgreSQL dikelola oleh Ubuntu, terpisah dari Compose.

## Perintah umum

```bash
make up          # docker compose up -d
make test        # pytest di container
make migrate     # migrate manual
make css         # build ulang static/css/app.css (Tailwind, tanpa Node)
make check       # migrasi terkini + check + test
make logs        # log app
```

Perintah Python **selalu** lewat container (host tidak punya pip):

```bash
docker compose run --rm app python manage.py <perintah>
```

## Struktur

```
config/settings/{base,dev,test,prod}.py   # setelan per environment
apps/                                     # app Django (nama polos, ada di sys.path)
  core audit master stock ledger reports exports onboarding
templates/                                # base, partials, per-app
static/{src,css,js,vendor}/               # aset; CSS & vendor di-commit
tests/                                    # smoke test lintas-app
```

Tanggung jawab app dan aturan dependensi: lihat rancangan teknis
(`workspace/T-001-telur-finance/03-build.md` §1).

## Aset

- Tailwind **standalone CLI v3.4.17** diunduh saat build image dengan checksum SHA-256.
  Hasil build `static/css/app.css` di-commit; runtime tidak menjalankan Tailwind.
- Vendor JS (HTMX 2.0.4, Alpine 3.14.9, Chart.js 4.4.7) ada di `static/vendor/`,
  versi dan checksum dicatat di `static/vendor/VENDOR.md`.

## Konfigurasi

Semua lewat environment (`.env.example`). Kunci: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`,
`DJANGO_ALLOWED_HOSTS`, `POSTGRES_DB/USER/PASSWORD/HOST/PORT` (atau `DATABASE_URL`).
Produksi memakai `config.settings.prod` dan menolak start tanpa `DJANGO_SECRET_KEY`
serta `DJANGO_ALLOWED_HOSTS`.
