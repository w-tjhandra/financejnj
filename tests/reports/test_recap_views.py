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
def test_dashboard_menampilkan_ringkasan_dan_data_infografis(completed_setup, client):
    client.force_login(completed_setup)
    today = today_wib()
    account = Account.current()
    account.opening_balance_date = today
    account.save(update_fields=["opening_balance_date"])
    category = make_category(code="UMUM", name="Operasional")
    income_item = make_item(name="Penjualan", flow="income", default_category=category)
    expense_item = make_item(name="Pakan", flow="expense", default_category=category)
    make_transaction(
        item=income_item,
        account=account,
        value_date=today,
        amount=Decimal("1000000.00"),
    )
    make_transaction(
        item=expense_item,
        category=category,
        account=account,
        value_date=today,
        amount=Decimal("250000.00"),
    )

    response = client.get(reverse("dashboard"))

    assert response.status_code == 200
    assert response.context["dashboard_income_display"] == "1.000.000,00"
    assert response.context["dashboard_expense_display"] == "250.000,00"
    assert response.context["dashboard_net_display"] == "750.000,00"
    assert response.context["cashflow_chart"]["income"][today.day - 1] == 1000000
    assert response.context["cashflow_chart"]["expense"][today.day - 1] == 250000
    assert response.context["category_chart"] == {
        "labels": ["Operasional"],
        "values": [250000],
    }
    content = response.content.decode()
    assert 'id="dashboard-cashflow-chart"' in content
    assert 'id="dashboard-category-chart"' in content
    assert "dashboard.js" in content
    assert "Catat aktivitas hari ini" not in content
    assert "Mulai dari sini" not in content
    assert "Aksi cepat" not in content


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
