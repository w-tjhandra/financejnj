"""Penulisan pengaturan stok (S-16, FR-06).

Nama/kode/satuan tiga jenis stok tetap (AC-06.4). Hanya ambang minimum dan
stok awal yang bisa diubah; stok awal terkunci per jenis setelah movement
pertama jenis itu, termasuk movement yang kemudian dihapus (BR-01).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db import transaction

from audit.service import diff, log_audit, snapshot
from core import messages
from core.errors import DomainError
from master.models import StockItem
from stock.queries import stock_locked_since

AUDIT_FIELDS = ("opening_qty", "min_threshold")
QTY_MAX = Decimal("1000000")


def _as_decimal(value: object, *, field: str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):  # pragma: no cover - dijaga agar tidak lolos
        raise DomainError(f"{field} harus berupa angka.", code="number_invalid")
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise DomainError(
            messages.NUMBER_INVALID.format(field=field), code="number_invalid"
        ) from exc


def _validate_qty(value: Decimal, *, field: str) -> Decimal:
    if value < 0:
        raise DomainError(f"{field} tidak boleh negatif.", code="qty_negative")
    if value > QTY_MAX:
        raise DomainError(f"{field} maksimum 1.000.000.", code="qty_max")
    return value


def update_stock_settings(
    *,
    stock_item_id: int,
    min_threshold: object = None,
    opening_qty: object = None,
    actor=None,
    meta=None,
) -> StockItem:
    """Simpan ambang dan/atau stok awal satu jenis stok; audit hanya saat berubah."""
    new_threshold = (
        None if min_threshold is None else _as_decimal(min_threshold, field="Ambang minimum")
    )
    if new_threshold is not None:
        new_threshold = _validate_qty(new_threshold, field="Ambang minimum")

    new_opening = None
    if opening_qty is not None:
        new_opening = _validate_qty(_as_decimal(opening_qty, field="Stok awal"), field="Stok awal")

    with transaction.atomic():
        stock_item = StockItem.objects.select_for_update().get(pk=stock_item_id)
        locked_since = stock_locked_since(stock_item.pk)
        if locked_since is not None and new_opening is not None:
            if new_opening != stock_item.opening_qty:
                message = messages.stock_opening_locked(locked_since)
                raise DomainError(
                    message,
                    code="stock_opening_locked",
                    fields={"opening_qty": message},
                )

        before = snapshot(stock_item, AUDIT_FIELDS)
        if new_opening is not None:
            stock_item.opening_qty = new_opening
        stock_item.min_threshold = new_threshold
        stock_item.save(update_fields=["opening_qty", "min_threshold", "updated_at"])

        changed_before, changed_after = diff(before, snapshot(stock_item, AUDIT_FIELDS))
        if changed_before:
            log_audit(
                entity="stock_item",
                entity_id=stock_item.pk,
                action="update",
                actor=actor,
                before=changed_before,
                after=changed_after,
                meta=meta,
            )
        return stock_item
