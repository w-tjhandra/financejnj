"""Saldo awal kas (S-17, FR-07).

Kunci kas dipicu oleh **transaksi apa pun yang pernah ada**, termasuk yang
sudah di-soft-delete (BR-01, AC-07.7). Movement stok tidak mengunci kas.
Koreksi saldo awal (transaksi sistem) belum dibangun; modul ini hanya
mengizinkan perubahan selama kas belum terkunci.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction

from audit.service import diff, log_audit, snapshot
from core import messages
from core.errors import DomainError
from core.models import CompanyProfile
from core.services.locks import assert_date_editable
from core.utils.dates import today_wib
from ledger.models import ACCOUNT_CHOICES, Account, Transaction
from master.models import Category, Item

AUDIT_FIELDS = ("opening_balance", "opening_balance_date")
CORRECTION_AUDIT_FIELDS = (
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
    "created_by",
)
MONEY_MAX = Decimal("100000000000")
MONEY_QUANTUM = Decimal("0.01")
REASON_MIN = 10
REASON_MAX = 300


def cash_is_locked() -> bool:
    """Permanen setelah baris transaksi pertama, termasuk yang dihapus."""
    return Transaction.all_objects.exists()


def cash_locked_since() -> date | None:
    return Transaction.all_objects.order_by("date", "id").values_list("date", flat=True).first()


def current_account() -> Account | None:
    return Account.current() or Account.objects.order_by("pk").first()


def set_opening_balance(
    *,
    amount: object,
    value_date: date,
    account_code: str | None = None,
    actor=None,
    meta=None,
) -> Account:
    """Ubah satu saldo awal selama belum ada transaksi."""
    try:
        opening_balance = amount if isinstance(amount, Decimal) else Decimal(str(amount))
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise DomainError(
            messages.NUMBER_INVALID.format(field="Saldo awal"), code="number_invalid"
        ) from exc
    if opening_balance < 0:
        raise DomainError("Saldo awal tidak boleh negatif.", code="amount_negative")
    if opening_balance > MONEY_MAX:
        raise DomainError("Saldo awal maksimum Rp 100.000.000.000.", code="amount_max")

    if value_date > today_wib():
        raise DomainError(
            messages.DATE_AFTER_TODAY,
            code="date_after_today",
            fields={"opening_balance_date": messages.DATE_AFTER_TODAY},
        )
    profile = CompanyProfile.get_solo()
    if profile is not None and profile.business_start_date is not None:
        if value_date < profile.business_start_date:
            message = messages.date_before_business_start(profile.business_start_date)
            raise DomainError(
                message,
                code="date_before_start",
                fields={"opening_balance_date": message},
            )

    with transaction.atomic():
        if account_code:
            account = Account.objects.select_for_update().filter(code=account_code).first()
        else:
            account = (
                Account.objects.select_for_update().filter(code="cash").first()
                or Account.objects.select_for_update().order_by("pk").first()
            )
        if account is None:
            raise DomainError("Akun kas belum dibuat.", code="account_missing")
        if Transaction.all_objects.exists():
            raise DomainError(
                messages.OPENING_BALANCE_LOCKED,
                code="opening_locked",
                fields={"opening_balance": messages.OPENING_BALANCE_LOCKED},
            )

        before = snapshot(account, AUDIT_FIELDS)
        account.opening_balance = opening_balance
        account.opening_balance_date = value_date
        account.save(update_fields=[*AUDIT_FIELDS, "updated_at"])

        changed_before, changed_after = diff(before, snapshot(account, AUDIT_FIELDS))
        if changed_before:
            log_audit(
                entity="account",
                entity_id=account.pk,
                action="update",
                actor=actor,
                before=changed_before,
                after=changed_after,
                meta=meta,
            )
        return account


def set_opening_balances(
    *,
    balances: dict[str, object],
    value_date: date,
    actor=None,
    meta=None,
) -> list[Account]:
    """Set all four source balances together before the first transaction."""
    if set(balances) != {code for code, _label in ACCOUNT_CHOICES}:
        raise DomainError("Saldo untuk keempat sumber wajib diisi.", code="accounts_incomplete")
    saved = []
    with transaction.atomic():
        if Transaction.all_objects.exists():
            raise DomainError(
                messages.OPENING_BALANCE_LOCKED,
                code="opening_locked",
                fields={"opening_balance": messages.OPENING_BALANCE_LOCKED},
            )
        for code, _label in ACCOUNT_CHOICES:
            saved.append(
                set_opening_balance(
                    amount=balances[code],
                    value_date=value_date,
                    account_code=code,
                    actor=actor,
                    meta=meta,
                )
            )
    return saved


def _correction_delta(value: object) -> Decimal:
    if isinstance(value, Decimal):
        delta = value
    elif isinstance(value, float):
        raise DomainError(messages.NUMBER_INVALID.format(field="Nominal"), code="number_invalid")
    else:
        try:
            delta = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise DomainError(
                messages.NUMBER_INVALID.format(field="Nominal"), code="number_invalid"
            ) from exc
    delta = delta.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    if delta == 0:
        raise DomainError("Nominal koreksi tidak boleh nol.", code="amount_zero")
    if abs(delta) > MONEY_MAX:
        raise DomainError(
            messages.AMOUNT_MAX,
            code="amount_max",
            fields={"amount": messages.AMOUNT_MAX},
        )
    return delta


def record_opening_correction(
    *,
    delta: object,
    reason: str,
    account_code: str | None = None,
    actor=None,
    meta=None,
) -> Transaction:
    """Koreksi saldo awal sebagai transaksi sistem non-operasional (FR-07).

    Hanya boleh setelah kas terkunci (ada transaksi), tanggal mengikuti
    `opening_balance_date`, dan `accounts.opening_balance` tidak diubah.
    """
    amount_delta = _correction_delta(delta)
    reason = (reason or "").strip()
    if len(reason) < REASON_MIN or len(reason) > REASON_MAX:
        raise DomainError(
            messages.REASON_MIN_10,
            code="reason_min",
            fields={"reason": messages.REASON_MIN_10},
        )

    item = Item.objects.filter(code="opening_correction", is_system=True).first()
    category = Category.objects.filter(code="UMUM").first()
    if item is None or category is None:
        raise DomainError("Master koreksi saldo awal belum tersedia.", code="master_missing")

    with transaction.atomic():
        if account_code:
            account = Account.objects.select_for_update().filter(code=account_code).first()
        else:
            account = (
                Account.objects.select_for_update().filter(code="cash").first()
                or Account.objects.select_for_update().order_by("pk").first()
            )
        if account is None:
            raise DomainError("Akun kas belum dibuat.", code="account_missing")
        if not cash_is_locked():
            raise DomainError(
                "Saldo awal belum terkunci; ubah saldo awal secara langsung.",
                code="opening_not_locked",
            )
        assert_date_editable(account.opening_balance_date)

        flow = "income" if amount_delta > 0 else "expense"
        txn = Transaction.objects.create(
            date=account.opening_balance_date,
            flow=flow,
            category=category,
            item=item,
            account=account,
            currency=account.currency,
            amount=abs(amount_delta),
            qty=None,
            unit=None,
            payment_method=None,
            notes=f"[Koreksi saldo awal] {reason}",
            period_month=None,
            is_opening_correction=True,
            created_by=actor if getattr(actor, "pk", None) else None,
        )
        log_audit(
            entity="transaction",
            entity_id=txn.pk,
            action="create",
            actor=actor,
            after=snapshot(txn, CORRECTION_AUDIT_FIELDS),
            meta=meta,
        )
        return txn
