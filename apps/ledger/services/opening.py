"""Saldo awal kas (S-17, FR-07).

Kunci kas dipicu oleh **transaksi apa pun yang pernah ada**, termasuk yang
sudah di-soft-delete (BR-01, AC-07.7). Movement stok tidak mengunci kas.
Koreksi saldo awal (transaksi sistem) belum dibangun; modul ini hanya
mengizinkan perubahan selama kas belum terkunci.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db import transaction

from audit.service import diff, log_audit, snapshot
from core import messages
from core.errors import DomainError
from core.models import CompanyProfile
from core.utils.dates import today_wib
from ledger.models import Account, Transaction

AUDIT_FIELDS = ("opening_balance", "opening_balance_date")
MONEY_MAX = Decimal("100000000000")


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
    actor=None,
    meta=None,
) -> Account:
    """Ubah saldo awal selama belum ada transaksi; validasi tanggal AC-07.6."""
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
        account = Account.objects.select_for_update().order_by("pk").first()
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
