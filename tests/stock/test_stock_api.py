"""Antarmuka stok: lock, arah, saldo berjalan, dan movement transaksi."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.db import transaction

from core import messages
from core.errors import DomainError
from master.models import StockItem
from stock import api as stock_api
from stock.models import StockMovement
from tests.factories import make_item, make_movement, make_stock_item, make_transaction


@pytest.mark.parametrize(
    ("flow", "expected"),
    [("income", "out"), ("expense", "in")],
)
def test_direction_for_mengikuti_arus(flow, expected):
    assert stock_api.direction_for(flow) == expected


def test_direction_for_menolak_arus_tidak_dikenal():
    with pytest.raises(DomainError) as exc:
        stock_api.direction_for("transfer")

    assert exc.value.message == messages.ITEM_FLOW_INVALID


@pytest.mark.django_db
def test_lock_items_mengembalikan_peta_dan_lock_kosong_aman():
    egg = make_stock_item("egg")
    feed = make_stock_item("feed")

    with transaction.atomic():
        locked = stock_api.lock_items([feed.pk, egg.pk])

    assert locked == {egg.pk: egg, feed.pk: feed}
    assert stock_api.lock_items([]) == {}


@pytest.mark.django_db
def test_on_hand_menghormati_as_of_dan_hanya_movement_aktif():
    egg = make_stock_item("egg", opening_qty=Decimal("10"))
    make_movement(stock_item=egg, value_date=date(2026, 9, 5), direction="in", qty=Decimal("5"))
    make_movement(stock_item=egg, value_date=date(2026, 9, 10), direction="out", qty=Decimal("4"))
    deleted = make_movement(
        stock_item=egg, value_date=date(2026, 9, 12), direction="out", qty=Decimal("100")
    )
    deleted.soft_delete()

    assert stock_api.on_hand(egg.pk) == Decimal("11")
    assert stock_api.on_hand(egg.pk, as_of=date(2026, 9, 4)) == Decimal("10")
    assert stock_api.on_hand(egg.pk, as_of=date(2026, 9, 5)) == Decimal("15")
    assert stock_api.on_hand(egg.pk, as_of=date(2026, 9, 10)) == Decimal("11")


@pytest.mark.django_db
def test_assert_balance_menemukan_tanggal_pertama_minus_setelah_delta():
    egg = make_stock_item("egg", opening_qty=Decimal("10"))
    make_movement(stock_item=egg, value_date=date(2026, 9, 10), direction="out", qty=Decimal("5"))

    negative = stock_api.assert_balance_after_change(
        stock_item_id=egg.pk,
        date=date(2026, 9, 5),
        delta_by_date={date(2026, 9, 5): Decimal("-8")},
    )

    assert negative == (date(2026, 9, 10), Decimal("-3"))


@pytest.mark.django_db
def test_assert_balance_aman_bila_semua_saldo_non_negatif():
    egg = make_stock_item("egg", opening_qty=Decimal("10"))
    make_movement(stock_item=egg, value_date=date(2026, 9, 10), direction="out", qty=Decimal("5"))

    assert (
        stock_api.assert_balance_after_change(
            stock_item_id=egg.pk,
            date=date(2026, 9, 5),
            delta_by_date={date(2026, 9, 5): Decimal("-2")},
        )
        is None
    )
    assert (
        stock_api.assert_balance_after_change(
            stock_item_id=egg.pk,
            date=date(2026, 9, 20),
            delta_by_date={date(2026, 9, 20): Decimal("3")},
        )
        is None
    )


@pytest.mark.django_db
def test_upsert_dan_soft_delete_movement_transaksi():
    egg = make_stock_item("egg")
    txn = make_transaction(item=make_item())

    movement = stock_api.upsert_for_transaction(
        txn=txn, stock_item=egg, direction="out", qty=Decimal("2.000")
    )
    same = stock_api.upsert_for_transaction(
        txn=txn, stock_item=egg, direction="out", qty=Decimal("3.000")
    )

    assert same.pk == movement.pk
    assert StockMovement.objects.filter(transaction=txn).count() == 1
    assert stock_api.on_hand(egg.pk) == Decimal("-3")

    deleted = stock_api.soft_delete_for_transaction(txn.pk)

    assert deleted == 1
    assert StockMovement.objects.filter(transaction=txn).count() == 0
    assert StockMovement.all_objects.filter(transaction=txn).count() == 1
    assert stock_api.on_hand(egg.pk) == Decimal("0")


@pytest.mark.django_db
def test_opening_qty_dibaca_dari_baris_stock_item():
    egg = StockItem.objects.create(code="egg", name="Telur", unit="kg", opening_qty=7)

    assert stock_api.on_hand(egg.pk) == Decimal("7")
