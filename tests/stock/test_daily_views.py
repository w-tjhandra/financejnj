"""Test view stok harian (S-08) dan penyesuaian (S-09)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.urls import reverse

from master.models import StockItem
from master.services.seed import ensure_master_data
from stock.models import StockMovement
from stock.services.daily import record_consumption, record_production
from tests.factories import make_movement


@pytest.fixture
def stock_data(completed_setup):
    print("FIXTURE START", flush=True)
    ensure_master_data(
        stock={
            "feed": {"qty": Decimal("100")},
            "egg": {"qty": Decimal("0")},
            "manure": {"qty": Decimal("0")},
        }
    )
    # Force opening_qty to known values since get_or_create doesn't update
    StockItem.objects.filter(code="feed").update(opening_qty=Decimal("100"), min_threshold=None)
    StockItem.objects.filter(code="egg").update(opening_qty=Decimal("0"))
    print("FIXTURE DONE", flush=True)
    return completed_setup


@pytest.fixture(autouse=True)
def _clean_movements():
    """Clean all stock movements before each test to avoid isolation issues."""
    # Hard delete all movements including soft-deleted ones
    StockMovement.all_objects.all().delete()
    yield


def _reset_stock():
    StockItem.objects.filter(code="feed").update(opening_qty=Decimal("100"), min_threshold=None)
    StockItem.objects.filter(code="egg").update(opening_qty=Decimal("0"))


def _add_middleware(request, user):
    """Add session and message middleware to request."""
    request.user = user
    SessionMiddleware(lambda r: None)(request)
    request.session.save()
    MessageMiddleware(lambda r: None)(request)


@pytest.mark.django_db
def test_ac_09_1_halaman_input_200(stock_data, client):
    _reset_stock()
    client.force_login(stock_data)
    resp = client.get(reverse("stock:daily"))
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "Stok Harian" in content
    assert "stock-daily-form" in content
    assert "stock-balance-grid" in content
    assert "Pergerakan harian" in content


@pytest.mark.django_db
def test_ac_09_2_input_produksi_telur(stock_data):
    """Test produksi telur via service (view is thin wrapper,
    service tested in test_daily_service.py)."""
    _reset_stock()
    egg = StockItem.objects.get(code="egg")
    m = record_production(
        stock_item=egg, date=date(2026, 10, 1), qty=Decimal("10"), actor=stock_data
    )
    assert m.direction == "in"
    assert m.qty == Decimal("10.000")
    assert m.source == "manual"
    assert StockMovement.objects.filter(stock_item=egg, direction="in", qty=Decimal("10")).exists()


@pytest.mark.django_db
def test_ac_09_3_input_pemakaian_pakan(stock_data):
    """Test pemakaian pakan via service (view is thin wrapper,
    service tested in test_daily_service.py)."""
    _reset_stock()
    feed = StockItem.objects.get(code="feed")
    m = record_consumption(
        stock_item=feed, date=date(2026, 10, 1), qty=Decimal("20"), actor=stock_data
    )
    assert m.direction == "out"
    assert m.qty == Decimal("20.000")
    assert m.source == "manual"
    assert StockMovement.objects.filter(
        stock_item=feed, direction="out", qty=Decimal("20")
    ).exists()


@pytest.mark.django_db
def test_ac_09_4_toggle_terhapus(stock_data, client):
    _reset_stock()
    client.force_login(stock_data)
    feed = StockItem.objects.get(code="feed")
    m = make_movement(
        stock_item=feed,
        value_date=date(2026, 10, 1),
        direction="out",
        qty=Decimal("5"),
        source="manual",
    )
    m.soft_delete(actor=stock_data)
    resp = client.get(reverse("stock:daily") + "?show_deleted=1")
    assert resp.status_code == 200
    assert "Dihapus" in resp.content.decode()


@pytest.mark.django_db
def test_ac_09_5_badge_menipis(stock_data, client):
    _reset_stock()
    client.force_login(stock_data)
    feed = StockItem.objects.get(code="feed")
    feed.min_threshold = Decimal("200")
    feed.save()
    resp = client.get(reverse("stock:daily"))
    assert "Menipis" in resp.content.decode()


@pytest.mark.django_db
def test_ac_14_1_halaman_penyesuaian_200(stock_data, client):
    _reset_stock()
    client.force_login(stock_data)
    resp = client.get(reverse("stock:adjustment"))
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "Penyesuaian Stok" in content
    assert "stock-adjustment-fields" in content
    assert "Simpan penyesuaian" in content


@pytest.mark.django_db
def test_ac_14_2_input_penyesuaian_positif(stock_data):
    """Test penyesuaian stok via service (view is thin wrapper)."""
    _reset_stock()
    feed = StockItem.objects.get(code="feed")
    from stock.services.daily import adjust_stock

    m = adjust_stock(
        stock_item=feed,
        date=date(2026, 10, 1),
        signed_qty=Decimal("15"),
        reason="Ditemukan sisa pakan di gudang",
        actor=stock_data,
    )
    assert m.direction == "in"
    assert m.qty == Decimal("15.000")
    assert m.source == "adjustment"
    assert StockMovement.objects.filter(
        stock_item=feed, source="adjustment", direction="in"
    ).exists()


@pytest.mark.django_db
def test_ac_14_3_alasan_pendek_ditolak(stock_data, client):
    _reset_stock()
    client.force_login(stock_data)
    feed = StockItem.objects.get(code="feed")
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
