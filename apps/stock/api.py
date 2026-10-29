"""Antarmuka stok yang dipakai ledger (D1, BR-03).

Modul ini adalah satu-satunya pintu bagi `ledger.services.*` untuk mengunci,
memvalidasi, dan menulis movement. Semua operasi tulis harus dipanggil di dalam
`transaction.atomic()` milik service pemanggil; `lock_items` sendiri tidak
membuka transaksi.
"""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager
from datetime import date
from decimal import Decimal

from django.db import connection
from django.utils import timezone

from core import messages
from core.errors import DomainError
from master.models import StockItem
from stock.models import StockMovement

DIRECTION_BY_FLOW = {"income": "out", "expense": "in"}


def direction_for(flow: str) -> str:
    """Arah movement yang sah: income→out, expense→in (I-3)."""
    try:
        return DIRECTION_BY_FLOW[flow]
    except KeyError as exc:
        raise DomainError(messages.ITEM_FLOW_INVALID, code="flow_invalid") from exc


def lock_items(ids: Iterable[int]) -> dict[int, StockItem]:
    """Kunci baris `stock_items` urut id (deterministik, cegah deadlock).

    Mengembalikan peta ``id -> StockItem`` agar pemanggil tidak perlu query
    ulang setelah lock. Wajib dipanggil di dalam transaksi DB.
    """
    item_ids = sorted({int(item_id) for item_id in ids})
    if not item_ids:
        return {}
    rows = list(StockItem.objects.select_for_update().filter(id__in=item_ids).order_by("id"))
    _run_after_lock_hook()
    return {row.pk: row for row in rows}


def on_hand(stock_item_id: int, as_of: date | None = None) -> Decimal:
    """Stok berjalan dari movement aktif; ``as_of`` inklusif."""
    stock_item = StockItem.objects.get(pk=stock_item_id)
    movements = StockMovement.objects.filter(stock_item_id=stock_item_id)
    if as_of is not None:
        movements = movements.filter(date__lte=as_of)
    total_in = Decimal("0")
    total_out = Decimal("0")
    for direction, qty in movements.values_list("direction", "qty"):
        if direction == "in":
            total_in += qty
        else:
            total_out += qty
    return stock_item.opening_qty + total_in - total_out


def peek_available(stock_item_id: int, as_of: date) -> Decimal:
    """Stok tersedia pada tanggal, hanya untuk memilih pesan pre-check.

    Hasilnya **tidak** menggatingkan penulisan; keputusan akhir diambil setelah
    `lock_items` dan `assert_balance_after_change`.
    """
    return on_hand(stock_item_id, as_of=as_of)


def assert_balance_after_change(
    *,
    stock_item_id: int,
    date: date,
    delta_by_date: dict[date, Decimal],
) -> tuple[date, Decimal] | None:
    """Validasi saldo kumulatif setelah delta diterapkan (BR-03).

    Semua tanggal ≥ tanggal terdampak terkecil dievaluasi. Mengembalikan
    ``(tanggal, saldo)`` pertama yang negatif, atau ``None`` bila aman.
    Urutan same-day adalah ``in`` sebelum ``out``, sehingga saldo akhir hari
    adalah titik minimum hari itu dan cukup diperiksa per tanggal.
    """
    deltas = {key: Decimal(value) for key, value in (delta_by_date or {}).items()}
    if not deltas:
        return None
    first_date = min([date, *deltas.keys()])
    adjustment_dates = sorted(deltas)

    stock_table = StockItem._meta.db_table
    movement_table = StockMovement._meta.db_table
    value_placeholders = ", ".join(["(%s, %s)"] * len(adjustment_dates))
    params: list[object] = []
    # base
    params.extend([stock_item_id, first_date, stock_item_id])
    # adj values
    for delta_date in adjustment_dates:
        params.extend([delta_date, deltas[delta_date]])
    # movements since first_date
    params.extend([stock_item_id, first_date])

    sql = f"""
        WITH base AS (
            SELECT s.opening_qty + COALESCE((
                SELECT SUM(CASE m.direction WHEN 'in' THEN m.qty ELSE -m.qty END)
                FROM {movement_table} m
                WHERE m.stock_item_id = %s
                  AND m.deleted_at IS NULL
                  AND m.date < %s
            ), 0) AS bal
            FROM {stock_table} s
            WHERE s.id = %s
        ), adj(d, net) AS (
            VALUES {value_placeholders}
        ), days AS (
            SELECT d, SUM(net) AS net FROM (
                SELECT m.date AS d,
                       SUM(CASE m.direction WHEN 'in' THEN m.qty ELSE -m.qty END) AS net
                FROM {movement_table} m
                WHERE m.stock_item_id = %s
                  AND m.deleted_at IS NULL
                  AND m.date >= %s
                GROUP BY m.date
                UNION ALL
                SELECT d, net FROM adj
            ) combined
            GROUP BY d
        ), running AS (
            SELECT d,
                   SUM(net) OVER (ORDER BY d) + (SELECT bal FROM base) AS balance
            FROM days
        )
        SELECT d, balance
        FROM running
        WHERE balance < 0
        ORDER BY d
        LIMIT 1
    """

    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
    if row is None:
        return None
    return row[0], Decimal(row[1])


def upsert_for_transaction(
    *,
    txn,
    stock_item: StockItem,
    direction: str,
    qty: Decimal,
    actor=None,
) -> StockMovement:
    """Buat/perbarui tepat satu movement aktif untuk transaksi (I-2).

    Movement bersumber transaksi **tidak** diaudit terpisah; audit dilakukan
    oleh service transaksi.
    """
    movement = StockMovement.objects.filter(transaction=txn, stock_item=stock_item).first()
    if movement is None:
        return StockMovement.objects.create(
            stock_item=stock_item,
            date=txn.date,
            direction=direction,
            qty=qty,
            source="transaction",
            transaction=txn,
            created_by=actor if getattr(actor, "pk", None) else None,
        )
    movement.date = txn.date
    movement.direction = direction
    movement.qty = qty
    movement.source = "transaction"
    movement.save(update_fields=["date", "direction", "qty", "source", "updated_at"])
    return movement


def soft_delete_for_transaction(txn_id: int, actor=None) -> int:
    """Soft-delete semua movement aktif milik transaksi (BR-05)."""
    return StockMovement.objects.filter(transaction_id=txn_id).update(
        deleted_at=timezone.now(),
        deleted_by=actor if getattr(actor, "pk", None) else None,
        updated_at=timezone.now(),
    )


# --- Test seam konkurensi -------------------------------------------------
_after_lock_hook = None


@contextmanager
def test_after_lock(callback):
    """Pasang callback tepat setelah `SELECT ... FOR UPDATE` berhasil.

    Hanya untuk test konkurensi deterministik (§10.3). Tidak dipakai produksi.
    """
    global _after_lock_hook
    _after_lock_hook = callback
    try:
        yield
    finally:
        _after_lock_hook = None


def _run_after_lock_hook() -> None:
    if _after_lock_hook is not None:
        _after_lock_hook()
