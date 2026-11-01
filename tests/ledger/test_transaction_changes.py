"""Update, delete, dan duplikat transaksi (FR-10, FR-11, FR-12)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from audit.models import AuditLog
from core import messages
from core.errors import (
    DomainError,
    DuplicateSalary,
    NotFound,
    PeriodLocked,
    StockConflict,
)
from core.services.locks import lock_period
from core.types import RequestMeta
from core.utils.dates import today_wib
from ledger.models import Attachment, Transaction
from ledger.services.opening import record_opening_correction
from ledger.services.transactions import (
    create_transaction,
    delete_transaction,
    duplicate_prefill,
    update_transaction,
)
from master.models import Category, Item, StockItem
from master.services.seed import ensure_master_data
from stock import api as stock_api
from stock.models import StockMovement
from tests.factories import make_attachment

FIXED_TODAY = date(2026, 10, 29)


@pytest.fixture
def seeded(completed_setup):
    ensure_master_data(
        stock={
            "feed": {"qty": Decimal("1000")},
            "egg": {"qty": Decimal("100")},
            "manure": {"qty": Decimal("30")},
        }
    )
    return completed_setup


def _create(*, item_code="egg_sales", amount="520000", actor=None, **kwargs):
    item = Item.objects.get(code=item_code)
    kwargs.setdefault("date", date(2026, 9, 20))
    kwargs.setdefault("flow", item.flow)
    kwargs.setdefault("category", item.default_category)
    kwargs.setdefault("item", item)
    kwargs.setdefault("amount", amount)
    if kwargs.get("payment_method") == "transfer":
        kwargs.setdefault("transfer_bank", "bca")
    return create_transaction(actor=actor, **kwargs)


def _update(txn, **kwargs):
    values = {
        "transaction_id": txn.pk,
        "date": txn.date,
        "flow": txn.flow,
        "category": txn.category,
        "item": txn.item,
        "amount": txn.amount,
        "qty": txn.qty,
        "unit": txn.unit,
        "payment_method": txn.payment_method,
        "transfer_bank": txn.transfer_bank or ("bca" if txn.payment_method == "transfer" else None),
        "notes": txn.notes,
        "period_month": txn.period_month,
    }
    values.update(kwargs)
    return update_transaction(**values)


def _egg() -> StockItem:
    return StockItem.objects.get(code="egg")


# --- AC-10: edit transaksi (delta movement) -------------------------------


def test_ac_10_1_edit_qty_mengubah_movement_yang_sama(seeded):
    txn = _create(item_code="egg_sales", qty="20")
    movement = StockMovement.objects.get(transaction=txn)
    assert stock_api.on_hand(_egg().pk) == Decimal("80")

    _update(txn, qty="30")

    txn.refresh_from_db()
    movement.refresh_from_db()
    assert txn.qty == Decimal("30.000")
    assert stock_api.on_hand(_egg().pk) == Decimal("70")
    assert StockMovement.all_objects.filter(transaction=txn).count() == 1
    assert StockMovement.objects.filter(transaction=txn).count() == 1
    assert movement.pk == StockMovement.objects.get(transaction=txn).pk
    assert movement.qty == Decimal("30.000")
    assert movement.date == date(2026, 9, 20)
    assert movement.direction == "out"
    assert Transaction.objects.count() == 1


def test_ac_10_2_item_menjadi_non_stok_soft_delete_movement(seeded):
    txn = _create(item_code="egg_sales", qty="20")
    assert stock_api.on_hand(_egg().pk) == Decimal("80")

    _update(
        txn,
        item=Item.objects.get(code="afkir_sales"),
        category=Category.objects.get(code="AFKIR"),
        qty=None,
        unit=None,
    )

    txn.refresh_from_db()
    assert txn.qty is None
    assert txn.item.code == "afkir_sales"
    assert stock_api.on_hand(_egg().pk) == Decimal("100")
    assert StockMovement.objects.filter(transaction=txn).count() == 0
    stale = StockMovement.all_objects.get(transaction=txn)
    assert stale.deleted_at is not None


def test_ac_10_3_pindah_tanggal_membawa_movement(seeded):
    txn = _create(item_code="egg_sales", qty="20", date=date(2026, 9, 30))
    assert stock_api.on_hand(_egg().pk, as_of=date(2026, 9, 14)) == Decimal("100")

    _update(txn, date=date(2026, 9, 15))

    txn.refresh_from_db()
    movement = StockMovement.objects.get(transaction=txn)
    assert txn.date == date(2026, 9, 15)
    assert movement.date == date(2026, 9, 15)
    assert stock_api.on_hand(_egg().pk, as_of=date(2026, 9, 14)) == Decimal("100")
    assert stock_api.on_hand(_egg().pk, as_of=date(2026, 9, 29)) == Decimal("80")
    assert stock_api.on_hand(_egg().pk) == Decimal("80")
    assert StockMovement.all_objects.filter(transaction=txn).count() == 1


def test_ac_10_4_edit_yang_membuat_saldo_minus_ditolak(seeded):
    first = _create(item_code="egg_sales", qty="80", date=date(2026, 9, 10))
    _create(item_code="egg_sales", qty="15", date=date(2026, 9, 15))

    with pytest.raises(StockConflict) as exc:
        _update(first, qty="90")

    assert exc.value.message == messages.STOCK_WILL_NEGATIVE.format(
        name="Telur", date="15/09/2026", balance="-5", unit="kg"
    )
    assert exc.value.http_status == 409
    first.refresh_from_db()
    assert first.qty == Decimal("80.000")
    assert StockMovement.objects.get(transaction=first).qty == Decimal("80.000")
    assert stock_api.on_hand(_egg().pk) == Decimal("5")
    assert not AuditLog.objects.filter(action="update").exists()


def test_ac_10_6_created_tetap_updated_berubah_dan_audit_diff(seeded):
    txn = _create(item_code="egg_sales", qty="2", actor=seeded)
    past = timezone.now() - timedelta(days=2)
    Transaction.objects.filter(pk=txn.pk).update(updated_at=past)
    txn.refresh_from_db()
    created_at = txn.created_at
    created_by_id = txn.created_by_id

    meta = RequestMeta(ip="203.0.113.7", user_agent="uji-edit")
    _update(txn, amount="600000", qty="3", actor=seeded, meta=meta)

    txn.refresh_from_db()
    assert txn.created_at == created_at
    assert txn.created_by_id == created_by_id == seeded.pk
    assert txn.updated_by_id == seeded.pk
    assert txn.updated_at > past

    audit = AuditLog.objects.get(entity="transaction", action="update")
    assert audit.user_id == seeded.pk
    assert audit.ip == "203.0.113.7"
    assert set(audit.before) == {"amount", "qty"}
    assert audit.before["amount"] == "520000.00"
    assert audit.after["amount"] == "600000.00"
    assert audit.before["qty"] == "2.000"
    assert audit.after["qty"] == "3.000"
    assert "created_by" not in audit.before


def test_ganti_jenis_stok_menghapus_movement_lama_dan_membuat_baru(seeded):
    txn = _create(item_code="egg_sales", qty="20")

    _update(
        txn,
        item=Item.objects.get(code="manure_sales"),
        category=Category.objects.get(code="UMUM"),
        qty="5",
    )

    txn.refresh_from_db()
    assert stock_api.on_hand(_egg().pk) == Decimal("100")
    assert stock_api.on_hand(StockItem.objects.get(code="manure").pk) == Decimal("25")
    assert StockMovement.objects.filter(transaction=txn).count() == 1
    active = StockMovement.objects.get(transaction=txn)
    assert active.stock_item.code == "manure"
    assert active.direction == "out"
    assert active.qty == Decimal("5.000")
    assert StockMovement.all_objects.filter(transaction=txn).count() == 2


def test_edit_qty_kosong_item_ber_stok_ditolak(seeded):
    txn = _create(item_code="egg_sales", qty="20")

    with pytest.raises(DomainError) as exc:
        _update(txn, qty=None)

    assert exc.value.message == messages.QTY_REQUIRED
    assert stock_api.on_hand(_egg().pk) == Decimal("80")
    assert not AuditLog.objects.filter(action="update").exists()


def test_edit_tanggal_sebelum_saldo_awal_ditolak(seeded):
    txn = _create(item_code="medicine", amount="1000")

    with pytest.raises(DomainError) as exc:
        _update(txn, date=date(2026, 8, 31))

    assert exc.value.message == messages.date_before_opening(date(2026, 9, 1))
    txn.refresh_from_db()
    assert txn.date == date(2026, 9, 20)


@pytest.mark.parametrize("new_date", [date(2026, 9, 20), date(2026, 10, 1)])
def test_edit_pada_periode_terkunci_ditolak(seeded, new_date):
    """Tanggal lama ikut dicek: transaksi September tidak lolos walau pindah ke Oktober."""
    txn = _create(item_code="medicine", amount="1000", date=date(2026, 9, 20))
    lock_period(date(2026, 9, 1), actor=seeded)

    with pytest.raises(PeriodLocked):
        _update(txn, date=new_date)

    txn.refresh_from_db()
    assert txn.date == date(2026, 9, 20)
    assert not AuditLog.objects.filter(action="update").exists()


def test_edit_gaji_menabrak_baris_lain_menghasilkan_duplicate_salary(seeded):
    salary = Item.objects.get(code="salary")
    umum = Category.objects.get(code="UMUM")
    layer = Category.objects.get(code="LAYER")
    kwargs = {
        "date": date(2026, 9, 30),
        "flow": "expense",
        "item": salary,
        "amount": "6000000",
        "period_month": date(2026, 9, 1),
    }
    existing = create_transaction(category=umum, **kwargs)
    second = create_transaction(category=layer, **kwargs)

    with pytest.raises(DuplicateSalary) as exc:
        _update(second, category=umum)

    assert exc.value.existing_id == existing.pk
    second.refresh_from_db()
    assert second.category_id == layer.pk
    assert Transaction.objects.filter(item=salary).count() == 2


def test_edit_item_nonaktif_yang_sama_diizinkan(seeded):
    txn = _create(item_code="medicine", amount="1000")
    medicine = txn.item
    medicine.is_active = False
    medicine.save(update_fields=["is_active", "updated_at"])

    updated = _update(txn, amount="2000")

    assert updated.amount == Decimal("2000.00")
    assert updated.item_id == medicine.pk


def test_edit_transaksi_terhapus_not_found(seeded):
    txn = _create(item_code="medicine", amount="1000")
    delete_transaction(transaction_id=txn.pk)

    with pytest.raises(NotFound):
        _update(txn, amount="2000")


# --- AC-11: soft delete transaksi ----------------------------------------


def test_ac_11_1_delete_soft_delete_transaksi_dan_movement(seeded):
    txn = _create(item_code="egg_sales", qty="20", actor=seeded)
    assert stock_api.on_hand(_egg().pk) == Decimal("80")

    delete_transaction(transaction_id=txn.pk, actor=seeded)

    assert not Transaction.objects.filter(pk=txn.pk).exists()
    deleted = Transaction.all_objects.get(pk=txn.pk)
    assert deleted.deleted_at is not None
    assert deleted.deleted_by_id == seeded.pk
    assert StockMovement.objects.filter(transaction_id=txn.pk).count() == 0
    assert StockMovement.all_objects.filter(transaction_id=txn.pk).count() == 1
    assert StockMovement.all_objects.get(transaction_id=txn.pk).deleted_at is not None
    assert stock_api.on_hand(_egg().pk) == Decimal("100")


def test_ac_11_5_audit_delete_snapshot_dan_idempoten(seeded):
    meta = RequestMeta(ip="203.0.113.8", user_agent="uji-hapus")
    txn = _create(item_code="egg_sales", qty="20", notes="Setoran pagi", actor=seeded)

    delete_transaction(transaction_id=txn.pk, actor=seeded, reason="salah input", meta=meta)
    deleted = Transaction.all_objects.get(pk=txn.pk)
    deleted_at = deleted.deleted_at

    audit = AuditLog.objects.get(entity="transaction", action="delete")
    assert audit.user_id == seeded.pk
    assert audit.ip == "203.0.113.8"
    assert audit.before["amount"] == "520000.00"
    assert audit.before["qty"] == "20.000"
    assert audit.before["notes"] == "Setoran pagi"
    assert audit.before["date"] == "2026-09-20"
    assert audit.before["created_by"] == seeded.pk
    assert audit.extra == {"movements": 1, "reason": "salah input"}

    delete_transaction(transaction_id=txn.pk, actor=seeded)
    delete_transaction(transaction_id=txn.pk, actor=seeded)

    deleted.refresh_from_db()
    assert deleted.deleted_at == deleted_at
    assert deleted.deleted_by_id == seeded.pk
    assert AuditLog.objects.filter(entity="transaction", action="delete").count() == 1


def test_delete_pada_periode_terkunci_ditolak(seeded):
    txn = _create(item_code="egg_sales", qty="20", date=date(2026, 9, 20))
    lock_period(date(2026, 9, 1), actor=seeded)

    with pytest.raises(PeriodLocked):
        delete_transaction(transaction_id=txn.pk, actor=seeded)

    assert Transaction.objects.filter(pk=txn.pk).exists()
    assert StockMovement.objects.filter(transaction=txn).count() == 1
    assert not AuditLog.objects.filter(action="delete").exists()


def test_delete_transaksi_non_stok_tanpa_movement(seeded):
    txn = _create(item_code="afkir_sales", amount="5400000")

    delete_transaction(transaction_id=txn.pk)

    assert not Transaction.objects.filter(pk=txn.pk).exists()
    assert StockMovement.all_objects.filter(transaction_id=txn.pk).count() == 0
    audit = AuditLog.objects.get(entity="transaction", action="delete")
    assert audit.extra == {"movements": 0}


def test_delete_tidak_menghapus_lampiran(seeded):
    txn = _create(item_code="egg_sales", qty="20")
    attachment = make_attachment(txn)
    file_path = attachment.file

    delete_transaction(transaction_id=txn.pk)

    kept = Attachment.all_objects.get(pk=attachment.pk)
    assert kept.deleted_at is None
    assert kept.file == file_path


def test_delete_transaksi_tidak_ada_not_found(seeded):
    with pytest.raises(NotFound):
        delete_transaction(transaction_id=999_999)


def test_delete_yang_membuat_saldo_minus_ditolak(seeded):
    """Menghapus pembelian awal tidak boleh membuat penjualan sesudahnya minus."""
    egg = _egg()
    purchase_item = Item.objects.create(
        name="Pembelian Telur Uji", flow="expense", stock_item=egg, unit="kg"
    )
    purchase = create_transaction(
        date=date(2026, 9, 10),
        flow="expense",
        category=Category.objects.get(code="UMUM"),
        item=purchase_item,
        amount="1500000",
        qty="30",
    )
    _create(item_code="egg_sales", qty="120", date=date(2026, 9, 20))
    assert stock_api.on_hand(egg.pk) == Decimal("10")

    with pytest.raises(StockConflict) as exc:
        delete_transaction(transaction_id=purchase.pk, actor=seeded)

    assert exc.value.message == messages.STOCK_WILL_NEGATIVE.format(
        name="Telur", date="20/09/2026", balance="-20", unit="kg"
    )
    assert exc.value.http_status == 409
    assert Transaction.objects.filter(pk=purchase.pk).exists()
    assert StockMovement.objects.filter(transaction=purchase).count() == 1
    assert stock_api.on_hand(egg.pk) == Decimal("10")
    assert not AuditLog.objects.filter(entity="transaction", action="delete").exists()


def test_delete_koreksi_saldo_awal_ditolak(seeded):
    """K-03: koreksi saldo awal read-only; koreksi balik lewat koreksi baru."""
    _create(item_code="medicine", amount="1000")
    correction = record_opening_correction(
        delta="100000", reason="Koreksi saldo awal uji", actor=seeded
    )

    with pytest.raises(DomainError) as exc:
        delete_transaction(transaction_id=correction.pk, actor=seeded)

    assert exc.value.code == "opening_correction_locked"
    correction.refresh_from_db()
    assert correction.deleted_at is None
    assert correction.deleted_by_id is None
    assert Transaction.objects.filter(pk=correction.pk).exists()
    assert not AuditLog.objects.filter(entity="transaction", action="delete").exists()


# --- AC-12: duplikat prefill ----------------------------------------------


def test_ac_12_1_duplikat_prefill_tanggal_hari_ini_dan_field_sama(seeded, monkeypatch):
    monkeypatch.setattr("ledger.services.transactions.today_wib", lambda: FIXED_TODAY)
    egg = _egg()
    egg.opening_qty = Decimal("1000")
    egg.save(update_fields=["opening_qty", "updated_at"])
    txn = _create(
        item_code="egg_sales",
        amount="6500000",
        qty="250",
        payment_method="transfer",
        transfer_bank="mandiri",
        notes="Setoran pagi",
        date=date(2026, 10, 27),
    )

    prefill = duplicate_prefill(txn.pk)

    assert prefill["date"] == FIXED_TODAY
    assert prefill["flow"] == txn.flow
    assert prefill["category"].pk == txn.category_id
    assert prefill["item"].pk == txn.item_id
    assert prefill["amount"] == Decimal("6500000.00")
    assert prefill["qty"] == Decimal("250.000")
    assert prefill["unit"] == "kg"
    assert prefill["payment_method"] == "transfer"
    assert prefill["transfer_bank"] == "mandiri"
    assert prefill["notes"] == "Setoran pagi"
    assert prefill["period_month"] is None
    assert "created_by" not in prefill
    assert "attachments" not in prefill


def test_ac_12_4_asal_hari_ini_tanggal_tetap(seeded, monkeypatch):
    monkeypatch.setattr("ledger.services.transactions.today_wib", lambda: FIXED_TODAY)
    txn = _create(item_code="egg_sales", qty="1", date=FIXED_TODAY)

    assert duplicate_prefill(txn.pk)["date"] == FIXED_TODAY


def test_duplikat_tidak_menulis_db(seeded, monkeypatch):
    monkeypatch.setattr("ledger.services.transactions.today_wib", lambda: FIXED_TODAY)
    txn = _create(item_code="egg_sales", qty="2", actor=seeded)
    transactions = Transaction.all_objects.count()
    movements = StockMovement.all_objects.count()
    audits = AuditLog.objects.count()

    duplicate_prefill(txn.pk)

    assert Transaction.all_objects.count() == transactions
    assert StockMovement.all_objects.count() == movements
    assert AuditLog.objects.count() == audits


def test_ac_12_3_hasil_duplikat_tanpa_lampiran(seeded, monkeypatch):
    monkeypatch.setattr("ledger.services.transactions.today_wib", lambda: FIXED_TODAY)
    source = _create(item_code="egg_sales", qty="5")
    make_attachment(source)
    make_attachment(source, file="attachments/2026/10/uji-2.pdf", original_name="uji-2.pdf")
    prefill = duplicate_prefill(source.pk)

    duplicated = create_transaction(**prefill)

    assert duplicated.pk != source.pk
    assert duplicated.attachments.count() == 0
    assert source.attachments.count() == 2


def test_duplikat_gaji_menghitung_ulang_bulan_berjalan(seeded, monkeypatch):
    monkeypatch.setattr("ledger.services.transactions.today_wib", lambda: FIXED_TODAY)
    salary = Item.objects.get(code="salary")
    source = create_transaction(
        date=date(2026, 9, 30),
        flow="expense",
        category=Category.objects.get(code="UMUM"),
        item=salary,
        amount="6000000",
        period_month=date(2026, 9, 1),
    )

    prefill = duplicate_prefill(source.pk)

    assert prefill["period_month"] == date(2026, 10, 1)
    assert prefill["date"] == FIXED_TODAY


def test_duplikat_transaksi_terhapus_not_found(seeded):
    txn = _create(item_code="medicine", amount="1000")
    delete_transaction(transaction_id=txn.pk)

    with pytest.raises(NotFound):
        duplicate_prefill(txn.pk)


def test_today_wib_dipakai_untuk_prefill(seeded):
    """Tanpa monkeypatch: prefill memakai kalender WIB hari ini."""
    txn = _create(item_code="medicine", amount="1000")

    assert duplicate_prefill(txn.pk)["date"] == today_wib()
