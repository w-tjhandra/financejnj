"""Helpers for the four supported cash sources."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Case, F, Sum, When

from ledger.models import ACCOUNT_CHOICES, Account, AccountTransfer, Transaction

ZERO = Decimal("0")


@transaction.atomic
def ensure_default_accounts(
    *,
    opening_balance_date: date,
    opening_balances: dict[str, Decimal] | None = None,
) -> list[Account]:
    """Create missing cash-source accounts, preserving an existing Tunai account."""
    balances = opening_balances or {}
    accounts = []
    legacy_cash = Account.objects.filter(code__isnull=True).order_by("pk").first()
    for code, name in ACCOUNT_CHOICES:
        account = Account.objects.filter(code=code).first()
        if account is None and code == "cash" and legacy_cash is not None:
            account = legacy_cash
            account.code = "cash"
            account.name = name
            account.type = "cash"
            account.save(update_fields=["code", "name", "type", "updated_at"])
        if account is None:
            account = Account.objects.create(
                code=code,
                name=name,
                type="cash" if code == "cash" else "bank",
                currency="IDR",
                opening_balance=balances.get(code, ZERO),
                opening_balance_date=opening_balance_date,
            )
        accounts.append(account)
    return accounts


def account_balance_at(account: Account, as_of: date) -> Decimal:
    """Return one account's opening balance plus its transactions and transfers."""
    if as_of < account.opening_balance_date:
        return ZERO
    transaction_delta = (
        Transaction.objects.filter(
            account=account,
            date__gte=account.opening_balance_date,
            date__lte=as_of,
        )
        .aggregate(
            total=Sum(
                Case(
                    When(flow="income", then=F("amount")),
                    default=-F("amount"),
                )
            )
        )["total"]
        or ZERO
    )
    transfer_in = (
        AccountTransfer.objects.filter(
            to_account=account,
            date__gte=account.opening_balance_date,
            date__lte=as_of,
        ).aggregate(total=Sum("amount"))["total"]
        or ZERO
    )
    transfer_out = (
        AccountTransfer.objects.filter(
            from_account=account,
            date__gte=account.opening_balance_date,
            date__lte=as_of,
        ).aggregate(total=Sum("amount"))["total"]
        or ZERO
    )
    return account.opening_balance + transaction_delta + transfer_in - transfer_out


def account_balances_at(as_of: date) -> list[dict]:
    account_order = {code: index for index, (code, _name) in enumerate(ACCOUNT_CHOICES)}
    return [
        {
            "code": account.code,
            "name": account.name,
            "balance": account_balance_at(account, as_of),
        }
        for account in sorted(
            Account.objects.filter(is_active=True),
            key=lambda row: account_order.get(row.code, len(account_order)),
        )
    ]
