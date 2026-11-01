"""Integration test setup wizard, guard, dan seed master (FR-02, FR-07)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from audit.models import AuditLog
from core.models import CompanyProfile
from core.services.setup_state import SETUP_DRAFT_KEY
from core.utils.dates import today_wib
from ledger.models import Account, Transaction
from master.models import Category, Item, StockItem
from master.services.seed import ensure_master_data
from onboarding.errors import SetupIncomplete
from onboarding.services.finalize import finalize_setup
from stock.models import StockMovement

PASSWORD = "RahasiaKandang2026"
TODAY = today_wib()
START = TODAY - timedelta(days=30)
START_ISO = START.isoformat()
TOMORROW_ISO = (TODAY + timedelta(days=1)).isoformat()
BEFORE_START_ISO = (START - timedelta(days=1)).isoformat()


def post_account(client, *, username="pemilik", password=PASSWORD, confirm=None, **extra):
    if confirm is None:
        confirm = password
    data = {
        "username": username,
        "first_name": extra.pop("first_name", "Pemilik"),
        "password": password,
        "password_confirm": confirm,
        **extra,
    }
    return client.post(reverse("setup_account"), data)


def post_profile(client, *, name="Telur Jaya Farm", start=START_ISO, app_start=None):
    return client.post(
        reverse("setup_profile"),
        {
            "name": name,
            "business_start_date": start,
            "application_start_date": app_start or TODAY.isoformat(),
        },
    )


def post_balance(client, *, amount="250.000.000", value_date=START_ISO):
    return client.post(
        reverse("setup_balance"),
        {
            "opening_balance_cash": amount,
            "opening_balance_bca": "0",
            "opening_balance_mandiri": "0",
            "opening_balance_ibk": "0",
            "opening_balance_date": value_date,
        },
    )


def post_stock(
    client,
    *,
    feed="1.500",
    egg="0",
    manure="30",
    feed_min="2.000",
    egg_min="100",
    manure_min="50",
):
    return client.post(
        reverse("setup_stock"),
        {
            "feed_qty": feed,
            "feed_min": feed_min,
            "egg_qty": egg,
            "egg_min": egg_min,
            "manure_qty": manure,
            "manure_min": manure_min,
        },
    )


def walk_to_review(client):
    assert post_account(client).status_code == 302
    assert post_profile(client).status_code == 302
    assert post_balance(client).status_code == 302
    assert post_stock(client).status_code == 302


def assert_master_seeded():
    assert Category.objects.count() == 4
    assert set(Category.objects.values_list("code", flat=True)) == {
        "LAYER",
        "AFKIR",
        "DOC",
        "UMUM",
    }
    afkir = Category.objects.get(code="AFKIR")
    assert afkir.name == "AYAM AFKIR"
    assert afkir.parent.code == "LAYER"
    assert all(Category.objects.values_list("is_system", flat=True))

    assert Item.objects.count() == 10
    correction = Item.objects.get(code="opening_correction")
    assert correction.name == "Koreksi Saldo Awal"
    assert correction.is_system is True
    assert correction.stock_item is None

    assert StockItem.objects.count() == 3
    stock = {item.code: item for item in StockItem.objects.all()}
    assert stock["feed"].opening_qty == Decimal("1500.000")
    assert stock["feed"].min_threshold == Decimal("2000.000")
    assert stock["egg"].opening_qty == Decimal("0.000")
    assert stock["manure"].opening_qty == Decimal("30.000")
    assert stock["feed"].unit == "kg"
    assert stock["egg"].unit == "kg"
    assert stock["manure"].unit == "karung"


# --- AC-02.1 / AC-02.2 -----------------------------------------------------


@pytest.mark.django_db
def test_instalasi_baru_membuka_akar_dialihkan_ke_langkah_1(client):
    response = client.get(reverse("dashboard"))

    assert response.status_code == 302
    assert response.url == "/setup/akun"


@pytest.mark.django_db
def test_langkah_1_dapat_dibuka_tanpa_user(client):
    response = client.get("/setup/akun")

    assert response.status_code == 200
    body = response.content.decode()
    assert "Buat akun pemilik" in body
    assert "Langkah 1 dari 5" in body


@pytest.mark.django_db
def test_password_pendek_ditolak_dan_user_tidak_dibuat(client):
    response = post_account(client, password="pendek")

    assert response.status_code == 200
    assert "Password minimal 10 karakter" in response.content.decode()
    assert get_user_model().objects.count() == 0


@pytest.mark.django_db
def test_password_konfirmasi_berbeda_ditolak(client):
    response = post_account(client, confirm="RahasiaKandang2027")

    assert response.status_code == 200
    assert "Konfirmasi password tidak sama" in response.content.decode()
    assert get_user_model().objects.count() == 0


@pytest.mark.django_db
def test_username_tidak_valid_ditolak(client):
    response = post_account(client, username="pemilik telur")

    assert response.status_code == 200
    assert "Username 3–30 karakter" in response.content.decode()
    assert get_user_model().objects.count() == 0


@pytest.mark.django_db
def test_langkah_1_membuat_user_dan_login(client):
    response = post_account(client)

    assert response.status_code == 302
    assert response.url == "/setup/profil"
    user = get_user_model().objects.get()
    assert user.username == "pemilik"
    assert user.check_password(PASSWORD)
    assert user.first_name == "Pemilik"
    assert client.session["_auth_user_id"] == str(user.pk)


@pytest.mark.django_db
def test_tanggal_mulai_aplikasi_disimpan_terpisah_dari_tanggal_mulai_usaha(client):
    post_account(client)

    response = post_profile(client, start=START_ISO, app_start="2026-11-01")

    assert response.status_code == 302
    profile = CompanyProfile.objects.get()
    assert profile.business_start_date == START
    assert profile.application_start_date.isoformat() == "2026-11-01"


# --- AC-02.6 / guard -------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/", "/transaksi", "/rekap/bulanan"])
def test_semua_url_dialihkan_ke_langkah_belum_selesai(client, path):
    post_account(client)

    response = client.get(path)

    assert response.status_code == 302
    assert response.url == "/setup/profil"


@pytest.mark.django_db
def test_post_ke_url_lain_ditolak_403_saat_setup_belum_selesai(client):
    post_account(client)

    response = client.post(reverse("dashboard"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_langkah_masa_depan_dialihkan_ke_langkah_aktif(client):
    post_account(client)

    response = client.get(reverse("setup_balance"))

    assert response.status_code == 302
    assert response.url == "/setup/profil"


@pytest.mark.django_db
def test_akses_akar_setelah_langkah_1_tetap_redirect(client):
    post_account(client)

    assert client.get(reverse("dashboard")).url == "/setup/profil"


# --- AC-02.5 resume setelah logout ----------------------------------------


@pytest.mark.django_db
def test_resume_setelah_logout_melanjutkan_langkah_aktif(client):
    post_account(client)
    post_profile(client)

    client.post(reverse("logout"))
    login = client.post(reverse("login"), {"username": "pemilik", "password": PASSWORD})
    assert login.status_code == 302

    response = client.get(reverse("setup"))
    assert response.status_code == 302
    assert response.url == "/setup/saldo"

    page = client.get(reverse("setup_balance"))
    assert page.status_code == 200
    assert "Telur Jaya Farm" not in page.content.decode()  # profil tidak diulang
    assert f'value="{START_ISO}"' in page.content.decode()


# --- Langkah 2 & 3: validasi tanggal --------------------------------------


@pytest.mark.django_db
def test_nama_usaha_wajib(client):
    post_account(client)

    response = post_profile(client, name="   ")

    assert response.status_code == 200
    assert "Nama usaha wajib diisi" in response.content.decode()
    assert CompanyProfile.objects.count() == 0


@pytest.mark.django_db
def test_tanggal_mulai_usaha_masa_depan_ditolak(client):
    post_account(client)

    response = post_profile(client, start=TOMORROW_ISO)

    assert response.status_code == 200
    assert "Tanggal mulai usaha tidak boleh melebihi hari ini" in response.content.decode()
    assert CompanyProfile.objects.count() == 0


@pytest.mark.django_db
def test_tanggal_saldo_masa_depan_ditolak(client):
    post_account(client)
    post_profile(client)

    response = post_balance(client, value_date=TOMORROW_ISO)

    assert response.status_code == 200
    assert "Tanggal saldo awal tidak boleh melebihi hari ini" in response.content.decode()
    assert Account.objects.count() == 0


@pytest.mark.django_db
def test_tanggal_saldo_sebelum_mulai_usaha_ditolak(client):
    post_account(client)
    post_profile(client)

    response = post_balance(client, value_date=BEFORE_START_ISO)

    assert response.status_code == 200
    assert "tidak boleh sebelum tanggal mulai usaha" in response.content.decode()
    assert Account.objects.count() == 0


@pytest.mark.django_db
def test_saldo_awal_tersimpan(client):
    post_account(client)
    post_profile(client)

    response = post_balance(client)

    assert response.status_code == 302
    assert response.url == "/setup/stok"
    account = Account.objects.get(code="cash")
    assert account.opening_balance == Decimal("250000000.00")
    assert account.opening_balance_date == START
    assert account.currency == "IDR"
    assert Account.objects.count() == 4
    assert Account.objects.get(code="bca").opening_balance == Decimal("0")
    assert Account.objects.get(code="mandiri").opening_balance == Decimal("0")
    assert Account.objects.get(code="ibk").opening_balance == Decimal("0")


# --- Langkah 4: draft session ---------------------------------------------


@pytest.mark.django_db
def test_stok_awal_disimpan_di_session_bukan_db(client):
    post_account(client)
    post_profile(client)
    post_balance(client)

    response = post_stock(client)

    assert response.status_code == 302
    assert response.url == "/setup/ringkasan"
    draft = client.session[SETUP_DRAFT_KEY]["stock"]
    assert Decimal(draft["feed"]["qty"]) == Decimal("1500.000")
    assert Decimal(draft["manure"]["qty"]) == Decimal("30.000")
    assert Category.objects.count() == 0
    assert Item.objects.count() == 0
    assert StockItem.objects.count() == 0


@pytest.mark.django_db
def test_tidak_ada_data_bisnis_sebelum_finalisasi(client):
    walk_to_review(client)

    assert Account.objects.count() == 4
    assert CompanyProfile.objects.count() == 1
    assert Category.objects.count() == 0
    assert Item.objects.count() == 0
    assert StockItem.objects.count() == 0
    assert Transaction.objects.count() == 0
    assert StockMovement.objects.count() == 0


@pytest.mark.django_db
def test_ringkasan_menampilkan_angka_terformat(client):
    walk_to_review(client)

    response = client.get(reverse("setup_review"))

    body = response.content.decode()
    assert response.status_code == 200
    assert "Telur Jaya Farm" in body
    assert "Rp 250.000.000,00" in body
    assert "1.500 kg" in body
    assert "30 karung" in body


# --- AC-02.3 finalisasi ----------------------------------------------------


@pytest.mark.django_db
def test_finalisasi_membuat_semua_data_master(client):
    walk_to_review(client)

    response = client.post(reverse("setup_review"), follow=True)

    assert response.status_code == 200
    assert response.redirect_chain[-1][0] == "/"
    assert "Setup selesai. Selamat bekerja." in response.content.decode()

    profile = CompanyProfile.get_solo()
    assert profile.setup_completed is True
    assert Account.objects.count() == 4
    assert Account.objects.get(code="cash").opening_balance == Decimal("250000000.00")
    assert_master_seeded()

    assert not AuditLog.objects.filter(entity="company_profile").exists()
    assert SETUP_DRAFT_KEY not in client.session


@pytest.mark.django_db
def test_finalisasi_idempoten_tidak_menggandakan_data(client):
    walk_to_review(client)
    user = get_user_model().objects.get()
    stock_draft = client.session[SETUP_DRAFT_KEY]["stock"]

    first = finalize_setup(actor=user, stock_draft=stock_draft)
    second = finalize_setup(actor=user, stock_draft=stock_draft)

    assert first.created is True
    assert second.created is False
    assert Category.objects.count() == 4
    assert Item.objects.count() == 10
    assert StockItem.objects.count() == 3
    assert not AuditLog.objects.filter(entity="company_profile").exists()


@pytest.mark.django_db
def test_finalisasi_tanpa_draft_stok_ditolak_dan_tidak_setengah_jadi(client):
    post_account(client)
    post_profile(client)
    post_balance(client)
    user = get_user_model().objects.get()

    with pytest.raises(SetupIncomplete) as exc:
        finalize_setup(actor=user, stock_draft=None)

    assert exc.value.step == 4
    assert CompanyProfile.get_solo().setup_completed is False
    assert Category.objects.count() == 0
    assert Item.objects.count() == 0
    assert StockItem.objects.count() == 0


@pytest.mark.django_db
def test_seed_master_idempoten():
    ensure_master_data(
        stock={
            "feed": {"qty": Decimal("1500.000"), "min_threshold": Decimal("2000.000")},
            "egg": {"qty": Decimal("0.000"), "min_threshold": None},
            "manure": {"qty": Decimal("30.000"), "min_threshold": Decimal("50.000")},
        }
    )
    ensure_master_data()

    assert_master_seeded()


# --- AC-02.4 setelah selesai ----------------------------------------------


@pytest.mark.django_db
def test_setup_setelah_selesai_404_untuk_user_login(client):
    walk_to_review(client)
    client.post(reverse("setup_review"))

    assert client.get(reverse("setup")).status_code == 404
    assert client.get(reverse("setup_account")).status_code == 404


@pytest.mark.django_db
def test_setup_setelah_selesai_dialihkan_ke_login_untuk_anonim(client, completed_setup):
    from django.test import Client

    anon = Client()

    response = anon.get(reverse("setup"))

    assert response.status_code == 302
    assert response.url == reverse("login")


# --- Setelah selesai: aplikasi normal -------------------------------------


@pytest.mark.django_db
def test_dashboard_normal_setelah_setup_selesai(client, completed_setup):
    client.force_login(completed_setup)

    response = client.get(reverse("dashboard"))

    assert response.status_code == 200
    assert "Dashboard" in response.content.decode()
