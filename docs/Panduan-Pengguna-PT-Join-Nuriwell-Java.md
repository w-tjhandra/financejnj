# Panduan Pengguna
## Aplikasi PT Join Nuriwell Java

Panduan ini ditujukan untuk pengguna yang mencatat keuangan dan stok harian. Anda
tidak perlu memahami istilah komputer untuk menggunakannya.

> **Alamat aplikasi:** gunakan tautan yang diberikan oleh perusahaan. Jika diminta
> masuk, isi nama pengguna dan kata sandi yang diberikan kepada Anda.

## Mulai menggunakan aplikasi

1. Buka tautan aplikasi, lalu masuk dengan nama pengguna dan kata sandi Anda.
2. Jika ini pertama kali menggunakan akun, ubah kata sandi melalui menu **Akun**.
   Kata sandi baru minimal 10 karakter. Jangan bagikan kata sandi kepada orang lain.
3. Gunakan menu di sisi kiri untuk berpindah halaman. Di ponsel, tekan tombol menu
   untuk menampilkan daftar menu.
4. Tekan **Keluar** setelah selesai, terutama jika menggunakan komputer bersama.

Jika lupa kata sandi, hubungi orang yang mengelola akun aplikasi di perusahaan.

## Pekerjaan harian

### 1. Catat produksi atau pemakaian stok

1. Buka **Stok harian**.
2. Pilih jenis stok, isi jumlah, dan pastikan tanggalnya benar.
3. Tekan **Catat stok**.
4. Periksa perubahan pada bagian **Stok saat ini** dan tabel **Pergerakan harian**.

Gunakan halaman ini untuk mencatat produksi telur atau kotoran, serta pemakaian
pakan. Satuan mengikuti jenis stok yang dipilih, misalnya kg atau karung.

### 2. Catat uang masuk atau keluar

1. Buka **Transaksi**, lalu tekan **Catat transaksi** atau **Transaksi baru**.
2. Isi tanggal kejadian, pilih **Pemasukan** atau **Pengeluaran**, lalu pilih item
   dan kategori yang sesuai.
3. Isi nominal dalam rupiah. Jangan memasukkan tanda minus; pilihan arus menentukan
   apakah uang masuk atau keluar.
4. Jika item terkait stok, isi jumlah (Qty). Satuan akan mengikuti jenis stok.
5. Pilih metode pembayaran bila tersedia. Tambahkan keterangan agar transaksi
   mudah dikenali, misalnya nama pemasok atau tujuan pembayaran.
6. Periksa kembali isian, lalu tekan **Simpan transaksi**.

**Contoh:** penjualan telur dicatat sebagai pemasukan dan jumlah telur yang terjual
diisi pada Qty. Pembelian pakan dicatat sebagai pengeluaran dan jumlah pakan yang
dibeli diisi pada Qty. Untuk item yang tidak terkait stok, Qty tidak mengubah stok.

Setiap transaksi mengurangi atau menambah salah satu dari empat sumber uang:
**BCA, Mandiri, IBK, atau Tunai**. Jika memilih metode **Transfer**, pilih bank
yang menjadi sumber atau tujuan pembayaran. Pembayaran tunai otomatis masuk ke
sumber **Tunai**.

Jika uang dipindahkan antar rekening perusahaan, gunakan menu **Pindah dana**,
bukan mencatatnya sebagai pemasukan atau pengeluaran. Contohnya, setoran uang
tunai ke rekening BCA. Pindah dana mengubah saldo kedua sumber, tetapi tidak
mengubah total saldo perusahaan maupun ringkasan pemasukan dan pengeluaran.

### 3. Periksa ringkasan

Buka **Dashboard** untuk melihat ringkasan pemasukan, pengeluaran, dan selisih
bulan berjalan beserta grafiknya. Gunakan **Rekap harian**, **Rekap mingguan**,
**Rekap bulanan**, atau **Rekap tahunan** untuk memeriksa periode yang lebih rinci.
Dashboard dan rekap juga menampilkan saldo masing-masing sumber serta jumlah
gabungannya.

## Pekerjaan akhir minggu atau akhir bulan

1. Cocokkan transaksi dengan bukti dan catatan perusahaan.
2. Cocokkan stok di aplikasi dengan hasil pemeriksaan fisik. Jika jumlahnya berbeda,
   cari tahu penyebabnya sebelum melakukan penyesuaian.
3. Buka rekap untuk periode yang akan diperiksa. Atur tanggal, bulan, minggu, tahun,
   atau kategori, lalu tekan **Tampilkan**.
4. Jika perlu mengolah atau menyimpan salinan laporan, tekan **Ekspor Excel** atau
   **Export XLSX**. File dapat dibuka menggunakan Microsoft Excel atau aplikasi
   lembar kerja lain.
5. Setelah data periode sudah diperiksa dan disetujui, buka **Kunci periode** lalu
   kunci bulan yang bersangkutan.

**Perhatian:** periode yang dikunci tidak dapat menerima perubahan transaksi,
stok harian, atau penyesuaian stok. Penguncian hanya dapat dilakukan berurutan
tanpa melewati bulan sebelumnya. Membuka kembali hanya diizinkan untuk periode
terkunci yang paling baru dan harus disertai alasan. Karena itu, pastikan laporan
dan stok sudah diperiksa sebelum mengunci.

## Mengoreksi data

- **Transaksi belum berada di periode terkunci:** buka transaksi dari menu
  **Transaksi**, pilih **Edit**, lalu simpan perubahan. Bila menghapus transaksi,
  transaksi akan ditandai dihapus dan dapat dilihat dengan pilihan
  **Tampilkan yang dihapus**.
- **Stok tidak cocok dengan hitungan fisik:** gunakan **Penyesuaian stok**.
  Pilih jenis stok, isi tanggal, lalu masukkan jumlah perubahan. Angka positif
  menambah stok; angka negatif mengurangi stok. Tulis alasan yang jelas (minimal
  10 karakter). Stok akhir tidak boleh kurang dari nol.
- **Saldo awal perlu dikoreksi:** buka **Saldo awal** dan pilih
  **Koreksi Saldo Awal**. Koreksi dicatat sebagai transaksi, bukan menghapus riwayat
  yang sudah ada.
- **Periode terkunci:** jangan membuat data dengan tanggal yang berbeda hanya agar
  bisa menyimpan. Hubungi pengelola atau atasan yang berwenang untuk membuka periode
  sesuai prosedur perusahaan.

## Arti menu

| Menu | Kegunaan |
|---|---|
| **Dashboard** | Ringkasan keuangan dan grafik bulan berjalan. |
| **Transaksi** | Mencatat, mencari, dan memeriksa pemasukan serta pengeluaran. |
| **Saldo awal** | Melihat atau mengatur saldo awal BCA, Mandiri, IBK, dan Tunai. |
| **Pindah dana** | Mencatat perpindahan uang antar sumber tanpa mengubah pemasukan/pengeluaran. |
| **Riwayat aktivitas** | Melihat catatan perubahan yang dilakukan di aplikasi. |
| **Stok harian** | Mencatat hasil produksi dan pemakaian stok setiap hari. |
| **Penyesuaian stok** | Mengoreksi selisih stok dengan alasan yang dicatat. |
| **Pengaturan stok** | Melihat stok awal dan mengatur ambang minimum stok. |
| **Rekap harian/mingguan/bulanan/tahunan** | Memeriksa dan mengekspor laporan untuk periode tertentu. |
| **Item transaksi** | Daftar nama transaksi yang dapat dipilih, seperti penjualan telur atau pembelian pakan. |
| **Kategori** | Pengelompokan transaksi, seperti pakan, gaji, atau penjualan. |
| **Kunci periode** | Mencegah perubahan setelah suatu periode selesai diperiksa. |
| **Profil usaha** | Informasi nama dan kontak usaha. |
| **Akun** | Mengganti kata sandi akun Anda. |

Item, kategori, saldo awal, dan pengaturan stok sebaiknya diubah hanya oleh orang
yang ditunjuk perusahaan. Perubahan pada daftar tersebut dapat memengaruhi cara
transaksi dikelompokkan atau stok dihitung.

## Glosarium sederhana

| Istilah | Arti sederhana |
|---|---|
| **Pemasukan** | Uang yang diterima usaha. |
| **Pengeluaran** | Uang yang dibayarkan usaha. |
| **Arus** | Penanda apakah transaksi termasuk pemasukan atau pengeluaran. |
| **Nominal** | Nilai uang transaksi dalam rupiah. |
| **Item** | Nama kejadian atau jenis transaksi yang dicatat. |
| **Kategori** | Kelompok untuk merapikan transaksi dan laporan. |
| **Qty** | Jumlah barang atau stok; isi satuannya juga, misalnya kg atau karung. |
| **Saldo awal** | Saldo kas atau jumlah stok yang tersedia pada awal pencatatan. |
| **Saldo sumber** | Saldo uang pada satu tempat penyimpanan, yaitu BCA, Mandiri, IBK, atau Tunai. |
| **Pindah dana** | Perpindahan uang antar sumber milik perusahaan; bukan pemasukan atau biaya baru. |
| **Saldo berjalan** | Perkiraan saldo setelah pemasukan, pengeluaran, atau pergerakan stok dihitung. |
| **Ambang minimum** | Batas stok untuk membantu menandai persediaan yang mulai menipis. |
| **Penyesuaian stok** | Penambahan atau pengurangan stok untuk menyamakan catatan dengan kondisi sebenarnya. |
| **Selisih** | Perhitungan pemasukan dikurangi pengeluaran, ditambah koreksi saldo awal bila ada. |
| **Mutasi non-operasional** | Koreksi saldo awal yang ditampilkan terpisah dari pemasukan dan pengeluaran biasa. |
| **Kunci periode** | Pengaturan yang membuat data pada bulan tersebut tidak dapat diubah. |
| **Riwayat aktivitas** | Catatan siapa yang melakukan perubahan dan kapan perubahan dilakukan. |
| **Ekspor Excel / XLSX** | Mengunduh laporan sebagai file lembar kerja untuk disimpan atau diolah. |

## Hal penting tentang angka dan laporan

- Gunakan **tanggal kejadian yang sebenarnya**, bukan tanggal saat Anda baru sempat
  mencatat.
- Periksa kembali angka, kategori, dan satuan sebelum menyimpan. Contohnya, jangan
  mencatat jumlah pakan dalam kg jika satuan itemnya adalah karung.
- Pemasukan atau pengeluaran yang terkait dengan stok juga mengubah jumlah stok:
  penjualan/pengeluaran barang mengurangi stok, sedangkan pembelian/penerimaan
  menambah stok. **Stok harian** tetap perlu dipakai untuk mencatat produksi atau
  pemakaian rutin.
- Nilai **Selisih** pada aplikasi adalah ringkasan arus uang yang dicatat. Nilai
  ini tidak otomatis sama dengan laba akuntansi atau laporan keuangan lengkap;
  perhitungannya tidak menggantikan pemeriksaan dan pencatatan akuntansi perusahaan.
- **Saldo kas** dan **saldo berjalan** di aplikasi adalah hasil perhitungan dari
  saldo awal serta transaksi yang dicatat. Cocokkan dengan uang fisik dan catatan
  bank perusahaan.
- Laporan akan mengikuti tanggal dan kategori yang dipilih. Jika hasil terlihat
  kosong atau berbeda, periksa kembali pilihan filternya.

## Jika menemui masalah

- **Tidak bisa menyimpan:** baca pesan yang muncul, lalu periksa tanggal, nominal,
  Qty, satuan, dan alasan penyesuaian. Kolom yang wajib biasanya diberi tanda atau
  pesan.
- **Stok tidak cukup:** cek catatan stok dan tanggal pergerakannya. Jangan membuat
  stok minus; minta pemeriksaan fisik atau persetujuan penanggung jawab.
- **Data tidak dapat diubah:** periksa apakah bulannya sudah dikunci. Hubungi
  pengelola atau atasan yang berwenang.
- **Angka rekap tidak sesuai:** periksa rentang tanggal, kategori, transaksi yang
  ditandai dihapus, serta apakah koreksi saldo awal tercantum.
- **Masih membutuhkan bantuan:** kirim nama halaman, tanggal transaksi, dan pesan
  yang terlihat kepada pengelola aplikasi. Jangan mengirim kata sandi.
