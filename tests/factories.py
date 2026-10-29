"""Factory minimal untuk test fondasi (belum memakai service)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from ledger.models import Account, Attachment, Transaction
from master.models import Category, Item, StockItem
from stock.models import StockMovement


def make_category(code="UMUM", name=None, **kwargs):
    category, _ = Category.objects.get_or_create(
        code=code, defaults={"name": name or code.title(), **kwargs}
    )
    return category


def make_stock_item(code="egg", name="Telur", unit="kg", opening_qty=Decimal("0"), **kwargs):
    stock_item, _ = StockItem.objects.get_or_create(
        code=code,
        defaults={"name": name, "unit": unit, "opening_qty": opening_qty, **kwargs},
    )
    return stock_item


def make_item(name="Item Uji", flow="expense", **kwargs):
    return Item.objects.create(name=name, flow=flow, **kwargs)


def make_account(**kwargs):
    kwargs.setdefault("opening_balance_date", date(2026, 9, 1))
    return Account.objects.create(**kwargs)


def make_transaction(
    *,
    item,
    category=None,
    account=None,
    value_date=date(2026, 10, 1),
    amount=Decimal("1000.00"),
    **kwargs,
):
    category = category or item.default_category or make_category()
    account = account or make_account()
    kwargs.setdefault("flow", item.flow)
    return Transaction.objects.create(
        date=value_date,
        category=category,
        item=item,
        account=account,
        amount=amount,
        **kwargs,
    )


def make_movement(
    *,
    stock_item,
    value_date=date(2026, 10, 1),
    direction="in",
    qty=Decimal("1.000"),
    source="manual",
    transaction=None,
    reason=None,
    **kwargs,
):
    return StockMovement.objects.create(
        stock_item=stock_item,
        date=value_date,
        direction=direction,
        qty=qty,
        source=source,
        transaction=transaction,
        reason=reason,
        **kwargs,
    )


def make_attachment(transaction, **kwargs):
    kwargs.setdefault("file", "attachments/2026/10/uji.pdf")
    kwargs.setdefault("original_name", "uji.pdf")
    kwargs.setdefault("mime_type", "application/pdf")
    kwargs.setdefault("size_bytes", 1024)
    return Attachment.objects.create(transaction=transaction, **kwargs)
