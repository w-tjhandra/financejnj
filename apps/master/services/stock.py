"""Guard master stok (FR-06).

Kode, nama, dan satuan tiga jenis stok adalah bagian dari skema laporan dan
tidak boleh berubah. Perubahan stok awal/ambang ditangani layar S-16 pada
tahap berikutnya; modul ini hanya menjaga kolom yang tetap (AC-06.4).
"""

from __future__ import annotations

from core import messages
from core.errors import DomainError
from master.models import StockItem


def reject_stock_unit_change(*, stock_item: StockItem | None = None) -> None:
    """Endpoint/aksi yang mencoba mengubah satuan selalu ditolak 400."""
    raise DomainError(
        messages.STOCK_UNIT_FIXED,
        code="stock_unit_fixed",
        http_status=400,
        fields={"unit": messages.STOCK_UNIT_FIXED},
    )


def update_stock_unit(*, stock_item_id: int, unit: object, actor=None, meta=None) -> None:
    """Sengaja menolak; disediakan agar jalur tulis tetap satu pintu."""
    StockItem.objects.get(pk=stock_item_id)  # memastikan jenis stok ada
    reject_stock_unit_change()
