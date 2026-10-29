"""Test layar Saldo Awal (S-17, AC-07.1/07.2/07.6/07.7)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse

from audit.models import AuditLog
from core import messages
from core.utils.dates import today_wib
from ledger.models import Account
from ledger.services.opening import cash_is_locked
from master.models import Item, StockItem
from master.services.seed import ensure_master_data
from tests.factories import make_movement, make_transaction


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


def _post_opening(client, *, amount="300.000.000", value_date="2026-09-01"):
    return client.post(
        reverse("opening_balance"),
        {"opening_balance": amount, "opening_balance_date": value_date},
    )


@pytest.mark.django_db
def test_ac_07_1_saldo_awal_bisa_diubah_sebelum_ada_transaksi(auth_client):
    response = _post_opening(auth_client)

    assert response.status_code == 302
    account = Account.objects.get()
    assert account.opening_balance == Decimal("300000000.00")
    assert account.opening_balance_date == date(2026, 9, 1)

    audit = AuditLog.objects.get(entity="account", action="update")
    assert audit.after["opening_balance"] == "300000000.00"
    assert audit.before["opening_balance"] == "250000000.00"

    page = auth_client.get(reverse("opening_balance"))
    body = page.content.decode()
    assert "Belum terkunci" in body
    assert 'value="300.000.000,00"' in body


@pytest.mark.django_db
def test_ac_07_2_setelah_transaksi_readonly_dan_ada_tombol_koreksi(auth_client, seeded):
    account = Account.objects.get()
    make_transaction(
        item=Item.objects.get(code="medicine"),
        account=account,
        value_date=date(2026, 9, 5),
    )

    page = auth_client.get(reverse("opening_balance"))
    body = page.content.decode()
    assert page.status_code == 200
    assert "Terkunci sejak 05/09/2026" in body
    assert "Koreksi Saldo Awal" in body
    assert 'name="opening_balance"' not in body

    response = _post_opening(auth_client, amount="999.000.000")
    assert response.status_code == 302
    account.refresh_from_db()
    assert account.opening_balance == Decimal("250000000.00")

    placeholder = auth_client.get(reverse("opening_correction"))
    assert placeholder.status_code == 200
    assert "tersedia setelah modul transaksi" in placeholder.content.decode()


@pytest.mark.django_db
def test_ac_07_7_movement_tidak_mengunci_kas_dan_transaksi_terhapus_mengunci(auth_client, seeded):
    make_movement(
        stock_item=StockItem.objects.get(code="feed"),
        value_date=date(2026, 9, 2),
        direction="in",
        qty=Decimal("5.000"),
    )

    assert cash_is_locked() is False
    page = auth_client.get(reverse("opening_balance"))
    assert "Belum terkunci" in page.content.decode()

    assert _post_opening(auth_client, amount="275.000.000").status_code == 302
    assert Account.objects.get().opening_balance == Decimal("275000000.00")

    account = Account.objects.get()
    txn = make_transaction(
        item=Item.objects.get(code="medicine"),
        account=account,
        value_date=date(2026, 9, 5),
    )
    txn.soft_delete(actor=seeded)

    assert cash_is_locked() is True
    page = auth_client.get(reverse("opening_balance"))
    body = page.content.decode()
    assert "Terkunci sejak 05/09/2026" in body
    assert 'name="opening_balance"' not in body


@pytest.mark.django_db
def test_tanggal_saldo_awal_masa_depan_ditolak(auth_client):
    future = today_wib() + timedelta(days=1)

    response = _post_opening(auth_client, value_date=future.isoformat())

    assert response.status_code == 200
    assert messages.DATE_AFTER_TODAY in response.content.decode()
    assert Account.objects.get().opening_balance == Decimal("250000000.00")


@pytest.mark.django_db
def test_tanggal_saldo_awal_sebelum_mulai_usaha_ditolak(auth_client):
    before_start = date(2026, 8, 31)

    response = _post_opening(auth_client, value_date=before_start.isoformat())

    assert response.status_code == 200
    assert "tidak boleh sebelum tanggal mulai usaha" in response.content.decode()
    assert Account.objects.get().opening_balance_date == date(2026, 9, 1)
