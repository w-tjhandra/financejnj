"""Test view rekap 4 periode (S-10…S-13)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from core.utils.dates import today_wib
from ledger.models import Account, Transaction
from tests.factories import make_category, make_item, make_stock_item, make_transaction


@pytest.mark.django_db
def test_ac_16_harian_200(completed_setup, client):
    client.force_login(completed_setup)
    Account.objects.create(
        name="Kas",
        type="cash",
        currency="IDR",
        opening_balance=Decimal("250000000.00"),
        opening_balance_date=date(2026, 9, 1),
    )
    cat_layer = make_category(code="LAYER", name="Ayam Petelur")
    item_telur = make_item(
        name="Pendapatan Telur",
        flow="income",
        default_category=cat_layer,
        stock_item=make_stock_item(code="egg", name="Telur", unit="kg", opening_qty=Decimal("0")),
    )
    Transaction.objects.create(
        date=date(2026, 10, 5),
        flow="income",
        category=cat_layer,
        item=item_telur,
        account=Account.objects.first(),
        amount=Decimal("500000.00"),
        qty=Decimal("10"),
        unit="kg",
        period_month=date(2026, 10, 1),
    )
    resp = client.get(reverse("reports:daily_recap"))
    assert resp.status_code == 200
    assert "Ringkasan" in resp.content.decode()


@pytest.mark.django_db
def test_ac_17_mingguan_200(completed_setup, client):
    client.force_login(completed_setup)
    resp = client.get(reverse("reports:weekly_recap"))
    assert resp.status_code == 200
    assert "Ringkasan Minggu" in resp.content.decode()


@pytest.mark.django_db
def test_ac_18_bulanan_200(completed_setup, client):
    client.force_login(completed_setup)
    resp = client.get(reverse("reports:monthly_recap"))
    assert resp.status_code == 200
    assert "Ringkasan Bulan" in resp.content.decode()


@pytest.mark.django_db
def test_ac_19_tahunan_200(completed_setup, client):
    client.force_login(completed_setup)
    resp = client.get(reverse("reports:yearly_recap"))
    assert resp.status_code == 200
    assert "Ringkasan Tahun" in resp.content.decode()


@pytest.mark.django_db
def test_ac_20_dashboard_redirect(completed_setup, client):
    client.force_login(completed_setup)
    resp = client.get(reverse("dashboard"))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_dashboard_chart_hanya_menghitung_transaksi_bulan_ini(completed_setup, client):
    client.force_login(completed_setup)
    today = today_wib()
    category = make_category(code="UMUM")
    income_item = make_item(
        name="Pemasukan dashboard",
        flow="income",
        default_category=category,
    )
    expense_item = make_item(
        name="Pengeluaran dashboard",
        flow="expense",
        default_category=category,
    )
    account = Account.current()
    make_transaction(
        item=income_item,
        account=account,
        value_date=today,
        amount=Decimal("500000.00"),
    )
    make_transaction(
        item=expense_item,
        account=account,
        value_date=today,
        amount=Decimal("125000.00"),
    )

    response = client.get(reverse("dashboard"))

    assert response.status_code == 200
    assert response.context["dashboard_income"] == Decimal("500000.00")
    assert response.context["dashboard_expense"] == Decimal("125000.00")
    assert response.context["dashboard_net"] == Decimal("375000.00")
    assert response.context["cashflow_chart"]["labels"][-1] == f"{today.day:02}"
    assert response.context["cashflow_chart"]["income"][-1] == 500000.0
    assert response.context["cashflow_chart"]["expense"][-1] == 125000.0
    assert response.context["category_chart"] == {
        "labels": ["Umum"],
        "values": [125000.0],
    }


@pytest.mark.django_db
def test_recap_tampilkan_empat_baris(completed_setup, client):
    client.force_login(completed_setup)
    Account.objects.create(
        name="Kas",
        type="cash",
        currency="IDR",
        opening_balance=Decimal("250000000.00"),
        opening_balance_date=date(2026, 9, 1),
    )
    cat_layer = make_category(code="LAYER", name="Ayam Petelur")
    item_telur = make_item(
        name="Pendapatan Telur",
        flow="income",
        default_category=cat_layer,
        stock_item=make_stock_item(code="egg", name="Telur", unit="kg", opening_qty=Decimal("0")),
    )
    Transaction.objects.create(
        date=date(2026, 10, 5),
        flow="income",
        category=cat_layer,
        item=item_telur,
        account=Account.objects.first(),
        amount=Decimal("500000.00"),
        qty=Decimal("10"),
        unit="kg",
        period_month=date(2026, 10, 1),
    )
    resp = client.get(reverse("reports:daily_recap"))
    assert "Pemasukan" in resp.content.decode()
    assert "Pengeluaran" in resp.content.decode()
    assert "Mutasi" in resp.content.decode()
    assert "Selisih" in resp.content.decode()


@pytest.mark.django_db
def test_ac_21_tahunan_tabel_per_bulan_terisi(completed_setup, client):
    """BUG-001: tabel 'Rekap per Bulan' menampilkan nominal, bukan 12 baris kosong."""
    client.force_login(completed_setup)
    account = Account.objects.create(
        name="Kas",
        type="cash",
        currency="IDR",
        opening_balance=Decimal("250000000.00"),
        opening_balance_date=date(2026, 9, 1),
    )
    cat_layer = make_category(code="LAYER", name="Ayam Petelur")
    item_telur = make_item(
        name="Pendapatan Telur",
        flow="income",
        default_category=cat_layer,
        stock_item=make_stock_item(code="egg", name="Telur", unit="kg", opening_qty=Decimal("0")),
    )
    item_pakan = make_item(
        name="Pakan",
        flow="expense",
        default_category=cat_layer,
        stock_item=make_stock_item(code="feed", name="Pakan", unit="kg", opening_qty=Decimal("0")),
    )
    for value_date, flow, item, amount in (
        (date(2026, 10, 5), "income", item_telur, Decimal("500000.00")),
        (date(2026, 10, 6), "expense", item_pakan, Decimal("200000.00")),
    ):
        Transaction.objects.create(
            date=value_date,
            flow=flow,
            category=cat_layer,
            item=item,
            account=account,
            amount=amount,
            period_month=date(2026, 10, 1),
        )

    resp = client.get(reverse("reports:yearly_recap"), {"year": 2026})
    assert resp.status_code == 200
    html = resp.content.decode()
    # Ambil hanya isi section "Rekap per Bulan" agar tidak tertipu nominal di tabel detail.
    month_section = html.split("Rekap per Bulan", 1)[1].split("Detail per Transaksi", 1)[0]
    assert "Oktober 2026" in month_section
    # Nominal bulan Oktober ikut ter-render (bukan 0,00 semua).
    assert "500000" in month_section
    assert "200000" in month_section
    assert "300000" in month_section
