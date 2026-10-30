"""Test service stok harian: produksi, pemakaian, penyesuaian, hapus manual.

AC-09.1–09.5 (produksi), AC-10.1–10.6 (pemakaian), AC-14.1–14.6 (penyesuaian),
AC-15.1–15.5 (hapus manual).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from audit.models import AuditLog
from core.errors import DomainError, NotFound, StockConflict
from master.models import Item, StockItem
from master.services.seed import ensure_master_data
from stock.models import StockMovement
from stock.services.daily import (
    adjust_stock,
    delete_manual,
    record_consumption,
    record_production,
)
from tests.factories import make_category, make_movement

EXC = (DomainError, StockConflict, NotFound)


@pytest.fixture
def seeded_stok(completed_setup):
    ensure_master_data(
        stock={
            "feed": {"qty": Decimal("1000")},
            "egg": {"qty": Decimal("0")},
            "manure": {"qty": Decimal("0")},
        }
    )
    return completed_setup


def _get_stock_item(code):
    return StockItem.objects.get(code=code)


def _user(seeded_stok):
    return seeded_stok


def test_ac_09_1_produksi_telur_membuat_movement_in(seeded_stok):
    egg = _get_stock_item("egg")
    m = record_production(
        stock_item=egg, date=date(2026, 10, 1), qty=Decimal("10"), actor=_user(seeded_stok)
    )
    assert m.direction == "in"
    assert m.qty == Decimal("10.000")
    assert m.source == "manual"
    assert AuditLog.objects.filter(entity="stock_movement", action="create").count() == 1


def test_ac_09_2_produksi_kotoran_membuat_movement_in(seeded_stok):
    manure = _get_stock_item("manure")
    m = record_production(
        stock_item=manure, date=date(2026, 10, 1), qty=Decimal("5"), actor=_user(seeded_stok)
    )
    assert m.direction == "in"
    assert m.qty == Decimal("5.000")


def test_ac_09_3_produksi_pakan_ditolak(seeded_stok):
    feed = _get_stock_item("feed")
    with pytest.raises(EXC):
        record_production(
            stock_item=feed, date=date(2026, 10, 1), qty=Decimal("10"), actor=_user(seeded_stok)
        )


def test_ac_09_4_qty_nol_ditolak(seeded_stok):
    egg = _get_stock_item("egg")
    with pytest.raises(EXC):
        record_production(
            stock_item=egg, date=date(2026, 10, 1), qty=Decimal("0"), actor=_user(seeded_stok)
        )


def test_ac_09_5_saldo_tidak_boleh_minus(seeded_stok):
    feed = _get_stock_item("feed")
    feed.opening_qty = Decimal("10")
    feed.save()
    record_consumption(
        stock_item=feed, date=date(2026, 10, 1), qty=Decimal("5"), actor=_user(seeded_stok)
    )
    with pytest.raises(EXC):
        record_consumption(
            stock_item=feed, date=date(2026, 10, 2), qty=Decimal("6"), actor=_user(seeded_stok)
        )


def test_ac_10_1_pemakaian_pakan_membuat_movement_out(seeded_stok):
    feed = _get_stock_item("feed")
    feed.opening_qty = Decimal("100")
    feed.save()
    m = record_consumption(
        stock_item=feed, date=date(2026, 10, 1), qty=Decimal("10"), actor=_user(seeded_stok)
    )
    assert m.direction == "out"
    assert m.qty == Decimal("10.000")
    assert m.source == "manual"


def test_ac_10_2_pemakaian_telur_ditolak(seeded_stok):
    egg = _get_stock_item("egg")
    with pytest.raises(EXC):
        record_consumption(
            stock_item=egg, date=date(2026, 10, 1), qty=Decimal("5"), actor=_user(seeded_stok)
        )


def test_ac_10_3_pemakaian_kotoran_ditolak(seeded_stok):
    manure = _get_stock_item("manure")
    with pytest.raises(EXC):
        record_consumption(
            stock_item=manure, date=date(2026, 10, 1), qty=Decimal("5"), actor=_user(seeded_stok)
        )


def test_ac_10_4_saldo_pakan_tidak_boleh_minus(seeded_stok):
    feed = _get_stock_item("feed")
    feed.opening_qty = Decimal("10")
    feed.save()
    with pytest.raises(EXC):
        record_consumption(
            stock_item=feed, date=date(2026, 10, 1), qty=Decimal("11"), actor=_user(seeded_stok)
        )


def test_ac_10_5_saldo_kumulatif_per_tanggal(seeded_stok):
    feed = _get_stock_item("feed")
    feed.opening_qty = Decimal("50")
    feed.save()
    record_consumption(
        stock_item=feed, date=date(2026, 10, 1), qty=Decimal("30"), actor=_user(seeded_stok)
    )
    record_consumption(
        stock_item=feed, date=date(2026, 10, 2), qty=Decimal("20"), actor=_user(seeded_stok)
    )
    with pytest.raises(EXC):
        record_consumption(
            stock_item=feed, date=date(2026, 10, 3), qty=Decimal("1"), actor=_user(seeded_stok)
        )


def test_ac_10_6_audit_tercatat(seeded_stok):
    feed = _get_stock_item("feed")
    feed.opening_qty = Decimal("100")
    feed.save()
    record_consumption(
        stock_item=feed, date=date(2026, 10, 1), qty=Decimal("10"), actor=_user(seeded_stok)
    )
    assert AuditLog.objects.filter(entity="stock_movement", action="create").count() == 1


def test_ac_14_1_positif_tambah_stok(seeded_stok):
    feed = _get_stock_item("feed")
    feed.opening_qty = Decimal("100")
    feed.save()
    m = adjust_stock(
        stock_item=feed,
        date=date(2026, 10, 1),
        signed_qty=Decimal("20"),
        reason="Sisa pakan ditemukan di gudang",
        actor=_user(seeded_stok),
    )
    assert m.direction == "in"
    assert m.qty == Decimal("20.000")
    assert m.source == "adjustment"


def test_ac_14_2_negatif_kurang_stok(seeded_stok):
    feed = _get_stock_item("feed")
    feed.opening_qty = Decimal("100")
    feed.save()
    m = adjust_stock(
        stock_item=feed,
        date=date(2026, 10, 1),
        signed_qty=Decimal("-15"),
        reason="Pakan rusak dibuang",
        actor=_user(seeded_stok),
    )
    assert m.direction == "out"
    assert m.qty == Decimal("15.000")


def test_ac_14_3_alasan_dibawah_10_ditolak(seeded_stok):
    feed = _get_stock_item("feed")
    with pytest.raises(EXC):
        adjust_stock(
            stock_item=feed,
            date=date(2026, 10, 1),
            signed_qty=Decimal("5"),
            reason="pendek",
            actor=_user(seeded_stok),
        )


def test_ac_14_4_hasil_tidak_boleh_minus(seeded_stok):
    feed = _get_stock_item("feed")
    feed.opening_qty = Decimal("10")
    feed.save()
    with pytest.raises(EXC):
        adjust_stock(
            stock_item=feed,
            date=date(2026, 10, 1),
            signed_qty=Decimal("-20"),
            reason="Koreksi besar yang tidak valid",
            actor=_user(seeded_stok),
        )


def test_ac_14_5_signed_qty_nol_ditolak(seeded_stok):
    feed = _get_stock_item("feed")
    with pytest.raises(EXC):
        adjust_stock(
            stock_item=feed,
            date=date(2026, 10, 1),
            signed_qty=Decimal("0"),
            reason="Alasan yang cukup panjang disini",
            actor=_user(seeded_stok),
        )


def test_ac_14_6_audit_tercatat(seeded_stok):
    feed = _get_stock_item("feed")
    feed.opening_qty = Decimal("100")
    feed.save()
    adjust_stock(
        stock_item=feed,
        date=date(2026, 10, 1),
        signed_qty=Decimal("10"),
        reason="Alasan penyesuaian yang valid",
        actor=_user(seeded_stok),
    )
    assert AuditLog.objects.filter(entity="stock_movement", action="create").count() == 1


def test_ac_15_1_hapus_manual_mengembalikan_stok(seeded_stok):
    feed = _get_stock_item("feed")
    feed.opening_qty = Decimal("100")
    feed.save()
    m = record_consumption(
        stock_item=feed, date=date(2026, 10, 1), qty=Decimal("20"), actor=_user(seeded_stok)
    )
    delete_manual(movement_id=m.pk, actor=_user(seeded_stok))
    m.refresh_from_db()
    assert m.deleted_at is not None
    assert AuditLog.objects.filter(entity="stock_movement", action="delete").count() == 1


def test_ac_15_2_hapus_idempoten(seeded_stok):
    feed = _get_stock_item("feed")
    feed.opening_qty = Decimal("100")
    feed.save()
    m = record_consumption(
        stock_item=feed, date=date(2026, 10, 1), qty=Decimal("20"), actor=_user(seeded_stok)
    )
    delete_manual(movement_id=m.pk, actor=_user(seeded_stok))
    result = delete_manual(movement_id=m.pk, actor=_user(seeded_stok))
    assert result.pk == m.pk
    assert AuditLog.objects.filter(entity="stock_movement", action="delete").count() == 1


def test_ac_15_3_hapus_adjustment_ditolak(seeded_stok):
    feed = _get_stock_item("feed")
    feed.opening_qty = Decimal("100")
    feed.save()
    m = adjust_stock(
        stock_item=feed,
        date=date(2026, 10, 1),
        signed_qty=Decimal("10"),
        reason="Alasan penyesuaian yang valid",
        actor=_user(seeded_stok),
    )
    with pytest.raises(EXC):
        delete_manual(movement_id=m.pk, actor=_user(seeded_stok))


def test_ac_15_4_hapus_movement_transaksi_ditolak(seeded_stok):
    feed = _get_stock_item("feed")
    cat = make_category(code="UMUM", name="Umum")
    item = Item.objects.create(name="Obat Test", flow="expense", default_category=cat)
    from ledger.models import Account, Transaction

    acc = Account.objects.create(
        name="Kas",
        type="cash",
        currency="IDR",
        opening_balance=Decimal("100"),
        opening_balance_date=date(2026, 9, 1),
    )
    txn = Transaction.objects.create(
        date=date(2026, 10, 1),
        flow="expense",
        category=cat,
        item=item,
        account=acc,
        amount=Decimal("100.00"),
    )
    make_movement(
        stock_item=feed,
        value_date=date(2026, 10, 1),
        direction="out",
        qty=Decimal("5"),
        source="transaction",
        transaction=txn,
    )
    mv = StockMovement.objects.filter(source="transaction").first()
    with pytest.raises(EXC):
        delete_manual(movement_id=mv.pk, actor=_user(seeded_stok))


def test_ac_15_5_hapus_yang_bikin_saldo_minus_ditolak(seeded_stok):
    feed = _get_stock_item("feed")
    feed.opening_qty = Decimal("10")
    feed.save()
    # IN adjustment on Oct 1
    m1 = adjust_stock(
        stock_item=feed,
        date=date(2026, 10, 1),
        signed_qty=Decimal("5"),
        reason="Penyesuaian stok masuk",
        actor=_user(seeded_stok),
    )
    # OUT consumption on Oct 2
    record_consumption(
        stock_item=feed, date=date(2026, 10, 2), qty=Decimal("12"), actor=_user(seeded_stok)
    )
    # Hapus IN adjustment → saldo jadi negatif di Oct 2, harus ditolak
    with pytest.raises(EXC):
        delete_manual(movement_id=m1.pk, actor=_user(seeded_stok))
    assert m1.deleted_at is None
