"""Internal transfers between the four cash-source accounts."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction

from audit.service import diff, log_audit, snapshot
from core.errors import DomainError, NotFound
from core.services.locks import assert_date_editable
from core.utils.dates import today_wib
from ledger.models import Account, AccountTransfer
from ledger.services.accounts import account_balance_at
from ledger.services.opening import MONEY_MAX

TRANSFER_AUDIT_FIELDS = (
    "date",
    "from_account",
    "to_account",
    "amount",
    "notes",
    "created_by",
)


def _transfer_amount(value: object) -> Decimal:
    if isinstance(value, (bool, float)):
        raise DomainError("Nominal tidak valid.", code="number_invalid")
    try:
        amount = Decimal(str(value))
        if not amount.is_finite():
            raise InvalidOperation
        amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise DomainError("Nominal tidak valid.", code="number_invalid") from exc
    if amount <= 0 or amount > MONEY_MAX:
        raise DomainError("Nominal pindah dana harus lebih dari nol.", code="amount_invalid")
    return amount


@transaction.atomic
def create_account_transfer(
    *,
    value_date: date,
    from_code: str,
    to_code: str,
    amount: object,
    notes: str = "",
    actor=None,
    meta=None,
) -> AccountTransfer:
    amount_value = _transfer_amount(amount)
    if value_date > today_wib():
        raise DomainError("Tanggal tidak boleh melebihi hari ini.", code="date_after_today")
    if from_code == to_code:
        raise DomainError("Sumber dan tujuan harus berbeda.", code="account_transfer_same")

    accounts = {
        account.code: account
        for account in Account.objects.select_for_update().filter(
            code__in=[from_code, to_code], is_active=True
        )
    }
    source = accounts.get(from_code)
    destination = accounts.get(to_code)
    if source is None or destination is None:
        raise DomainError("Akun sumber atau tujuan tidak ditemukan.", code="account_missing")
    if value_date < source.opening_balance_date or value_date < destination.opening_balance_date:
        raise DomainError(
            "Tanggal pindah dana tidak boleh sebelum tanggal saldo awal akun.",
            code="date_before_opening",
        )
    assert_date_editable(value_date)

    available = account_balance_at(source, value_date)
    if amount_value > available:
        raise DomainError(
            "Saldo sumber tidak cukup untuk pindah dana.",
            code="account_transfer_insufficient",
            fields={"amount": "Saldo sumber tidak cukup untuk pindah dana."},
        )

    transfer = AccountTransfer.objects.create(
        date=value_date,
        from_account=source,
        to_account=destination,
        amount=amount_value,
        notes=notes.strip(),
        created_by=actor if getattr(actor, "pk", None) else None,
    )
    log_audit(
        entity="account_transfer",
        entity_id=transfer.pk,
        action="create",
        actor=actor,
        after=snapshot(transfer, TRANSFER_AUDIT_FIELDS),
        meta=meta,
    )
    return transfer


@transaction.atomic
def delete_account_transfer(*, transfer_id: int, actor=None, meta=None) -> None:
    transfer = AccountTransfer.objects.select_for_update().filter(pk=transfer_id).first()
    if transfer is None:
        raise NotFound("Pindah dana tidak ditemukan.")
    assert_date_editable(transfer.date, operation="delete")
    before = snapshot(transfer, TRANSFER_AUDIT_FIELDS)
    transfer.soft_delete(actor=actor)
    changed_before, changed_after = diff(
        before, snapshot(transfer, TRANSFER_AUDIT_FIELDS)
    )
    log_audit(
        entity="account_transfer",
        entity_id=transfer.pk,
        action="delete",
        actor=actor,
        before=changed_before,
        after=changed_after,
        meta=meta,
    )
