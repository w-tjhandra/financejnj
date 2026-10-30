"""Test query rekap 4 periode (FR-16…FR-26): AC-16.x–20.x."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from ledger.models import Account, Transaction
from master.models import Category, Item
from master.services.seed import ensure_master_data
from reports.queries import daily_recap, yearly_recap
from tests.factories import make_movement, make_stock_item


@pytest.fixture
def recap_setup(completed_setup):
    ensure_master_data(
        stock={
            "feed": {"qty": Decimal("1000")},
            "egg": {"qty": Decimal("0")},
            "manure": {"qty": Decimal("0")},
        }
    )
    account = Account.objects.create(
        name="Kas",
        type="cash",
        currency="IDR",
        opening_balance=Decimal("250000000.00"),
        opening_balance_date=date(2026, 9, 1),
    )
    cat_layer = Category.objects.get(code="LAYER")
    cat_afkir = Category.objects.get(code="AFKIR")
    cat_doc = Category.objects.get(code="DOC")
    cat_umum = Category.objects.get(code="UMUM")

    item_telur = Item.objects.get(name="Pendapatan Telur", flow="income")
    item_pakan = Item.objects.get(name="Pakan", flow="expense")
    item_afkir = Item.objects.get(name="Pendapatan Ayam Afkir", flow="income")
    item_gaji = Item.objects.get(name="Gaji Karyawan", flow="expense")
    return {
        "account": account,
        "cat_layer": cat_layer,
        "cat_afkir": cat_afkir,
        "cat_doc": cat_doc,
        "cat_umum": cat_umum,
        "item_telur": item_telur,
        "item_pakan": item_pakan,
        "item_afkir": item_afkir,
        "item_gaji": item_gaji,
    }


def _txn(account, value_date, data):
    return Transaction.objects.create(
        date=value_date,
        account=account,
        **data,
    )


def test_ac_16_empat_baris_d2(recap_setup):
    d = recap_setup
    _txn(
        d["account"],
        date(2026, 10, 5),
        {
            "flow": "income",
            "category": d["cat_layer"],
            "item": d["item_telur"],
            "amount": Decimal("500000.00"),
            "qty": Decimal("10"),
            "unit": "kg",
            "period_month": date(2026, 10, 1),
        },
    )
    _txn(
        d["account"],
        date(2026, 10, 6),
        {
            "flow": "expense",
            "category": d["cat_layer"],
            "item": d["item_pakan"],
            "amount": Decimal("200000.00"),
            "qty": Decimal("50"),
            "unit": "kg",
            "period_month": date(2026, 10, 1),
        },
    )
    result = daily_recap(date(2026, 10, 1), date(2026, 10, 31), None)
    keys = {row.key for row in result.summary}
    assert keys == {
        "pemasukan",
        "pengeluaran",
        "mutasi_nonoperasional",
        "selisih",
    }


def test_ac_17_layer_muat_afkir(recap_setup):
    d = recap_setup
    _txn(
        d["account"],
        date(2026, 10, 5),
        {
            "flow": "income",
            "category": d["cat_layer"],
            "item": d["item_telur"],
            "amount": Decimal("500000.00"),
            "qty": Decimal("10"),
            "unit": "kg",
            "period_month": date(2026, 10, 1),
        },
    )
    _txn(
        d["account"],
        date(2026, 10, 6),
        {
            "flow": "income",
            "category": d["cat_afkir"],
            "item": d["item_afkir"],
            "amount": Decimal("300000.00"),
            "unit": "kg",
            "period_month": date(2026, 10, 1),
        },
    )
    result_layer = daily_recap(date(2026, 10, 1), date(2026, 10, 31), d["cat_layer"].pk)
    total_layer = sum(r.amount for r in result_layer.summary if r.key == "pemasukan")
    assert total_layer == Decimal("800000.00")
    result_afkir = daily_recap(date(2026, 10, 1), date(2026, 10, 31), d["cat_afkir"].pk)
    total_afkir = sum(r.amount for r in result_afkir.summary if r.key == "pemasukan")
    assert total_afkir == Decimal("300000.00")


def test_ac_18_saldo_sebelum_opening_nol(recap_setup):
    d = recap_setup
    _txn(
        d["account"],
        date(2026, 8, 20),
        {
            "flow": "income",
            "category": d["cat_umum"],
            "item": d["item_gaji"],
            "amount": Decimal("100000.00"),
            "unit": "kg",
            "period_month": date(2026, 8, 1),
        },
    )
    result = daily_recap(date(2026, 8, 1), date(2026, 8, 31), None)
    for row in result.summary:
        if row.key in ("pemasukan", "pengeluaran", "mutasi_nonoperasional", "selisih"):
            assert row.amount == Decimal("0")


def test_ac_19_stok_opening_in_out_adj_closing(recap_setup):
    egg = make_stock_item(code="egg", name="Telur", unit="kg", opening_qty=Decimal("100"))
    # ensure_master_data sudah membuat item egg (opening 0); get_or_create tidak menimpa.
    egg.opening_qty = Decimal("100")
    egg.save(update_fields=["opening_qty"])
    make_movement(
        stock_item=egg,
        value_date=date(2026, 10, 1),
        direction="in",
        qty=Decimal("50"),
        source="manual",
    )
    make_movement(
        stock_item=egg,
        value_date=date(2026, 10, 2),
        direction="out",
        qty=Decimal("30"),
        source="manual",
    )
    make_movement(
        stock_item=egg,
        value_date=date(2026, 10, 3),
        direction="in",
        qty=Decimal("5"),
        source="adjustment",
        reason="Penyesuaian pecah",
    )
    result = daily_recap(date(2026, 10, 1), date(2026, 10, 31), None)
    stock_row = [r for r in result.stock if r.kode == "egg"][0]
    assert stock_row.opening == Decimal("100")
    assert stock_row.in_qty == Decimal("50")
    assert stock_row.out_qty == Decimal("30")
    assert stock_row.adj == Decimal("5")
    assert stock_row.closing == Decimal("125")


def test_ac_20_filter_kategori(recap_setup):
    d = recap_setup
    _txn(
        d["account"],
        date(2026, 10, 5),
        {
            "flow": "income",
            "category": d["cat_layer"],
            "item": d["item_telur"],
            "amount": Decimal("500000.00"),
            "unit": "kg",
            "period_month": date(2026, 10, 1),
        },
    )
    _txn(
        d["account"],
        date(2026, 10, 6),
        {
            "flow": "expense",
            "category": d["cat_doc"],
            "item": d["item_pakan"],
            "amount": Decimal("200000.00"),
            "unit": "kg",
            "period_month": date(2026, 10, 1),
        },
    )
    result = daily_recap(date(2026, 10, 1), date(2026, 10, 31), d["cat_doc"].pk)
    total = sum(r.amount for r in result.summary if r.key == "pengeluaran")
    assert total == Decimal("200000.00")


def test_ac_21_yearly_bulan_punya_nilai_datar(recap_setup):
    """BUG-001: entri bulan tahunan menyediakan nilai datar untuk tabel per bulan."""
    d = recap_setup
    _txn(
        d["account"],
        date(2026, 10, 5),
        {
            "flow": "income",
            "category": d["cat_layer"],
            "item": d["item_telur"],
            "amount": Decimal("500000.00"),
            "unit": "kg",
            "period_month": date(2026, 10, 1),
        },
    )
    _txn(
        d["account"],
        date(2026, 10, 6),
        {
            "flow": "expense",
            "category": d["cat_layer"],
            "item": d["item_pakan"],
            "amount": Decimal("200000.00"),
            "unit": "kg",
            "period_month": date(2026, 10, 1),
        },
    )

    result = yearly_recap(2026)
    oktober = next(m for m in result.months if m["bulan"] == date(2026, 10, 1))

    assert oktober["month_label"] == "Oktober 2026"
    assert oktober["label"] == "Oktober 2026"
    assert oktober["pemasukan"] == Decimal("500000.00")
    assert oktober["pengeluaran"] == Decimal("200000.00")
    assert oktober["mutasi_nonoperasional"] == Decimal("0")
    assert oktober["selisih"] == Decimal("300000.00")

    # Kontrak lama tetap utuh.
    assert len(oktober["summary"]) == 4
    assert {row["key"]: row["amount"] for row in oktober["summary"]} == {
        "pemasukan": Decimal("500000.00"),
        "pengeluaran": Decimal("200000.00"),
        "mutasi_nonoperasional": Decimal("0"),
        "selisih": Decimal("300000.00"),
    }
    assert any(k["kode"] == "LAYER" for k in oktober["kategori"])

    # Bulan tanpa transaksi tetap nol, bukan hilang.
    desember = next(m for m in result.months if m["bulan"] == date(2026, 12, 1))
    assert desember["pemasukan"] == Decimal("0")
    assert desember["selisih"] == Decimal("0")
