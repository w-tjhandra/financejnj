"""Constraint DB yang menjadi pagar terakhir invariant domain."""

from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from audit.models import AuditLog
from core.models import PeriodLock
from ledger.models import ATTACHMENT_MAX_BYTES
from master.models import Item, StockItem
from tests.factories import (
    make_account,
    make_attachment,
    make_category,
    make_item,
    make_movement,
    make_stock_item,
    make_transaction,
)


@pytest.mark.django_db
@pytest.mark.parametrize("amount", [Decimal("0.00"), Decimal("-1.00")])
def test_amount_harus_positif(amount):
    item = make_item()

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            make_transaction(item=item, amount=amount)


@pytest.mark.django_db
@pytest.mark.parametrize("qty", [Decimal("0.000"), Decimal("-0.001")])
def test_qty_harus_positif(qty):
    item = make_item()

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            make_transaction(item=item, qty=qty, unit="kg")


@pytest.mark.django_db
def test_qty_wajib_punya_unit():
    item = make_item()

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            make_transaction(item=item, qty=Decimal("1.000"), unit=None)


@pytest.mark.django_db
def test_unit_tanpa_qty_diizinkan():
    item = make_item()

    txn = make_transaction(item=item, qty=None, unit="kg")

    assert txn.qty is None
    assert txn.unit == "kg"


@pytest.mark.django_db
def test_item_non_stok_boleh_qty_informasional():
    item = make_item(name="Jual Ayam Afkir", flow="income", stock_item=None, unit="ekor")

    txn = make_transaction(item=item, qty=Decimal("2.000"), unit="ekor")

    assert txn.qty == Decimal("2.000")
    assert txn.unit == "ekor"


@pytest.mark.django_db
def test_adjustment_reason_minimal_10_karakter():
    stock = make_stock_item()

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            make_movement(
                stock_item=stock,
                source="adjustment",
                reason="pendek",
                direction="out",
            )

    movement = make_movement(
        stock_item=stock,
        source="adjustment",
        reason="koreksi stok",
        direction="out",
    )
    assert movement.reason == "koreksi stok"


@pytest.mark.django_db
def test_unique_gaji_per_item_kategori_akun_bulan():
    category = make_category()
    account = make_account()
    item = make_item(name="Gaji Karyawan", flow="expense", frequency="monthly")
    period = date(2026, 10, 1)

    first = make_transaction(
        item=item,
        category=category,
        account=account,
        period_month=period,
        value_date=date(2026, 10, 5),
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            make_transaction(
                item=item,
                category=category,
                account=account,
                period_month=period,
                value_date=date(2026, 10, 6),
            )

    first.soft_delete()
    second = make_transaction(
        item=item,
        category=category,
        account=account,
        period_month=period,
        value_date=date(2026, 10, 7),
    )
    assert second.pk != first.pk


@pytest.mark.django_db
def test_unique_movement_per_transaksi_dan_stok():
    stock = make_stock_item()
    item = make_item(stock_item=stock, unit="kg")
    txn = make_transaction(item=item)

    make_movement(stock_item=stock, source="transaction", transaction=txn, direction="in")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            make_movement(stock_item=stock, source="transaction", transaction=txn, direction="in")


@pytest.mark.django_db
def test_period_lock_harus_tanggal_satu():
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PeriodLock.objects.create(period=date(2026, 10, 2))

    lock = PeriodLock.objects.create(period=date(2026, 10, 1))
    assert lock.is_locked is True


@pytest.mark.django_db
@pytest.mark.parametrize(
    "mime_type", ["text/plain", "image/gif", "application/zip", "application/octet-stream"]
)
def test_attachment_mime_dibatasi(mime_type):
    item = make_item()
    txn = make_transaction(item=item)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            make_attachment(txn, mime_type=mime_type)


@pytest.mark.django_db
@pytest.mark.parametrize("size_bytes", [0, ATTACHMENT_MAX_BYTES + 1])
def test_attachment_size_1_sampai_10mb(size_bytes):
    item = make_item()
    txn = make_transaction(item=item)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            make_attachment(txn, size_bytes=size_bytes)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("entity", "action"),
    [("tidak_ada", "create"), ("transaction", "tidak_ada")],
)
def test_audit_entity_dan_action_dibatasi(entity, action):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            AuditLog.objects.create(entity=entity, entity_id=1, action=action)


@pytest.mark.django_db
def test_stock_item_code_dibatasi():
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            StockItem.objects.create(code="lain", name="Lain", unit="kg")


@pytest.mark.django_db
def test_item_stok_wajib_unit_di_db():
    stock = make_stock_item()

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Item.objects.create(name="Pakan Uji", flow="expense", stock_item=stock, unit=None)
