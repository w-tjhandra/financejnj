"""Smoke test fondasi: health, auth, dan routing dasar."""

import json

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_healthz_melaporkan_db_ok(client):
    response = client.get(reverse("healthz"))

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/json")
    assert json.loads(response.content) == {"status": "ok", "db": "ok"}


@pytest.mark.django_db
def test_halaman_login_dapat_dibuka_tanpa_login(client):
    response = client.get(reverse("login"))

    assert response.status_code == 200
    body = response.content.decode()
    assert 'method="post"' in body
    assert "Nama pengguna" in body
    assert "Kata sandi" in body


@pytest.mark.django_db
def test_dashboard_mengalihkan_anonim_ke_login(client):
    response = client.get(reverse("dashboard"))

    assert response.status_code == 302
    assert response.url.startswith("/masuk?next=/")


@pytest.mark.django_db
def test_login_berhasil_membuka_dashboard(client, django_user_model):
    django_user_model.objects.create_user(username="pemilik", password="RahasiaKandang2026")

    response = client.post(
        reverse("login"),
        {"username": "pemilik", "password": "RahasiaKandang2026"},
        follow=True,
    )

    assert response.status_code == 200
    assert response.redirect_chain[-1][0] == "/"
    assert "Dashboard" in response.content.decode()
