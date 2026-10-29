"""Pesan pengguna yang dikutip acceptance criteria (rancangan §3.11).

Implementasi dan test memakai konstanta ini; jangan menulis ulang string yang
sudah ditetapkan AC. Placeholder memakai ``str.format``.
"""

from __future__ import annotations

from datetime import date

from core.utils.dates import format_date_id, format_date_short, format_month_id

# --- Auth & setup ---------------------------------------------------------
RATE_LIMITED = "Terlalu banyak percobaan. Coba lagi dalam 15 menit."
SESSION_EXPIRED = "Sesi berakhir, silakan masuk kembali."
LOGIN_FAILED = "Username atau kata sandi salah"
PASSWORD_MIN = "Password minimal 10 karakter"
PASSWORD_SAME_AS_USERNAME = "Kata sandi tidak boleh sama dengan nama pengguna."
PASSWORD_MISMATCH = "Konfirmasi kata sandi tidak sama."
OLD_PASSWORD_INCORRECT = "Kata sandi lama salah."
PASSWORD_CHANGED = "Kata sandi berhasil diperbarui."

# --- Profil usaha ---------------------------------------------------------
BUSINESS_NAME_REQUIRED = "Nama usaha wajib diisi"
EMAIL_INVALID = "Format email tidak valid."
PROFILE_SAVED = "Profil usaha disimpan."

# --- Master data ----------------------------------------------------------
CATEGORY_SYSTEM = "Kategori sistem tidak bisa dihapus."
CATEGORY_IN_USE = "Kategori sudah dipakai {count} transaksi. Nonaktifkan saja."
CATEGORY_CODE_TAKEN = "Kode kategori sudah dipakai"
CATEGORY_DEPTH = "Maksimal satu tingkat."
CATEGORY_REQUIRED = "Kode dan nama kategori wajib diisi."
CATEGORY_HAS_CHILDREN = "Kategori masih punya subkategori."
CATEGORY_PARENT_INACTIVE = "Induk kategori tidak aktif."
CATEGORY_USED_LOCKED = "Kategori dipakai pada periode terkunci ({month} {year})."
ITEM_STOCK_UNIT = "Item terkait stok wajib memilih jenis stok."
ITEM_NAME_TAKEN = "Nama item sudah dipakai untuk arus ini."
ITEM_SYSTEM = "Item sistem tidak bisa dihapus."
ITEM_IN_USE = "Item sudah dipakai {count} transaksi. Nonaktifkan saja."
ITEM_USED_LOCKED = "Item dipakai pada periode terkunci ({month} {year})."
ITEM_USED_NOTE = "Sudah dipakai {count} transaksi"
ITEM_USED_FIELD_LOCKED = "Item sudah dipakai {count} transaksi; {field} tidak bisa diubah."
ITEM_STOCK_DIRECTION = "Arah stok tidak sesuai arus item."
ITEM_FLOW_INVALID = "Arus item tidak valid."
ITEM_FREQUENCY_INVALID = "Frekuensi item tidak valid."
ITEM_CATEGORY_INACTIVE = "Kategori default tidak aktif."
STOCK_UNIT_FIXED = "Satuan stok tidak bisa diubah."
STOCK_NOT_FOUND = "Jenis stok tidak ditemukan."
STOCK_OPENING_LOCKED = "Terkunci sejak {date}. Gunakan penyesuaian."
STOCK_SETTINGS_SAVED = "Pengaturan stok disimpan."

# --- Saldo awal & tanggal -------------------------------------------------
DATE_AFTER_TODAY = "Tanggal saldo awal tidak boleh melebihi hari ini."
DATE_BEFORE_BUSINESS_START = "Tanggal saldo awal tidak boleh sebelum tanggal mulai usaha ({date})"
DATE_INVALID = "Format tanggal tidak valid."
OPENING_BALANCE_LOCKED = "Saldo awal terkunci karena sudah ada transaksi."
OPENING_BALANCE_SAVED = "Saldo awal disimpan."
DATE_BEFORE_OPENING = "Tanggal transaksi tidak boleh sebelum tanggal saldo awal ({date})."
TXN_DATE_AFTER_TODAY = "Tanggal tidak boleh melebihi hari ini."

# --- Angka ----------------------------------------------------------------
NUMBER_INVALID = "{field} harus berupa angka."
AMOUNT_MIN = "Nominal harus lebih dari 0"
AMOUNT_MAX = "Nominal maksimum Rp 100.000.000.000."
QTY_MIN = "Qty harus lebih dari 0."
QTY_MAX = "Qty maksimum 1.000.000."
AMOUNT_RANGE = "Nominal minimum tidak boleh lebih besar dari maksimum"

# --- Transaksi & stok -----------------------------------------------------
QTY_REQUIRED = "Qty wajib untuk item terkait stok"
STOCK_INSUFFICIENT_DETAIL = (
    "Stok {name} pada {date} hanya {qty} {unit}; tidak cukup untuk {requested} {unit}."
)
STOCK_CONFLICT = "Stok {name} tidak cukup: tersedia {qty} {unit}; diminta {requested} {unit}"
STOCK_WILL_NEGATIVE = "Stok {name} akan minus pada {date} ({balance} {unit})"
STOCK_DAILY_INSUFFICIENT = "Stok {name} tidak cukup: tersedia {qty} {unit}."
ADJUSTMENT_NEGATIVE = "Penyesuaian akan membuat stok {name} negatif (hasil: {result} {unit})."
DAILY_EMPTY = "Isi minimal satu jumlah."
REASON_MIN_10 = "Alasan minimal 10 karakter."
SALARY_CATEGORY = "Gaji hanya untuk kategori LAYER, DOC, atau UMUM."
PERIOD_LOCKED_SHORT = "Periode terkunci."

# --- Kunci periode --------------------------------------------------------
PERIOD_LOCKED = "Periode {month} {year} terkunci. Buka kunci terlebih dahulu."
CHAIN_GAP = "Kunci {month} {year} terlebih dahulu (tidak boleh ada lubang)."
UNLOCK_REASON = "Alasan buka kunci wajib (minimal 10 karakter)."
ALREADY_LOCKED = "Periode {month} {year} sudah terkunci."
NOT_LOCKED = "Periode {month} {year} belum terkunci."
UNLOCK_LATEST_FIRST = "Buka kunci {month} {year} terlebih dahulu."

# --- Lampiran & logo ------------------------------------------------------
ATTACHMENT_TYPE = "Tipe file harus JPG, PNG, WEBP, atau PDF."
ATTACHMENT_SIZE = "Ukuran maksimum 10 MB."
ATTACHMENT_LIMIT = "Maksimum 5 lampiran per transaksi."
LOGO_TYPE = "Logo harus PNG atau JPG."

# --- Export ---------------------------------------------------------------
EXPORT_RANGE = "Rentang export maksimum 366 hari."


def _period_parts(period: date) -> dict[str, str | int]:
    return {"month": format_month_id(period).rsplit(" ", 1)[0], "year": period.year}


def period_locked(period: date) -> str:
    return PERIOD_LOCKED.format(**_period_parts(period))


def chain_gap(period: date) -> str:
    return CHAIN_GAP.format(**_period_parts(period))


def already_locked(period: date) -> str:
    return ALREADY_LOCKED.format(**_period_parts(period))


def not_locked(period: date) -> str:
    return NOT_LOCKED.format(**_period_parts(period))


def unlock_latest_first(period: date) -> str:
    return UNLOCK_LATEST_FIRST.format(**_period_parts(period))


def item_used_locked(period: date) -> str:
    return ITEM_USED_LOCKED.format(**_period_parts(period))


def category_used_locked(period: date) -> str:
    return CATEGORY_USED_LOCKED.format(**_period_parts(period))


def date_before_business_start(value: date) -> str:
    return DATE_BEFORE_BUSINESS_START.format(date=format_date_short(value))


def date_before_opening(value: date) -> str:
    return DATE_BEFORE_OPENING.format(date=format_date_short(value))


def stock_opening_locked(value: date) -> str:
    return STOCK_OPENING_LOCKED.format(date=format_date_id(value))
