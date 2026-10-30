"""Test view stok harian (S-08) dan penyesuaian (S-09)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from master.models import StockItem
from stock.models import StockMovement
from tests.factories import make_movement


@pytest.mark.django_db
def test_ac_09_1_halaman_input_200(completed_setup, client):
    client.force_login(completed_setup)
    StockItem.objects.create(code="feed", name="Pakan", unit="kg", opening_qty=Decimal("100"))
    StockItem.objects.create(code="egg", name="Telur", unit="kg", opening_qty=Decimal("0"))
    resp = client.get(reverse("stock:daily"))
    assert resp.status_code == 200
    assert "Stok Harian" in resp.content.decode()


@pytest.mark.django_db
def test_ac_09_2_input_produksi_telur(completed_setup, client):
    client.force_login(completed_setup)
    StockItem.objects.create(code="feed", name="Pakan", unit="kg", opening_qty=Decimal("100"))
    egg = StockItem.objects.create(code="egg", name="Telur", unit="kg", opening_qty=Decimal("0"))
    resp = client.post(
        reverse("stock:daily"),
        {"stock_item": egg.pk, "date": "2026-10-01", "qty": "10.000"},
    )
    assert resp.status_code == 302
    assert StockMovement.objects.filter(
        stock_item=egg, direction="in", qty=Decimal("10")
    ).exists()


@pytest.mark.django_db
def test_ac_09_3_input_pemakaian_pakan(completed_setup, client):
    client.force_login(completed_setup)
    feed = StockItem.objects.create(code="feed", name="Pakan", unit="kg", opening_qty=Decimal("100"))
    resp = client.post(
        reverse("stock:daily"),
        {"stock_item": feed.pk, "date": "2026-10-01", "qty": "20.000"},
    )
    assert resp.status_code == 302
    assert StockMovement.objects.filter(
        stock_item=feed, direction="out", qty=Decimal("20")
    ).exists()


@pytest.mark.django_db
def test_ac_09_4_toggle_terhapus(completed_setup, client):
    client.force_login(completed_setup)
    feed = StockItem.objects.create(
        code="feed", name="Pakan", unit="kg", opening_qty=Decimal("100")
    )
    m = make_movement(
        stock_item=feed,
        value_date=date(2026, 10, 1),
        direction="out",
        qty=Decimal("5"),
        source="manual",
    )
    m.soft_delete(actor=completed_setup)
    resp = client.get(reverse("stock:daily") + "?show_deleted=1")
    assert resp.status_code == 200
    assert "Dihapus" in resp.content.decode()


@pytest.mark.django_db
def test_ac_09_5_badge_menipis(completed_setup, client):
    client.force_login(completed_setup)
    feed = StockItem.objects.create(
        code="feed", name="Pakan", unit="kg", opening_qty=Decimal("100")
    )
    feed.min_threshold = Decimal("200")
    feed.save()
    resp = client.get(reverse("stock:daily"))
    assert "Menipis" in resp.content.decode()


@pytest.mark.django_db
def test_ac_14_1_halaman_penyesuaian_200(completed_setup, client):
    client.force_login(completed_setup)
    StockItem.objects.create(code="feed", name="Pakan", unit="kg", opening_qty=Decimal("100"))
    resp = client.get(reverse("stock:adjustment"))
    assert resp.status_code == 200
    assert "Penyesuaian Stok" in resp.content.decode()


@pytest.mark.django_db
def test_ac_14_2_input_penyesuaian_positif(completed_setup, client):
    client.force_login(completed_setup)
    feed = StockItem.objects.create(code="feed", name="Pakan", unit="kg", opening_qty=Decimal("100"))
    resp = client.post(
        reverse("stock:adjustment"),
        {
            "stock_item": feed.pk,
            "date": "2026-10-01",
            "qty": "15.000",
            "reason": "Ditemukan sisa pakan di gudang",
        },
    )
    assert resp.status_code == 302
    assert StockMovement.objects.filter(
        stock_item=feed, source="adjustment", direction="in"
    ).exists()


@pytest.mark.django_db
def test_ac_14_3_alasan_pendek_ditolak(completed_setup, client):
    client.force_login(completed_setup)
    feed = StockItem.objects.create(code="feed", name="Pakan", unit="kg", opening_qty=Decimal("100"))
    resp = client.post(
        reverse("stock:adjustment"),
        {
            "stock_item": feed.pk,
            "date": "2026-10-01",
            "qty": "5.000",
            "reason": "pendek",
        },
    )
    assert resp.status_code == 200
    assert "Alasan minimal 10 karakter" in resp.content.decode()
