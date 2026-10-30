"""Input stok harian: produksi, pemakaian, penyesuaian, dan hapus manual.

Semua operasi menulis movement stok non-transaksi dengan urutan ikatan:
validasi bentuk → `assert_date_editable` → `lock_items` (urut id, cegah
deadlock) → validasi saldo berjalan kumulatif lewat
`stock_api.assert_balance_after_change` (CTE window) → tulis → audit
`stock_movement:create/delete`.

Arah movement:
- produksi telur/kotoran → ``in``
- pemakaian pakan → ``out``
- penyesuaian → ``in`` bila positif, ``out`` bila negatif

Sumber movement yang dihasilkan sini adalah ``manual`` (produksi/pemakaian)
atau ``adjustment`` (penyesuaian); movement bersumber transaksi tidak
sentuh layanan ini.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db import transaction

from audit.service import log_audit, snapshot
from core import messages
from core.errors import DomainError, NotFound, StockConflict
from core.services.locks import assert_date_editable
from core.types import RequestMeta
from core.utils.numbers import format_qty, parse_id_number
from master.models import StockItem
from stock import api as stock_api
from stock.models import StockMovement

QTY_QUANTUM = Decimal("0.001")
QTY_MAX = Decimal("1000000")
REASON_MIN = 10

PRODUCTION_CODES = frozenset({"egg", "manure"})
CONSUMPTION_CODES = frozenset({"feed"})

MOVEMENT_AUDIT_FIELDS = ("stock_item", "date", "direction", "qty", "source", "reason")


def _coerce_date(value: object, *, field: str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            pass
    raise DomainError(
        messages.DATE_INVALID, code="date_invalid", fields={field: messages.DATE_INVALID}
    )


def _coerce_qty(value: object, *, field: str, allow_negative: bool = False) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise DomainError(
            messages.NUMBER_INVALID.format(field=field),
            code="number_invalid",
            fields={field: messages.NUMBER_INVALID.format(field=field)},
        )
    try:
        qty = parse_id_number(
            value,
            places=3,
            field=field,
            min_value=None if allow_negative else Decimal("0"),
            max_value=QTY_MAX,
            allow_negative=allow_negative,
        )
    except DomainError as exc:
        raise DomainError(
            exc.message,
            code="qty_invalid",
            fields={field: exc.message},
        ) from exc
    if qty == 0:
        raise DomainError(messages.QTY_MIN, code="qty_min", fields={field: messages.QTY_MIN})
    return qty


def _negative_message(item: StockItem, when: date, balance: Decimal) -> str:
    return messages.STOCK_WILL_NEGATIVE.format(
        name=item.name,
        date=when.strftime("%d/%m/%Y"),
        balance=format_qty(balance),
        unit=item.unit,
    )


def _apply_balance_guard(item: StockItem, value_date: date, delta: Decimal) -> None:
    """Tolak bila change membuat saldo berjalan negatif pada tanggal manapun."""
    negative = stock_api.assert_balance_after_change(
        stock_item_id=item.pk, date=value_date, delta_by_date={value_date: delta}
    )
    if negative is not None:
        when, balance = negative
        raise StockConflict(
            _negative_message(item, when, balance),
            code="stock_will_negative",
            fields={"qty": _negative_message(item, when, balance)},
        )


def _audit_create(movement: StockMovement, *, actor=None, meta: RequestMeta | None = None):
    log_audit(
        entity="stock_movement",
        entity_id=movement.pk,
        action="create",
        actor=actor,
        after=snapshot(movement, MOVEMENT_AUDIT_FIELDS),
        meta=meta,
    )


def _audit_delete(movement: StockMovement, *, before, actor=None, meta: RequestMeta | None = None):
    log_audit(
        entity="stock_movement",
        entity_id=movement.pk,
        action="delete",
        actor=actor,
        before=before,
        meta=meta,
    )


def record_production(
    *,
    stock_item: StockItem,
    date: object,
    qty: object,
    actor=None,
    meta: RequestMeta | None = None,
) -> StockMovement:
    """Catat produksi telur/kotoran (arah ``in``). Pakan tidak boleh diproduksi."""
    if stock_item.code not in PRODUCTION_CODES:
        raise DomainError(
            messages.DAILY_PRODUKSI_HANYA_TELUR_KOTORAN,
            code="stock_type_invalid",
            fields={"stock_item": messages.DAILY_PRODUKSI_HANYA_TELUR_KOTORAN},
        )
    value_date = _coerce_date(date, field="Tanggal")
    quantity = _coerce_qty(qty, field="Qty")
    assert_date_editable(value_date)

    with transaction.atomic():
        locked = stock_api.lock_items([stock_item.pk])
        item = locked[stock_item.pk]
        _apply_balance_guard(item, value_date, quantity)
        movement = StockMovement.objects.create(
            stock_item=item,
            date=value_date,
            direction="in",
            qty=quantity,
            source="manual",
            created_by=actor if getattr(actor, "pk", None) else None,
        )
        _audit_create(movement, actor=actor, meta=meta)
    return movement


def record_consumption(
    *,
    stock_item: StockItem,
    date: object,
    qty: object,
    actor=None,
    meta: RequestMeta | None = None,
) -> StockMovement:
    """Catat pemakaian pakan (arah ``out``). Telur/kotoran tidak boleh dipakai."""
    if stock_item.code not in CONSUMPTION_CODES:
        raise DomainError(
            messages.DAILY_PEMAKAIAN_HANYA_PAKAN,
            code="stock_type_invalid",
            fields={"stock_item": messages.DAILY_PEMAKAIAN_HANYA_PAKAN},
        )
    value_date = _coerce_date(date, field="Tanggal")
    quantity = _coerce_qty(qty, field="Qty")
    assert_date_editable(value_date)

    with transaction.atomic():
        locked = stock_api.lock_items([stock_item.pk])
        item = locked[stock_item.pk]
        _apply_balance_guard(item, value_date, -quantity)
        movement = StockMovement.objects.create(
            stock_item=item,
            date=value_date,
            direction="out",
            qty=quantity,
            source="manual",
            created_by=actor if getattr(actor, "pk", None) else None,
        )
        _audit_create(movement, actor=actor, meta=meta)
    return movement


def adjust_stock(
    *,
    stock_item: StockItem,
    date: object,
    signed_qty: object,
    reason: str,
    actor=None,
    meta: RequestMeta | None = None,
) -> StockMovement:
    """Penyesuaian stok (+/-). Alasan minimal 10 karakter; hasil tidak negatif."""
    value_date = _coerce_date(date, field="Tanggal")
    delta = _coerce_qty(signed_qty, field="Qty", allow_negative=True)
    reason_text = (reason or "").strip()
    if len(reason_text) < REASON_MIN:
        raise DomainError(
            messages.REASON_MIN_10,
            code="reason_min",
            fields={"reason": messages.REASON_MIN_10},
        )
    assert_date_editable(value_date)

    direction = "in" if delta > 0 else "out"
    with transaction.atomic():
        locked = stock_api.lock_items([stock_item.pk])
        item = locked[stock_item.pk]
        _apply_balance_guard(item, value_date, delta)
        movement = StockMovement.objects.create(
            stock_item=item,
            date=value_date,
            direction=direction,
            qty=abs(delta),
            source="adjustment",
            reason=reason_text,
            created_by=actor if getattr(actor, "pk", None) else None,
        )
        _audit_create(movement, actor=actor, meta=meta)
    return movement


def delete_manual(
    *,
    movement_id: int,
    actor=None,
    meta: RequestMeta | None = None,
) -> StockMovement | None:
    """Soft-delete movement manual; validasi saldo berjalan setelah dihapus.

    Idempoten: movement yang sudah terhapus dikembalikan tanpa menulis ulang.
    Hanya movement sumber ``manual`` (bukan transaksi) yang dihapus lewat sini;
    penyesuaian (`adjustment`) tidak bisa dihapus ( koreksi lewat penyesuaian
    balik).
    """
    with transaction.atomic():
        movement = StockMovement.all_objects.select_for_update().filter(pk=movement_id).first()
        if movement is None:
            raise NotFound(messages.DAILY_MANUAL_TIDAK_DITEMUKAN)
        if movement.transaction_id is not None or movement.source != "manual":
            raise DomainError(
                messages.DAILY_MANUAL_BUKAN_MANUAL,
                code="movement_not_manual",
                fields={"movement": messages.DAILY_MANUAL_BUKAN_MANUAL},
            )
        if movement.deleted_at is not None:
            return movement

        assert_date_editable(movement.date)
        locked = stock_api.lock_items([movement.stock_item_id])
        item = locked[movement.stock_item_id]
        signed = movement.qty if movement.direction == "in" else -movement.qty
        _apply_balance_guard(item, movement.date, -signed)

        before = snapshot(movement, MOVEMENT_AUDIT_FIELDS)
        movement.soft_delete(actor=actor)
        _audit_delete(movement, before=before, actor=actor, meta=meta)
    return movement
