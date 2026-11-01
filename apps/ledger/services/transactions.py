"""Service transaksi (FR-08, FR-09, FR-10, FR-11, FR-12).

Satu pintu tulis untuk `ledger.Transaction` dan movement stoknya. Urutan
eksekusi mengikat (§3.9): validasi bentuk → pre-check → atomic →
`assert_date_editable` → lock transaksi (bila ada) → lock stok urut id →
validasi saldo → tulis → audit.

Update memakai delta bersih (BR-04): movement yang sama diperbarui di tempat,
perubahan jenis stok menghapus movement lama dan membuat yang baru. Delete
adalah soft delete transaksi + movement, tanpa movement pembalik (BR-05).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date as date_type
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.utils import timezone

from audit.service import diff, log_audit, snapshot
from core import messages
from core.errors import DomainError, DuplicateSalary, NotFound, StockConflict, StockInsufficient
from core.services.locks import assert_date_editable
from core.utils.dates import (
    format_date_id,
    format_date_short,
    format_month_id,
    month_start,
    today_wib,
)
from core.utils.numbers import format_qty
from ledger.models import TRANSFER_BANK_VALUES, Account, Transaction
from master.models import Category, Item
from stock import api as stock_api
from stock.models import StockMovement

MONEY_MAX = Decimal("100000000000")
QTY_MAX = Decimal("1000000")
PAYMENT_METHODS = {"cash", "transfer"}
SALARY_CATEGORIES = {"LAYER", "DOC", "UMUM"}
MONEY_QUANTUM = Decimal("0.01")
QTY_QUANTUM = Decimal("0.001")
AUDIT_FIELDS = (
    "date",
    "flow",
    "category",
    "item",
    "account",
    "currency",
    "amount",
    "qty",
    "unit",
    "payment_method",
    "transfer_bank",
    "notes",
    "period_month",
    "is_opening_correction",
    "idempotency_key",
    "created_by",
)


def _coerce_date(value: object, *, field: str) -> date_type:
    if isinstance(value, date_type):
        return value
    if isinstance(value, str):
        try:
            return date_type.fromisoformat(value)
        except ValueError:
            pass
    message = messages.DATE_INVALID
    raise DomainError(message, code="date_invalid", fields={field: message})


def _coerce_decimal(value: object, *, field: str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool) or isinstance(value, float):
        message = messages.NUMBER_INVALID.format(field=field)
        raise DomainError(message, code="number_invalid", fields={field: message})
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        message = messages.NUMBER_INVALID.format(field=field)
        raise DomainError(message, code="number_invalid", fields={field: message}) from exc


def _resolve_account() -> Account:
    account = Account.current() or Account.objects.order_by("pk").first()
    if account is None:
        raise DomainError("Akun kas belum dibuat.", code="account_missing")
    return account


def _validate_date_bounds(value_date: date_type, account: Account) -> None:
    """Tanggal transaksi: tidak melewati hari ini dan tidak sebelum saldo awal."""
    if value_date > today_wib():
        message = messages.TXN_DATE_AFTER_TODAY
        raise DomainError(message, code="date_after_today", fields={"date": message})
    if value_date < account.opening_balance_date:
        message = messages.date_before_opening(account.opening_balance_date)
        raise DomainError(message, code="date_before_opening", fields={"date": message})


def _validate_header(
    *,
    value_date: date_type,
    flow: str,
    category: Category,
    item: Item,
    amount: Decimal,
    account: Account,
    existing_item_id: int | None = None,
    existing_category_id: int | None = None,
) -> None:
    """Validasi header transaksi.

    ``existing_*_id`` melonggarkan cek aktif hanya untuk master yang **sudah**
    dipakai baris yang sedang diedit (E-14: item nonaktif tetap boleh dipertahankan).
    """
    if flow not in {"income", "expense"}:
        message = messages.ITEM_FLOW_INVALID
        raise DomainError(message, code="flow_invalid", fields={"flow": message})
    if item.flow != flow:
        message = messages.ITEM_FLOW_INVALID
        raise DomainError(message, code="flow_invalid", fields={"flow": message})
    if not item.is_active and item.pk != existing_item_id:
        message = "Item tidak aktif."
        raise DomainError(message, code="item_inactive", fields={"item": message})
    if item.is_system:
        message = "Item sistem hanya bisa dipakai lewat koreksi saldo awal."
        raise DomainError(message, code="item_system", fields={"item": message})
    if not category.is_active and category.pk != existing_category_id:
        message = "Kategori tidak aktif."
        raise DomainError(message, code="category_inactive", fields={"category": message})

    _validate_date_bounds(value_date, account)

    if amount <= 0:
        message = messages.AMOUNT_MIN
        raise DomainError(message, code="amount_min", fields={"amount": message})
    if amount > MONEY_MAX:
        message = messages.AMOUNT_MAX
        raise DomainError(message, code="amount_max", fields={"amount": message})


def _normalize_payment(payment_method: object) -> str | None:
    payment = None if payment_method in (None, "") else str(payment_method)
    if payment is not None and payment not in PAYMENT_METHODS:
        message = "Metode pembayaran tidak valid."
        raise DomainError(
            message, code="payment_method_invalid", fields={"payment_method": message}
        )
    return payment


def _normalize_transfer_bank(payment_method: str | None, transfer_bank: object) -> str | None:
    bank = None if transfer_bank in (None, "") else str(transfer_bank)
    if payment_method == "transfer":
        if bank not in TRANSFER_BANK_VALUES:
            message = "Pilih bank untuk transaksi transfer."
            raise DomainError(
                message,
                code="transfer_bank_required",
                fields={"transfer_bank": message},
            )
        return bank
    if bank is not None:
        message = "Bank hanya dapat diisi untuk transaksi transfer."
        raise DomainError(
            message,
            code="transfer_bank_payment_mismatch",
            fields={"transfer_bank": message},
        )
    return None


def _normalize_notes(notes: object) -> str:
    text = (notes or "").strip()
    if len(text) > 500:
        message = "Keterangan maksimum 500 karakter."
        raise DomainError(message, code="notes_max", fields={"notes": message})
    return text


def _validate_qty(
    *,
    item: Item,
    qty: object,
    unit: object,
) -> tuple[Decimal | None, str | None]:
    """D3: qty wajib untuk ber-stok; opsional informasional untuk non-stok."""
    if item.stock_item_id is not None:
        if qty in (None, ""):
            message = messages.QTY_REQUIRED
            raise DomainError(message, code="qty_required", fields={"qty": message})
        quantity = _coerce_decimal(qty, field="Qty").quantize(QTY_QUANTUM, rounding=ROUND_HALF_UP)
        if quantity <= 0:
            message = messages.QTY_MIN
            raise DomainError(message, code="qty_min", fields={"qty": message})
        if quantity > QTY_MAX:
            message = messages.QTY_MAX
            raise DomainError(message, code="qty_max", fields={"qty": message})
        return quantity, item.stock_item.unit

    if qty in (None, ""):
        # AC-08.10: qty kosong juga berarti satuan kosong (informasional).
        return None, None

    quantity = _coerce_decimal(qty, field="Qty").quantize(QTY_QUANTUM, rounding=ROUND_HALF_UP)
    if quantity <= 0:
        message = messages.QTY_MIN
        raise DomainError(message, code="qty_min", fields={"qty": message})
    if quantity > QTY_MAX:
        message = messages.QTY_MAX
        raise DomainError(message, code="qty_max", fields={"qty": message})

    unit_text = str(unit or item.unit or "").strip()
    if not unit_text:
        message = "Satuan wajib diisi bila qty diisi."
        raise DomainError(message, code="unit_required", fields={"unit": message})
    if len(unit_text) > 10:
        message = "Satuan maksimum 10 karakter."
        raise DomainError(message, code="unit_max", fields={"unit": message})
    return quantity, unit_text


def _validate_monthly(
    *,
    item: Item,
    category: Category,
    value_date: date_type,
    period_month: object,
    opening_balance_date: date_type,
) -> date_type | None:
    if item.frequency != "monthly":
        return None

    if period_month in (None, ""):
        message = "Bulan gaji wajib dipilih."
        raise DomainError(message, code="period_month_required", fields={"period_month": message})
    period = _coerce_date(period_month, field="period_month")
    if period.day != 1:
        message = "Bulan gaji harus tanggal 1."
        raise DomainError(message, code="period_month_first", fields={"period_month": message})

    period = month_start(period)
    if period > month_start(value_date):
        message = "Bulan gaji tidak boleh setelah bulan tanggal transaksi."
        raise DomainError(message, code="period_month_after_date", fields={"period_month": message})
    if period < month_start(opening_balance_date):
        message = "Bulan gaji tidak boleh sebelum tanggal saldo awal."
        raise DomainError(
            message, code="period_month_before_opening", fields={"period_month": message}
        )
    if category.code not in SALARY_CATEGORIES:
        message = messages.SALARY_CATEGORY
        raise DomainError(message, code="salary_category", fields={"category": message})
    return period


def _stock_short_message(
    *,
    stock_item,
    value_date: date_type,
    available: Decimal,
    requested: Decimal,
) -> str:
    return messages.STOCK_INSUFFICIENT_DETAIL.format(
        name=stock_item.name,
        date=format_date_id(value_date),
        qty=format_qty(available),
        unit=stock_item.unit,
        requested=format_qty(requested),
    )


def _stock_conflict_message(*, stock_item, available: Decimal, requested: Decimal) -> str:
    return messages.STOCK_CONFLICT.format(
        name=stock_item.name,
        qty=format_qty(available),
        unit=stock_item.unit,
        requested=format_qty(requested),
    )


def _find_salary(
    *, item: Item, category: Category, account: Account, period_month: date_type
) -> Transaction | None:
    return Transaction.objects.filter(
        item=item,
        category=category,
        account=account,
        period_month=period_month,
    ).first()


def _salary_message(category: Category, period_month: date_type) -> str:
    return f"Gaji {category.code} {format_month_id(period_month)} sudah tercatat."


def _signed_movement_qty(movement: StockMovement) -> Decimal:
    """Pengaruh movement terhadap stok: masuk positif, keluar negatif."""
    return movement.qty if movement.direction == "in" else -movement.qty


def _movement_audit_entry(movement: StockMovement) -> dict:
    """Ringkasan movement untuk ``extra`` audit (bukan snapshot penuh)."""
    return {
        "stock_item": movement.stock_item_id,
        "date": movement.date.isoformat(),
        "direction": movement.direction,
        "qty": str(movement.qty),
    }


def _stock_negative_message(stock_item, when: date_type, balance: Decimal) -> str:
    return messages.STOCK_WILL_NEGATIVE.format(
        name=stock_item.name,
        date=format_date_short(when),
        balance=format_qty(balance),
        unit=stock_item.unit,
    )


def create_transaction(
    *,
    date,
    flow: str,
    category: Category,
    item: Item,
    amount,
    qty=None,
    unit=None,
    payment_method: str | None = None,
    transfer_bank: str | None = None,
    notes: str = "",
    period_month=None,
    idempotency_key=None,
    actor=None,
    meta=None,
) -> Transaction:
    """Buat transaksi + movement stok dalam satu transaksi DB (AC-08.x)."""
    if idempotency_key and (
        existing := Transaction.all_objects.filter(idempotency_key=idempotency_key).first()
    ):
        return existing

    value_date = _coerce_date(date, field="date")
    money = _coerce_decimal(amount, field="Nominal").quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    account = _resolve_account()
    _validate_header(
        value_date=value_date,
        flow=flow,
        category=category,
        item=item,
        amount=money,
        account=account,
    )

    quantity, unit_value = _validate_qty(item=item, qty=qty, unit=unit)
    period = _validate_monthly(
        item=item,
        category=category,
        value_date=value_date,
        period_month=period_month,
        opening_balance_date=account.opening_balance_date,
    )

    payment = _normalize_payment(payment_method)
    bank = _normalize_transfer_bank(payment, transfer_bank)
    notes = _normalize_notes(notes)

    direction = None
    signed_qty = None
    precheck_failed = False
    if item.stock_item_id is not None:
        direction = stock_api.direction_for(flow)
        signed_qty = quantity if direction == "in" else -quantity
        if direction == "out":
            available = stock_api.peek_available(item.stock_item_id, value_date)
            precheck_failed = available < quantity

    with transaction.atomic():
        assert_date_editable(value_date)

        if item.stock_item_id is not None:
            locked = stock_api.lock_items([item.stock_item_id])
            stock_item = locked[item.stock_item_id]
            negative = stock_api.assert_balance_after_change(
                stock_item_id=stock_item.pk,
                date=value_date,
                delta_by_date={value_date: signed_qty},
            )
            if negative is not None:
                if precheck_failed:
                    message = _stock_short_message(
                        stock_item=stock_item,
                        value_date=negative[0],
                        available=stock_api.peek_available(stock_item.pk, value_date),
                        requested=quantity,
                    )
                    raise StockInsufficient(message, fields={"qty": message})
                available = stock_api.peek_available(stock_item.pk, value_date)
                message = _stock_conflict_message(
                    stock_item=stock_item,
                    available=available,
                    requested=quantity,
                )
                raise StockConflict(message, fields={"qty": message})
        else:
            stock_item = None

        try:
            with transaction.atomic():
                txn = Transaction.objects.create(
                    date=value_date,
                    flow=flow,
                    category=category,
                    item=item,
                    account=account,
                    currency=account.currency,
                    amount=money,
                    qty=quantity,
                    unit=unit_value,
                    payment_method=payment,
                    transfer_bank=bank,
                    notes=notes,
                    period_month=period,
                    created_by=actor if getattr(actor, "pk", None) else None,
                    idempotency_key=idempotency_key,
                )
        except IntegrityError as exc:
            if idempotency_key:
                existing = Transaction.all_objects.filter(idempotency_key=idempotency_key).first()
                if existing is not None:
                    return existing
            if period is not None:
                existing = _find_salary(
                    item=item, category=category, account=account, period_month=period
                )
                if existing is not None:
                    message = _salary_message(category, period)
                    raise DuplicateSalary(message, existing_id=existing.pk) from exc
            message = "Transaksi gagal disimpan."
            raise DomainError(message, code="transaction_conflict") from exc

        if stock_item is not None:
            stock_api.upsert_for_transaction(
                txn=txn,
                stock_item=stock_item,
                direction=direction,
                qty=quantity,
                actor=actor,
            )

        log_audit(
            entity="transaction",
            entity_id=txn.pk,
            action="create",
            actor=actor,
            after=snapshot(txn, AUDIT_FIELDS),
            meta=meta,
        )
        return txn


def update_transaction(
    *,
    transaction_id: int,
    date,
    flow: str,
    category: Category,
    item: Item,
    amount,
    qty=None,
    unit=None,
    payment_method: str | None = None,
    transfer_bank: str | None = None,
    notes: str = "",
    period_month=None,
    actor=None,
    meta=None,
) -> Transaction:
    """Ubah transaksi + penyesuaian movement sebagai delta (FR-10, BR-04).

    Movement dengan jenis stok sama diperbarui **di tempat**; perubahan jenis
    stok/non-stok menghapus movement lama dan membuat yang baru. Saldo berjalan
    divalidasi sekali memakai delta bersih dari tanggal terdampak terkecil,
    bukan dua validasi terpisah.
    """
    value_date = _coerce_date(date, field="date")
    money = _coerce_decimal(amount, field="Nominal").quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)

    with transaction.atomic():
        txn = Transaction.objects.select_for_update().filter(pk=transaction_id).first()
        if txn is None:
            raise NotFound(messages.TRANSACTION_NOT_FOUND)
        if txn.is_opening_correction:
            message = "Transaksi koreksi saldo awal tidak bisa diedit."
            raise DomainError(message, code="opening_correction_locked", fields={"date": message})

        account = txn.account
        old_date = txn.date

        _validate_header(
            value_date=value_date,
            flow=flow,
            category=category,
            item=item,
            amount=money,
            account=account,
            existing_item_id=txn.item_id,
            existing_category_id=txn.category_id,
        )
        # E-07: kedua tanggal harus bisa diedit, bukan hanya tanggal baru.
        _validate_date_bounds(old_date, account)
        assert_date_editable(old_date, operation="update")
        assert_date_editable(value_date, operation="update")

        quantity, unit_value = _validate_qty(item=item, qty=qty, unit=unit)
        period = _validate_monthly(
            item=item,
            category=category,
            value_date=value_date,
            period_month=period_month,
            opening_balance_date=account.opening_balance_date,
        )
        payment = _normalize_payment(payment_method)
        bank = _normalize_transfer_bank(payment, transfer_bank)
        notes = _normalize_notes(notes)

        new_stock_item = item.stock_item if item.stock_item_id is not None else None
        direction = stock_api.direction_for(flow) if new_stock_item is not None else None
        signed_qty = None
        if new_stock_item is not None:
            signed_qty = quantity if direction == "in" else -quantity

        old_movements = sorted(
            StockMovement.objects.filter(transaction_id=txn.pk), key=lambda row: row.pk
        )

        # Delta bersih: buang pengaruh lama, tambahkan pengaruh baru.
        deltas: dict[int, dict[date_type, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
        for movement in old_movements:
            deltas[movement.stock_item_id][movement.date] -= _signed_movement_qty(movement)
        if new_stock_item is not None and signed_qty is not None:
            deltas[new_stock_item.pk][value_date] += signed_qty
        touched = {
            stock_item_id: dict(delta_by_date)
            for stock_item_id, delta_by_date in deltas.items()
            if any(value != 0 for value in delta_by_date.values())
        }

        locked = stock_api.lock_items(touched) if touched else {}
        first_touched = min(
            [value_date, *(movement.date for movement in old_movements)],
        )
        for stock_item_id, delta_by_date in touched.items():
            negative = stock_api.assert_balance_after_change(
                stock_item_id=stock_item_id,
                date=first_touched,
                delta_by_date=delta_by_date,
            )
            if negative is not None:
                when, balance = negative
                message = _stock_negative_message(locked[stock_item_id], when, balance)
                raise StockConflict(message, fields={"qty": message})

        if period is not None:
            clash = (
                Transaction.objects.filter(
                    item=item,
                    category=category,
                    account=account,
                    period_month=period,
                )
                .exclude(pk=txn.pk)
                .first()
            )
            if clash is not None:
                raise DuplicateSalary(_salary_message(category, period), existing_id=clash.pk)

        before = snapshot(txn, AUDIT_FIELDS)
        stock_before = [_movement_audit_entry(movement) for movement in old_movements]

        txn.date = value_date
        txn.flow = flow
        txn.category = category
        txn.item = item
        txn.account = account
        txn.currency = account.currency
        txn.amount = money
        txn.qty = quantity
        txn.unit = unit_value
        txn.payment_method = payment
        txn.transfer_bank = bank
        txn.notes = notes
        txn.period_month = period
        txn.updated_by = actor if getattr(actor, "pk", None) else None

        try:
            with transaction.atomic():
                txn.save(
                    update_fields=[
                        "date",
                        "flow",
                        "category",
                        "item",
                        "account",
                        "currency",
                        "amount",
                        "qty",
                        "unit",
                        "payment_method",
                        "transfer_bank",
                        "notes",
                        "period_month",
                        "updated_by",
                        "updated_at",
                    ]
                )
        except IntegrityError as exc:
            if period is not None:
                clash = (
                    Transaction.objects.filter(
                        item=item,
                        category=category,
                        account=account,
                        period_month=period,
                    )
                    .exclude(pk=txn.pk)
                    .first()
                )
                if clash is not None:
                    raise DuplicateSalary(
                        _salary_message(category, period), existing_id=clash.pk
                    ) from exc
            message = "Transaksi gagal disimpan."
            raise DomainError(message, code="transaction_conflict") from exc

        same_stock = (
            new_stock_item is not None
            and len(old_movements) == 1
            and old_movements[0].stock_item_id == new_stock_item.pk
        )
        if new_stock_item is None:
            stock_api.soft_delete_for_transaction(txn.pk, actor)
        elif same_stock:
            stock_api.upsert_for_transaction(
                txn=txn,
                stock_item=new_stock_item,
                direction=direction,
                qty=quantity,
                actor=actor,
            )
        else:
            stock_api.soft_delete_for_transaction(txn.pk, actor)
            stock_api.upsert_for_transaction(
                txn=txn,
                stock_item=new_stock_item,
                direction=direction,
                qty=quantity,
                actor=actor,
            )

        stock_after = [
            _movement_audit_entry(movement)
            for movement in sorted(
                StockMovement.objects.filter(transaction_id=txn.pk), key=lambda row: row.pk
            )
        ]
        changed_before, changed_after = diff(before, snapshot(txn, AUDIT_FIELDS))
        extra = None
        if stock_before != stock_after:
            extra = {"stock": {"before": stock_before, "after": stock_after}}

        log_audit(
            entity="transaction",
            entity_id=txn.pk,
            action="update",
            actor=actor,
            before=changed_before,
            after=changed_after,
            extra=extra,
            meta=meta,
        )
        return txn


def delete_transaction(*, transaction_id: int, actor=None, reason: str = "", meta=None) -> None:
    """Soft delete transaksi + semua movement aktifnya (FR-11, BR-05).

    Tanpa movement pembalik: pengaruh stok hilang karena semua perhitungan
    mengabaikan baris terhapus. Saldo berjalan divalidasi ulang (I-1): delete
    yang membuat stok minus ditolak. Koreksi saldo awal tidak bisa dihapus
    (K-03). Idempoten — pemanggilan kedua tidak menulis audit baru. Lampiran
    tidak disentuh (baris maupun berkas di disk).
    """
    with transaction.atomic():
        txn = Transaction.all_objects.select_for_update().filter(pk=transaction_id).first()
        if txn is None:
            raise NotFound(messages.TRANSACTION_NOT_FOUND)
        if txn.deleted_at is not None:
            return
        if txn.is_opening_correction:
            message = (
                "Transaksi koreksi saldo awal tidak bisa dihapus. "
                "Buat koreksi balik lewat Saldo Awal."
            )
            raise DomainError(message, code="opening_correction_locked")

        assert_date_editable(txn.date, operation="delete")

        movements = list(StockMovement.objects.filter(transaction_id=txn.pk))
        deltas: dict[int, dict[date_type, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
        for movement in movements:
            deltas[movement.stock_item_id][movement.date] -= _signed_movement_qty(movement)
        touched = {
            stock_item_id: dict(delta_by_date)
            for stock_item_id, delta_by_date in deltas.items()
            if any(value != 0 for value in delta_by_date.values())
        }

        if touched:
            locked = stock_api.lock_items(touched)
            first_touched = min(movement.date for movement in movements)
            for stock_item_id, delta_by_date in touched.items():
                negative = stock_api.assert_balance_after_change(
                    stock_item_id=stock_item_id,
                    date=first_touched,
                    delta_by_date=delta_by_date,
                )
                if negative is not None:
                    when, balance = negative
                    message = _stock_negative_message(locked[stock_item_id], when, balance)
                    raise StockConflict(message, fields={"qty": message})

        before = snapshot(txn, AUDIT_FIELDS)
        user = actor if getattr(actor, "pk", None) else None
        deleted_movements = stock_api.soft_delete_for_transaction(txn.pk, actor)
        txn.deleted_at = timezone.now()
        txn.deleted_by = user
        txn.save(update_fields=["deleted_at", "deleted_by"])

        extra: dict[str, object] = {"movements": deleted_movements}
        note = (reason or "").strip()
        if note:
            extra["reason"] = note[:300]

        log_audit(
            entity="transaction",
            entity_id=txn.pk,
            action="delete",
            actor=actor,
            before=before,
            extra=extra,
            meta=meta,
        )


def duplicate_prefill(transaction_id: int) -> dict:
    """Nilai awal form tambah dari transaksi yang ada (FR-12, BR-08).

    Tidak menulis DB. Tanggal = hari ini WIB; bulan gaji dihitung ulang dari
    bulan tanggal baru. Lampiran, audit, dan jejak pembuatan tidak disalin.
    """
    txn = Transaction.objects.filter(pk=transaction_id).first()
    if txn is None:
        raise NotFound(messages.TRANSACTION_NOT_FOUND)

    value_date = today_wib()
    period = month_start(value_date) if txn.item.frequency == "monthly" else None
    return {
        "date": value_date,
        "flow": txn.flow,
        "category": txn.category,
        "item": txn.item,
        "amount": txn.amount,
        "qty": txn.qty,
        "unit": txn.unit,
        "payment_method": txn.payment_method,
        "transfer_bank": txn.transfer_bank,
        "notes": txn.notes,
        "period_month": period,
    }
