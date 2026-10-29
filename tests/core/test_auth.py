"""Auth hardening: rate limit, redirect aman, sesi, logout, ganti sandi (FR-01)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.conf import settings
from django.core.cache import cache
from django.test import Client, override_settings
from django.urls import reverse

from core import messages as core_messages
from tests.conftest import TEST_PASSWORD

NEW_PASSWORD = "KandangBaru2026"


@pytest.fixture(autouse=True)
def _clear_login_cache():
    cache.clear()
    yield
    cache.clear()


def post_login(client, *, username="pemilik", password=TEST_PASSWORD, next_url=None, **extra):
    data = {"username": username, "password": password}
    if next_url is not None:
        data["next"] = next_url
    return client.post(reverse("login"), data, **extra)


def post_password_change(
    client,
    *,
    old_password=TEST_PASSWORD,
    new_password=NEW_PASSWORD,
    confirm=None,
):
    return client.post(
        reverse("account_settings"),
        {
            "old_password": old_password,
            "new_password1": new_password,
            "new_password2": new_password if confirm is None else confirm,
        },
    )


# --- Login ----------------------------------------------------------------


@pytest.mark.django_db
def test_login_sukses_merotasi_session_dan_memakai_next_internal(client, completed_setup):
    client.get(reverse("login"))
    session = client.session
    session["seed"] = "nilai"
    session.save()
    old_session_key = session.session_key

    response = post_login(client, next_url="/pengaturan/akun")

    assert response.status_code == 302
    assert response.url == "/pengaturan/akun"
    assert client.session.session_key != old_session_key
    assert client.session.get("_auth_user_id") == str(completed_setup.pk)


@pytest.mark.django_db
def test_login_gagal_memakai_pesan_generik_untuk_username_apa_pun(client, completed_setup):
    salah_username = post_login(client, username="tidak-ada", password="salah-sekali")
    salah_password = post_login(client, password="salah-sekali")

    for response in (salah_username, salah_password):
        assert response.status_code == 200
        body = response.content.decode()
        assert "Username atau kata sandi salah." in body
        assert "Akun ini tidak aktif" not in body


@pytest.mark.django_db
def test_next_eksternal_ditolak_dan_kembali_ke_beranda(client, completed_setup):
    for external in (
        "https://evil.example/masuk",
        "//evil.example/masuk",
        "/\\evil.example",
        "http://testserver/pengaturan/akun",
    ):
        cache.clear()
        response = post_login(client, next_url=external)
        assert response.status_code == 302
        assert response.url == "/"


@pytest.mark.django_db
def test_login_terkunci_setelah_lima_kegagalan(client, completed_setup):
    for _ in range(settings.LOGIN_MAX_ATTEMPTS):
        response = post_login(client, password="salah-sekali")
        assert response.status_code == 200

    locked = post_login(client, password=TEST_PASSWORD)

    assert locked.status_code == 200
    assert core_messages.RATE_LIMITED in locked.content.decode()
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_rate_limit_terpisah_per_ip(client, completed_setup):
    for _ in range(settings.LOGIN_MAX_ATTEMPTS):
        post_login(client, password="salah-sekali")

    response = post_login(client, password=TEST_PASSWORD, REMOTE_ADDR="10.0.0.9")

    assert response.status_code == 302
    assert client.session.get("_auth_user_id") == str(completed_setup.pk)


@override_settings(LOGIN_MAX_ATTEMPTS=5, LOGIN_LOCKOUT_SECONDS=900)
@pytest.mark.django_db
def test_lockout_pulih_setelah_window_berakhir(client, completed_setup):
    now = [1_700_000_000.0]

    def clock():
        return now[0]

    with patch("time.time", side_effect=clock):
        for attempt in range(5):
            response = post_login(client, password="salah-sekali")
            assert response.status_code == 200
            if attempt == 4:
                assert core_messages.RATE_LIMITED not in response.content.decode()

        assert (
            core_messages.RATE_LIMITED
            in post_login(client, password=TEST_PASSWORD).content.decode()
        )

        now[0] += 901
        response = post_login(client, password=TEST_PASSWORD)

    assert response.status_code == 302
    assert client.session.get("_auth_user_id") == str(completed_setup.pk)


@pytest.mark.django_db
def test_kegagalan_direset_setelah_login_sukses(client, completed_setup):
    for _ in range(4):
        post_login(client, password="salah-sekali")

    assert post_login(client, password=TEST_PASSWORD).status_code == 302
    client.post(reverse("logout"))

    for _ in range(4):
        post_login(client, password="salah-sekali")

    response = post_login(client, password=TEST_PASSWORD)

    assert response.status_code == 302
    assert client.session.get("_auth_user_id") == str(completed_setup.pk)


# --- Sesi & logout --------------------------------------------------------


def test_konfigurasi_sesi_sesuai_br_16():
    assert settings.SESSION_COOKIE_AGE == 12 * 60 * 60
    assert settings.SESSION_SAVE_EVERY_REQUEST is True
    assert settings.SESSION_EXPIRE_AT_BROWSER_CLOSE is False
    assert settings.SESSION_COOKIE_HTTPONLY is True
    assert settings.SESSION_COOKIE_SAMESITE == "Lax"


@pytest.mark.django_db
def test_logout_get_ditolak(client, completed_setup):
    client.force_login(completed_setup)

    response = client.get(reverse("logout"))

    assert response.status_code == 405
    assert client.session.get("_auth_user_id") == str(completed_setup.pk)


@pytest.mark.django_db
def test_logout_post_tanpa_csrf_ditolak(completed_setup):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(completed_setup)

    response = csrf_client.post(reverse("logout"))

    assert response.status_code == 403
    assert csrf_client.session.get("_auth_user_id") == str(completed_setup.pk)


# --- Ganti kata sandi -----------------------------------------------------


@pytest.mark.django_db
def test_halaman_ganti_sandi_wajib_login(client, completed_setup):
    response = client.get(reverse("account_settings"))

    assert response.status_code == 302
    assert response.url.startswith("/masuk?next=")


@pytest.mark.django_db
def test_ganti_sandi_sukses_tetap_login_dan_menampilkan_pesan(client, completed_setup):
    client.force_login(completed_setup)

    response = post_password_change(client)
    assert response.status_code == 302
    assert response.url == reverse("account_settings")

    completed_setup.refresh_from_db()
    assert completed_setup.check_password(NEW_PASSWORD)

    followed = client.get(reverse("dashboard"))
    assert followed.status_code == 200
    assert core_messages.PASSWORD_CHANGED in followed.content.decode()


@pytest.mark.django_db
def test_ganti_sandi_ditolak_bila_sandi_lama_salah(client, completed_setup):
    client.force_login(completed_setup)

    response = post_password_change(client, old_password="salah-sekali")

    assert response.status_code == 200
    assert core_messages.OLD_PASSWORD_INCORRECT in response.content.decode()
    completed_setup.refresh_from_db()
    assert completed_setup.check_password(TEST_PASSWORD)


@pytest.mark.django_db
def test_ganti_sandi_ditolak_bila_sama_dengan_username(client, completed_setup):
    client.force_login(completed_setup)

    response = post_password_change(client, new_password="Pemilik")

    assert response.status_code == 200
    assert core_messages.PASSWORD_SAME_AS_USERNAME in response.content.decode()


@pytest.mark.django_db
def test_ganti_sandi_ditolak_bila_kurang_dari_sepuluh_karakter(client, completed_setup):
    client.force_login(completed_setup)

    response = post_password_change(client, new_password="pendek")

    assert response.status_code == 200
    assert "10 karakter" in response.content.decode()


@pytest.mark.django_db
def test_ganti_sandi_ditolak_bila_konfirmasi_tidak_sama(client, completed_setup):
    client.force_login(completed_setup)

    response = post_password_change(client, confirm="KandangLain2026")

    assert response.status_code == 200
    assert core_messages.PASSWORD_MISMATCH in response.content.decode()
