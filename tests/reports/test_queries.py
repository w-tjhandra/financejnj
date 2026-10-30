"""Test query rekap 4 periode (FR-16…FR-26): AC-16.x–20.x."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from ledger.models import Account, Transaction
from master.models import Category, Item, StockItem
from master.services.seed import ensure_master_data
from reports.queries import daily_recap
from tests.factories import make_movement


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

    item_telur = Item.objects.get(code="egg_sales")
    item_pakan = Item.objects.get(code="feed")
    item_afkir = Item.objects.get(code="afkir_sales")
    item_gaji = Item.objects.get(code="salary")
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


def _txn(d, account, data):
    return Transaction.objects.create(
        date=d,
        account=account,
        **data,
    )


def test_ac_16_empat_baris_d2(recap_setup):
    d = recap_setup
    _txn(
        date(2026, 10, 5),
        d["account"],
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
        date(2026, 10, 6),
        d["account"],
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
        date(2026, 10, 5),
        d["account"],
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
        date(2026, 10, 6),
        d["account"],
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
        date(2026, 8, 20),
        d["account"],
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
    egg = StockItem.objects.get(code="egg")
    egg.opening_qty = Decimal("100")
    egg.save()
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
        date(2026, 10, 5),
        d["account"],
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
        date(2026, 10, 6),
        d["account"],
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
