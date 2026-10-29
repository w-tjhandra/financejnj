# Keputusan Teknis & Klarifikasi

Dokumen ini mencatat keputusan yang mengikat implementasi. Sumber: `02-prd.md` v1.1,
`03-build.md`, dan keputusan Orch untuk K-00…K-12.

## 1. Keputusan Orch (K-00…K-12)

| ID | Keputusan | Alasan singkat |
|---|---|---|
| **K-00** | **Opsi A**: kunci berantai + guard `max_locked`; unlock hanya untuk bulan terkunci **terakhir**. AC-30.8 diamandemen: untuk mengedit September, buka Oktober dulu, lalu September. | D4/BR-12 menang agar angka bulan terkunci tidak bisa berubah tanpa unlock eksplisit. Guard per bulan (Opsi B) membuka celah integritas. |
| **K-01** | Periode yang **dimulai tepat** pada `opening_balance_date` memuat saldo awal; pra-opening memakai strict `<`. | Mengikuti AC-19.1/AC-07.1 (September = 250 jt), bukan BR-09a yang menulis `<=`. |
| **K-02** | Pesan UI memakai nama bulan Indonesia, mis. `Periode September 2026 terkunci.`; kode `2026-09` hanya di log/`extra`. | Menyatukan AC-08.9 dan AC-30.2 pada bentuk yang lebih ramah pengguna. |
| **K-03** | Transaksi koreksi saldo awal **read-only**; koreksi balik dibuat lewat S-17 (delta berlawanan), bukan edit/hapus. | Menjaga semantik mutasi non-operasional dan jejak audit. |
| **K-04** | Mengganti **nama** item/kategori tetap boleh walau dipakai di bulan terkunci. | BR-06/BR-12 hanya melarang nonaktif/ubah tautan; E-24 menyatakan transaksi lama ikut nama baru. |
| **K-05** | Ringkasan export sepenuhnya **global** (empat baris, saldo, stok, per kategori) + label `(semua kategori)` + daftar filter aktif. | Menghindari angka Ringkasan yang tampak tidak konsisten dengan sheet rincian. |
| **K-06** | Harga rata-rata info dihitung per **jenis stok**, bukan per item. | Sesuai FR-21/AC-21.4: Σ nominal ÷ Σ qty transaksi yang menghasilkan movement pada stok itu. |
| **K-07** | PDF **tanpa tanda tangan**; struktur siap ditambah gambar statis bila diminta. | Q-004 belum dijawab; NS-15 melarang grafik, bukan tanda tangan. |
| **K-08** | Total daftar transaksi hanya menjumlahkan **baris aktif**; baris terhapus ditampilkan terpisah. | Menjaga total sesuai data yang masih berlaku (AC-11.3/17.4). |
| **K-09** | Batas kategori gaji LAYER/DOC/UMUM berlaku untuk **semua** item `frequency=monthly`, termasuk item kustom. | Konsisten dengan unique constraint gaji dan tabel “Gaji per bulan gaji”. |
| **K-10** | Logo & lampiran disajikan lewat **view berautentikasi**; `media/` tidak dipetakan ke URL publik. | NFR-10/NFR-11; mencegah akses publik dan tebak URL. |
| **K-11** | Rekap mingguan mendapat filter **bulan/tahun** (opsional UI) memakai `weeks_in_month`. | Memberi jalur uji AC-18.2 tanpa mengubah definisi minggu ISO. |
| **K-12** | Lampiran transaksi terhapus terlihat lewat detail `show_deleted=1`; URL lampiran mensyaratkan `show_deleted=1`. | Menyelaraskan AC-33.5 dengan BR-05a (file tidak dihapus saat transaksi dihapus). |

## 2. Keputusan teknis yang sudah diterapkan

| ID | Keputusan | Alasan |
|---|---|---|
| D-01 | Kolom teknis `transactions.idempotency_key`, `stock_movements.batch_key`, `items.code`. | Idempotensi double submit dan lookup item sistem yang stabil saat nama berubah. |
| D-02 | Nama tabel fisik mengikuti app (`ledger_transaction`, dst.). | Default Django; PRD §8 adalah model konseptual. |
| D-03 | Master bisnis di-seed saat setup, bukan data migration. | Instalasi baru harus benar-benar kosong agar guard setup teruji. |
| D-04 | Penyesuaian stok tidak bisa dihapus; koreksi lewat penyesuaian balik. | Menjaga alasan historis dan jejak audit. |
| D-09 | Audit ditulis sejak T-006, bukan retrofit. | Tidak ada operasi domain yang lolos audit. |
| D-15 | `PeriodLock` ditempatkan di app `core`. | Guard dipakai semua app; `core` adalah dependency root. |

## 3. Deviasi kecil T-006.1

| Hal | Keputusan | Alasan |
|---|---|---|
| `ledger.Attachment.updated_at` | Ada (warisan `SoftDeleteModel`), meski rancangan §2.10 hanya menyebut `created_at`/`deleted_at`. | Konsistensi base model; tidak menambah field bisnis dan aman untuk fase berikut. |
| Nama constraint | Dipendekkan agar ≤30 karakter, mis. `uniq_movement_txn_stock`, `adjustment_reason_min10`, `movement_source_transaction`. | Batas nama index/constraint lintas backend; makna tetap sama. |
| GIN trigram `notes` | Dibuat di `ledger.0002_txn_gin_notes` setelah `core.0002_pg_trgm`, dan dicatat juga di `Transaction.Meta`. | Extension harus ada sebelum index; state migrasi tetap sinkron dengan model. |
| `AuditLog` append-only | `save()` hanya untuk insert; `QuerySet.update/delete` dan `Model.delete()` ditolak. | BR-14/AC-32.4; tidak ada jalur ORM biasa untuk mengubah audit. |
| Regex alasan adjustment | Memakai `^.{10,}$`; batas maksimum 300 dijaga `CharField(max_length=300)`. | PostgreSQL menolak repetition count >255: pola `^.{10,300}$` menghasilkan `invalid repetition count(s)` (ditemukan test). |
