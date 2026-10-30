"""Test view rekap 4 periode (S-10…S-13)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from ledger.models import Account, Transaction
from tests.factories import make_category, make_item, make_stock_item


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
