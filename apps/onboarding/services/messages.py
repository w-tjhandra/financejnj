"""Pesan wizard setup (Bahasa Indonesia, aman ditampilkan ke pengguna)."""

from __future__ import annotations

# Navigasi langkah
STEP_ACCOUNT_MISSING = "Langkah 1 (akun) belum selesai."
STEP_PROFILE_MISSING = "Langkah 2 (profil usaha) belum selesai."
STEP_BALANCE_MISSING = "Langkah 3 (saldo awal) belum selesai."
STOCK_INVALID = "Langkah 4 (stok awal) belum lengkap."
SETUP_DONE = "Setup selesai. Selamat bekerja."

# Langkah 1 — akun
USERNAME_REQUIRED = "Username wajib diisi."
USERNAME_FORMAT = "Username 3–30 karakter, hanya huruf, angka, titik, dan garis bawah."
USERNAME_TAKEN = "Username sudah dipakai."
PASSWORD_MISMATCH = "Konfirmasi password tidak sama."
PASSWORD_SAME_AS_USERNAME = "Password tidak boleh sama dengan username."

# Langkah 2 — profil
BUSINESS_NAME_REQUIRED = "Nama usaha wajib diisi."
BUSINESS_START_AFTER_TODAY = "Tanggal mulai usaha tidak boleh melebihi hari ini."

# Tanggal
DATE_INVALID = "Tanggal tidak valid (format YYYY-MM-DD)."
DATE_REQUIRED = "Tanggal wajib diisi."
