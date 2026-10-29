"""Test layar Stok & ambang minimum (S-16, AC-06.1…06.4)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from audit.models import AuditLog
from core import messages
from core.errors import DomainError
from core.models import PeriodLock
from master.models import StockItem
from master.services.seed import ensure_master_data
from stock.queries import stock_overview
from stock.services.settings import update_stock_settings
from tests.factories import make_movement


@pytest.fixture
def seeded(completed_setup):
    ensure_master_data(
        stock={
            "feed": {"qty": Decimal("1500"), "min_threshold": None},
            "egg": {"qty": Decimal("0"), "min_threshold": None},
            "manure": {"qty": Decimal("30"), "min_threshold": None},
        }
    )
    return completed_setup


@pytest.fixture
def auth_client(client, seeded):
    client.force_login(seeded)
    return client


def _cards():
    return {card.stock_item.code: card for card in stock_overview()}


def _post_stock(client, code: str, *, opening: str, threshold: str = ""):
    return client.post(
        reverse("stock:update", args=[code]),
        {"opening_qty": opening, "min_threshold": threshold},
    )


@pytest.mark.django_db
def test_ac_06_1_ambang_minimum_memunculkan_badge_menipis(auth_client):
    response = _post_stock(auth_client, "feed", opening="1.500", threshold="2.000")

    assert response.status_code == 302
    feed = StockItem.objects.get(code="feed")
    assert feed.min_threshold == Decimal("2000.000")

    card = _cards()["feed"]
    assert card.current_qty == Decimal("1500.000")
    assert card.is_low is True

    page = auth_client.get(reverse("stock:settings"))
    assert "Menipis" in page.content.decode()

    audit = AuditLog.objects.get(entity="stock_item", action="update", entity_id=feed.pk)
    assert audit.after["min_threshold"] == "2000.000"

    assert _post_stock(auth_client, "feed", opening="1.500", threshold="1.000").status_code == 302
    assert _cards()["feed"].is_low is False
    assert "Menipis" not in auth_client.get(reverse("stock:settings")).content.decode()


@pytest.mark.django_db
def test_ac_06_2_stok_awal_telur_bisa_diubah_tanpa_movement(auth_client):
    response = _post_stock(auth_client, "egg", opening="25")

    assert response.status_code == 302
    egg = StockItem.objects.get(code="egg")
    assert egg.opening_qty == Decimal("25.000")
    assert _cards()["egg"].current_qty == Decimal("25.000")

    audit = AuditLog.objects.get(entity="stock_item", action="update", entity_id=egg.pk)
    assert audit.after["opening_qty"] == "25.000"


@pytest.mark.django_db
def test_ac_06_3_stok_awal_terkunci_setelah_movement_pertama(auth_client, seeded):
    feed = StockItem.objects.get(code="feed")
    make_movement(
        stock_item=feed,
        value_date=date(2026, 10, 1),
        direction="in",
        qty=Decimal("5.000"),
    )

    page = auth_client.get(reverse("stock:settings"))
    body = page.content.decode()
    assert messages.stock_opening_locked(date(2026, 10, 1)) in body

    forms = {card.stock_item.code: form for card, form in page.context["cards"]}
    assert forms["feed"].fields["opening_qty"].disabled is True

    response = _post_stock(auth_client, "feed", opening="999")
    assert response.status_code == 302
    feed.refresh_from_db()
    assert feed.opening_qty == Decimal("1500.000")

    with pytest.raises(DomainError) as exc:
        update_stock_settings(
            stock_item_id=feed.pk,
            opening_qty=Decimal("999"),
            min_threshold=feed.min_threshold,
            actor=seeded,
        )
    assert exc.value.message == messages.stock_opening_locked(date(2026, 10, 1))


@pytest.mark.django_db
def test_stok_awal_dua_jenis_independen(auth_client):
    feed = StockItem.objects.get(code="feed")
    make_movement(stock_item=feed, value_date=date(2026, 10, 1), direction="in")

    assert _cards()["feed"].is_locked is True
    assert _cards()["egg"].is_locked is False

    response = _post_stock(auth_client, "egg", opening="25")

    assert response.status_code == 302
    assert StockItem.objects.get(code="egg").opening_qty == Decimal("25.000")
    assert StockItem.objects.get(code="feed").opening_qty == Decimal("1500.000")


@pytest.mark.django_db
def test_stok_saat_ini_hanya_menghitung_movement_aktif(seeded):
    egg = StockItem.objects.get(code="egg")
    egg.opening_qty = Decimal("10")
    egg.min_threshold = Decimal("14")
    egg.save(update_fields=["opening_qty", "min_threshold", "updated_at"])

    make_movement(stock_item=egg, direction="in", qty=Decimal("5"))
    make_movement(stock_item=egg, direction="out", qty=Decimal("2"))
    dihapus = make_movement(stock_item=egg, direction="in", qty=Decimal("7"))
    dihapus.soft_delete()

    card = _cards()["egg"]
    assert card.current_qty == Decimal("13.000")
    assert card.is_low is True


@pytest.mark.django_db
def test_ambang_minimum_negatif_ditolak(auth_client):
    response = _post_stock(auth_client, "feed", opening="1.500", threshold="-1")

    assert response.status_code == 200
    assert "harus lebih dari 0" in response.content.decode()
    assert StockItem.objects.get(code="feed").min_threshold is None


@pytest.mark.django_db
def test_ambang_tetap_bisa_diubah_saat_periode_terkunci(auth_client):
    PeriodLock.objects.create(period=date(2026, 10, 1), is_locked=True)

    response = _post_stock(auth_client, "feed", opening="1.500", threshold="2.000")

    assert response.status_code == 302
    assert StockItem.objects.get(code="feed").min_threshold == Decimal("2000.000")


@pytest.mark.django_db
def test_tidak_ada_kontrol_ubah_nama_atau_satuan(auth_client):
    body = auth_client.get(reverse("stock:settings")).content.decode()

    assert 'name="unit"' not in body
    assert 'name="stock_name"' not in body
    assert 'name="name"' not in body
    assert "Satuan: kg · tetap" in body
