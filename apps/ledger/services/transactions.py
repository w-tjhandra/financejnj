"""Service transaksi (FR-08, FR-09).

Satu pintu tulis untuk `ledger.Transaction` dan movement stoknya. Urutan
eksekusi mengikat (§3.9): validasi bentuk → pre-check → atomic →
`assert_date_editable` → lock stok urut id → validasi saldo → insert →
movement → audit.

Modul ini sengaja **tidak** menangani update/delete/duplikat (T-006.4a2).
"""

from __future__ import annotations

from datetime import date as date_type
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import IntegrityError, transaction

from audit.service import log_audit, snapshot
from core import messages
from core.errors import DomainError, DuplicateSalary, StockConflict, StockInsufficient
from core.services.locks import assert_date_editable
from core.utils.dates import format_date_id, format_month_id, month_start, today_wib
from core.utils.numbers import format_qty
from ledger.models import Account, Transaction
from master.models import Category, Item
from stock import api as stock_api

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


def _validate_header(
    *,
    value_date: date_type,
    flow: str,
    category: Category,
    item: Item,
    amount: Decimal,
    account: Account,
) -> None:
    if flow not in {"income", "expense"}:
        message = messages.ITEM_FLOW_INVALID
        raise DomainError(message, code="flow_invalid", fields={"flow": message})
    if item.flow != flow:
        message = messages.ITEM_FLOW_INVALID
        raise DomainError(message, code="flow_invalid", fields={"flow": message})
    if not item.is_active:
        message = "Item tidak aktif."
        raise DomainError(message, code="item_inactive", fields={"item": message})
    if item.is_system:
        message = "Item sistem hanya bisa dipakai lewat koreksi saldo awal."
        raise DomainError(message, code="item_system", fields={"item": message})
    if not category.is_active:
        message = "Kategori tidak aktif."
        raise DomainError(message, code="category_inactive", fields={"category": message})

    if value_date > today_wib():
        message = messages.TXN_DATE_AFTER_TODAY
        raise DomainError(message, code="date_after_today", fields={"date": message})
    if value_date < account.opening_balance_date:
        message = messages.date_before_opening(account.opening_balance_date)
        raise DomainError(message, code="date_before_opening", fields={"date": message})

    if amount <= 0:
        message = messages.AMOUNT_MIN
        raise DomainError(message, code="amount_min", fields={"amount": message})
    if amount > MONEY_MAX:
        message = messages.AMOUNT_MAX
        raise DomainError(message, code="amount_max", fields={"amount": message})


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

    payment = None if payment_method in (None, "") else str(payment_method)
    if payment is not None and payment not in PAYMENT_METHODS:
        message = "Metode pembayaran tidak valid."
        raise DomainError(
            message, code="payment_method_invalid", fields={"payment_method": message}
        )
    notes = (notes or "").strip()
    if len(notes) > 500:
        message = "Keterangan maksimum 500 karakter."
        raise DomainError(message, code="notes_max", fields={"notes": message})

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
                    message = f"Gaji {category.code} {format_month_id(period)} sudah tercatat."
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
