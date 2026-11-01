"""Create transaksi (FR-08), gaji bulanan (FR-09), dan konkurensi D1."""

from __future__ import annotations

import threading
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.db import close_old_connections

from audit.models import AuditLog
from core import messages
from core.errors import (
    DomainError,
    DuplicateSalary,
    PeriodLocked,
    StockConflict,
    StockInsufficient,
)
from core.services.locks import lock_period
from core.types import RequestMeta
from core.utils.dates import today_wib
from ledger.models import Transaction
from ledger.services.transactions import create_transaction
from master.models import Category, Item, StockItem
from master.services.seed import ensure_master_data
from stock import api as stock_api
from stock.models import StockMovement


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
    return create_transaction(actor=actor, **kwargs)


def test_ac_08_1_item_ber_stok_wajib_qty(seeded):
    with pytest.raises(DomainError) as exc:
        _create(item_code="egg_sales", qty=None)

    assert exc.value.message == messages.QTY_REQUIRED
    assert Transaction.objects.count() == 0
    assert StockMovement.objects.count() == 0


def test_ac_08_1_dan_08_10_item_non_stok_qty_opsional(seeded):
    txn = _create(item_code="afkir_sales", amount="5400000", qty=None)

    assert txn.qty is None
    assert txn.unit is None
    assert StockMovement.objects.count() == 0
    assert stock_api.on_hand(StockItem.objects.get(code="egg").pk) == Decimal("100")


def test_ac_08_11_qty_non_stok_informasional_tanpa_movement(seeded):
    dry_run_count = StockMovement.objects.count()

    txn = _create(
        item_code="afkir_sales",
        amount="5400000",
        qty="2000",
        unit="ekor",
    )

    assert txn.qty == Decimal("2000.000")
    assert txn.unit == "ekor"
    assert StockMovement.objects.count() == dry_run_count
    assert stock_api.on_hand(StockItem.objects.get(code="egg").pk) == Decimal("100")


def test_ac_08_2_penjualan_telur_mengurangi_stok_dan_membuat_movement_out(seeded):
    txn = _create(item_code="egg_sales", amount="520000", qty="20")

    egg = StockItem.objects.get(code="egg")
    movement = StockMovement.objects.get(transaction=txn)

    assert stock_api.on_hand(egg.pk) == Decimal("80")
    assert movement.stock_item_id == egg.pk
    assert movement.direction == "out"
    assert movement.qty == Decimal("20.000")
    assert movement.source == "transaction"


def test_pembelian_pakan_membuat_movement_in(seeded):
    txn = _create(item_code="feed", amount="300000", qty="25")

    movement = StockMovement.objects.get(transaction=txn)

    assert movement.direction == "in"
    assert stock_api.on_hand(StockItem.objects.get(code="feed").pk) == Decimal("1025")


def test_ac_08_3_stok_tidak_cukup_ditolak_tanpa_data_parsial(seeded):
    egg = StockItem.objects.get(code="egg")
    egg.opening_qty = Decimal("10")
    egg.save(update_fields=["opening_qty", "updated_at"])

    with pytest.raises(StockInsufficient) as exc:
        _create(item_code="egg_sales", date=date(2026, 9, 20), qty="20")

    assert exc.value.http_status == 409
    assert exc.value.message == messages.STOCK_INSUFFICIENT_DETAIL.format(
        name="Telur",
        date="20 Sep 2026",
        qty="10",
        unit="kg",
        requested="20",
    )
    assert Transaction.objects.count() == 0
    assert StockMovement.objects.count() == 0
    assert AuditLog.objects.filter(entity="transaction").count() == 0


def test_ac_08_4_tanggal_sebelum_saldo_awal_ditolak(seeded):
    with pytest.raises(DomainError) as exc:
        _create(item_code="medicine", date=date(2026, 8, 31), amount="1000")

    assert exc.value.message == messages.date_before_opening(date(2026, 9, 1))


def test_ac_08_5_tanggal_masa_depan_ditolak(seeded):
    with pytest.raises(DomainError) as exc:
        _create(item_code="medicine", date=today_wib() + timedelta(days=1), amount="1000")

    assert exc.value.message == messages.TXN_DATE_AFTER_TODAY


@pytest.mark.parametrize("amount", ["0", "-5000"])
def test_ac_08_6_nominal_harus_positif(seeded, amount):
    with pytest.raises(DomainError) as exc:
        _create(item_code="medicine", amount=amount)

    assert exc.value.message == messages.AMOUNT_MIN


def test_ac_08_6_nominal_maksimum(seeded):
    with pytest.raises(DomainError) as exc:
        _create(item_code="medicine", amount="100000000001")

    assert exc.value.message == messages.AMOUNT_MAX


def test_ac_08_9_periode_terkunci_ditolak(seeded):
    lock_period(date(2026, 9, 1), actor=seeded)

    with pytest.raises(PeriodLocked) as exc:
        _create(item_code="egg_sales", date=date(2026, 9, 20), qty="1")

    assert exc.value.message == messages.period_locked(date(2026, 9, 1))
    assert not Transaction.objects.exists()
    assert not StockMovement.objects.exists()


def test_backdate_ke_bulan_terkunci_ditolak(seeded):
    lock_period(date(2026, 9, 1), actor=seeded)

    with pytest.raises(PeriodLocked):
        _create(item_code="medicine", date=date(2026, 9, 15), amount="1000")

    assert Transaction.objects.count() == 0


def test_idempotency_key_mengembalikan_transaksi_yang_sama(seeded):
    key = uuid4()

    first = _create(item_code="egg_sales", qty="2", idempotency_key=key)
    second = _create(item_code="egg_sales", qty="2", idempotency_key=key)

    assert second.pk == first.pk
    assert Transaction.objects.count() == 1
    assert StockMovement.objects.count() == 1
    assert AuditLog.objects.filter(entity="transaction", action="create").count() == 1


def test_gaji_bulanan_duplikat_menghasilkan_duplicate_salary(seeded):
    salary = Item.objects.get(code="salary")
    category = Category.objects.get(code="UMUM")
    kwargs = {
        "date": date(2026, 9, 30),
        "flow": "expense",
        "category": category,
        "item": salary,
        "amount": "6000000",
        "period_month": date(2026, 9, 1),
        "actor": seeded,
    }

    first = create_transaction(**kwargs)
    with pytest.raises(DuplicateSalary) as exc:
        create_transaction(**kwargs)

    assert exc.value.existing_id == first.pk
    assert Transaction.objects.filter(item=salary).count() == 1


def test_gaji_kategori_afkir_ditolak(seeded):
    salary = Item.objects.get(code="salary")

    with pytest.raises(DomainError) as exc:
        create_transaction(
            date=date(2026, 9, 30),
            flow="expense",
            category=Category.objects.get(code="AFKIR"),
            item=salary,
            amount="1000000",
            period_month=date(2026, 9, 1),
        )

    assert exc.value.message == messages.SALARY_CATEGORY


def test_bulan_gaji_tidak_boleh_setelah_bulan_transaksi(seeded):
    salary = Item.objects.get(code="salary")

    with pytest.raises(DomainError) as exc:
        create_transaction(
            date=date(2026, 9, 30),
            flow="expense",
            category=Category.objects.get(code="UMUM"),
            item=salary,
            amount="1000000",
            period_month=date(2026, 10, 1),
        )

    assert exc.value.code == "period_month_after_date"


def test_item_sistem_hanya_lewat_koreksi(seeded):
    correction = Item.objects.get(code="opening_correction")

    with pytest.raises(DomainError) as exc:
        create_transaction(
            date=date(2026, 9, 20),
            flow="expense",
            category=Category.objects.get(code="UMUM"),
            item=correction,
            amount="1000",
        )

    assert exc.value.code == "item_system"


def test_riwayat_transaksi_mencatat_actor_tanpa_metadata_browser(seeded):
    meta = RequestMeta(ip="203.0.113.9", user_agent="uji")

    txn = _create(item_code="egg_sales", qty="2", actor=seeded, meta=meta)

    audit = AuditLog.objects.get(entity="transaction", action="create")
    assert audit.entity_id == txn.pk
    assert audit.user_id == seeded.pk
    assert audit.ip is None
    assert audit.user_agent is None
    assert audit.after["amount"] == "520000.00"
    assert audit.after["qty"] == "2.000"
    assert audit.after["category"] == txn.category_id
    assert audit.after["created_by"] == seeded.pk


@pytest.mark.django_db(transaction=True)
def test_ac_08_12_dua_penjualan_paralel_tepat_satu_menang(seeded, monkeypatch):
    egg = StockItem.objects.get(code="egg")
    egg.opening_qty = Decimal("30")
    egg.save(update_fields=["opening_qty", "updated_at"])

    barrier = threading.Barrier(2)
    release = threading.Event()
    locked = threading.Event()
    results: list[object] = []
    original_peek = stock_api.peek_available
    check_barrier = threading.Barrier(2)
    local = threading.local()

    def synced_peek(stock_item_id, as_of):
        available = original_peek(stock_item_id, as_of)
        if not getattr(local, "checked", False):
            local.checked = True
            check_barrier.wait(timeout=5)
        return available

    monkeypatch.setattr(stock_api, "peek_available", synced_peek)

    def hold_lock():
        locked.set()
        release.wait(timeout=5)

    def worker():
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            with stock_api.test_after_lock(hold_lock):
                _create(
                    item_code="egg_sales",
                    date=date(2026, 9, 20),
                    qty="20",
                    idempotency_key=uuid4(),
                    actor=seeded,
                )
            results.append("ok")
        except StockConflict as exc:
            results.append(("409", str(exc)))
        except Exception as exc:  # pragma: no cover - kegagalan tak terduga
            results.append(("error", repr(exc)))
        finally:
            close_old_connections()

    first = threading.Thread(target=worker)
    second = threading.Thread(target=worker)
    first.start()
    second.start()

    assert locked.wait(timeout=5)
    release.set()
    first.join(timeout=10)
    second.join(timeout=10)

    assert results.count("ok") == 1
    conflict = [result for result in results if isinstance(result, tuple) and result[0] == "409"]
    assert len(conflict) == 1
    assert conflict[0][1] == messages.STOCK_CONFLICT.format(
        name="Telur", qty="10", unit="kg", requested="20"
    )
    assert stock_api.on_hand(egg.pk) == Decimal("10")
    assert Transaction.objects.count() == 1
    assert StockMovement.objects.filter(stock_item=egg).count() == 1


def test_ac_08_12_tanpa_balapan_pesan_rinci(seeded):
    """Kalah balapan memakai pesan tersedia/diminta; stok tidak negatif."""
    egg = StockItem.objects.get(code="egg")
    egg.opening_qty = Decimal("10")
    egg.save(update_fields=["opening_qty", "updated_at"])

    with pytest.raises(StockInsufficient):
        _create(item_code="egg_sales", qty="20", date=date(2026, 9, 21))

    assert stock_api.on_hand(egg.pk) == Decimal("10")


def test_create_tidak_menulis_audit_saat_gagal(seeded):
    egg = StockItem.objects.get(code="egg")
    egg.opening_qty = Decimal("0")
    egg.save(update_fields=["opening_qty", "updated_at"])

    with pytest.raises(StockInsufficient):
        _create(item_code="egg_sales", qty="1")

    assert not AuditLog.objects.exists()
    assert not Transaction.objects.exists()
