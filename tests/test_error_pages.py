"""Halaman error ramah saat DEBUG=False (FR-01)."""

from __future__ import annotations

import pytest
from django.test import override_settings
from django.urls import reverse


@pytest.mark.django_db
def test_404_menampilkan_halaman_ramah_tanpa_stack_trace(client, completed_setup):
    response = client.get("/alamat-yang-tidak-ada")

    assert response.status_code == 404
    body = response.content.decode()
    assert "Halaman tidak ditemukan" in body
    assert "Traceback" not in body
    assert "Page not found" not in body


@pytest.mark.django_db
def test_403_menampilkan_halaman_ramah(client, completed_setup):
    client.force_login(completed_setup)
    with override_settings(ROOT_URLCONF="tests.urls_error"):
        response = client.get("/forbidden")

    assert response.status_code == 403
    body = response.content.decode()
    assert "Akses ditolak" in body
    assert "Traceback" not in body


@pytest.mark.django_db
def test_500_menampilkan_halaman_ramah_tanpa_stack_trace(client, completed_setup):
    client.force_login(completed_setup)
    client.raise_request_exception = False

    with override_settings(ROOT_URLCONF="tests.urls_error"):
        response = client.get("/boom")

    assert response.status_code == 500
    body = response.content.decode()
    assert "Terjadi kesalahan pada server" in body
    assert "Traceback" not in body
    assert "RuntimeError" not in body
    assert "kegagalan uji" not in body


@pytest.mark.django_db
def test_post_di_luar_setup_tetap_403_saat_setup_belum_selesai(client):
    response = client.post(reverse("dashboard"))

    assert response.status_code == 403
