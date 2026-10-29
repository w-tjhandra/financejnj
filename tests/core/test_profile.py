"""Test layar Profil Usaha (S-20, AC-03.1…03.3)."""

from __future__ import annotations

from datetime import date

import pytest
from django.urls import reverse

from audit.models import AuditLog
from core import messages
from core.models import CompanyProfile, PeriodLock


@pytest.fixture
def auth_client(client, completed_setup):
    client.force_login(completed_setup)
    return client


def _profile_payload(**overrides):
    data = {
        "name": "Telur Jaya Farm",
        "address": "",
        "phone": "",
        "email": "",
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
def test_ac_03_1_ubah_nama_tersimpan_dan_header_memakai_nama_baru(auth_client):
    response = auth_client.post(
        reverse("profile"),
        _profile_payload(
            name="Telur Jaya Farm Baru",
            address="Jl. Peternakan 1",
            phone="0812-3456-7890",
            email="pemilik@telurjaya.test",
        ),
    )

    assert response.status_code == 302
    profile = CompanyProfile.get_solo()
    assert profile.name == "Telur Jaya Farm Baru"
    assert profile.address == "Jl. Peternakan 1"
    assert profile.phone == "0812-3456-7890"
    assert profile.email == "pemilik@telurjaya.test"

    audit = AuditLog.objects.get(entity="company_profile", action="update")
    assert audit.after["name"] == "Telur Jaya Farm Baru"
    assert audit.before["name"] == "Telur Jaya Farm"

    page = auth_client.get(reverse("dashboard"))
    assert "Telur Jaya Farm Baru" in page.content.decode()


@pytest.mark.django_db
def test_ac_03_2_nama_kosong_ditolak_dan_nilai_lama_tetap(auth_client):
    response = auth_client.post(reverse("profile"), _profile_payload(name="   "))

    assert response.status_code == 200
    assert messages.BUSINESS_NAME_REQUIRED in response.content.decode()
    assert CompanyProfile.get_solo().name == "Telur Jaya Farm"
    assert not AuditLog.objects.filter(entity="company_profile", action="update").exists()


@pytest.mark.django_db
def test_ac_03_3_email_tidak_valid_ditolak(auth_client):
    response = auth_client.post(reverse("profile"), _profile_payload(email="bukan-email"))

    assert response.status_code == 200
    assert messages.EMAIL_INVALID in response.content.decode()
    assert CompanyProfile.get_solo().email == ""


@pytest.mark.django_db
def test_email_kosong_dan_valid_diterima(auth_client):
    assert auth_client.post(reverse("profile"), _profile_payload(email="")).status_code == 302

    response = auth_client.post(reverse("profile"), _profile_payload(email="admin@telurjaya.test"))

    assert response.status_code == 302
    assert CompanyProfile.get_solo().email == "admin@telurjaya.test"


@pytest.mark.django_db
def test_profil_tetap_bisa_disimpan_saat_periode_terkunci(auth_client):
    PeriodLock.objects.create(period=date(2026, 10, 1), is_locked=True)

    response = auth_client.post(
        reverse("profile"), _profile_payload(name="Telur Jaya Saat Terkunci")
    )

    assert response.status_code == 302
    assert CompanyProfile.get_solo().name == "Telur Jaya Saat Terkunci"
