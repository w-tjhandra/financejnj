"""Soft delete: manager default menyembunyikan, all_objects tetap melihat."""

from datetime import date

import pytest

from ledger.models import Attachment, Transaction
from stock.models import StockMovement
from tests.factories import (
    make_attachment,
    make_item,
    make_movement,
    make_stock_item,
    make_transaction,
)


@pytest.mark.django_db
def test_transaction_soft_delete_dan_restore():
    txn = make_transaction(item=make_item())
    pk = txn.pk

    txn.soft_delete()

    assert Transaction.objects.filter(pk=pk).exists() is False
    assert Transaction.all_objects.filter(pk=pk).exists() is True
    assert Transaction.all_objects.get(pk=pk).deleted_at is not None

    txn.restore()

    assert Transaction.objects.filter(pk=pk).exists() is True
    assert Transaction.all_objects.get(pk=pk).deleted_at is None


@pytest.mark.django_db
def test_stock_movement_soft_delete_dan_relasi_transaksi_tetap_resolve():
    stock = make_stock_item()
    item = make_item(stock_item=stock, unit="kg")
    txn = make_transaction(item=item)
    movement = make_movement(
        stock_item=stock,
        source="transaction",
        transaction=txn,
        direction="in",
    )
    pk = movement.pk

    movement.soft_delete()

    assert StockMovement.objects.filter(pk=pk).exists() is False
    assert StockMovement.all_objects.filter(pk=pk).exists() is True
    # Related manager mengikuti manager default; minta all_objects secara eksplisit.
    assert txn.stock_movements(manager="all_objects").filter(pk=pk).exists() is True
    assert StockMovement.all_objects.get(pk=pk).transaction_id == txn.pk


@pytest.mark.django_db
def test_attachment_soft_delete():
    txn = make_transaction(item=make_item())
    attachment = make_attachment(txn)
    pk = attachment.pk

    attachment.soft_delete()

    assert Attachment.objects.filter(pk=pk).exists() is False
    assert Attachment.all_objects.filter(pk=pk).exists() is True
    assert txn.attachments(manager="all_objects").filter(pk=pk).exists() is True


@pytest.mark.django_db
def test_queryset_alive_dan_dead():
    item = make_item()
    alive = make_transaction(item=item, value_date=date(2026, 10, 1))
    dead = make_transaction(item=item, value_date=date(2026, 10, 2))
    dead.soft_delete()

    assert set(Transaction.all_objects.alive().values_list("pk", flat=True)) == {alive.pk}
    assert set(Transaction.all_objects.dead().values_list("pk", flat=True)) == {dead.pk}
