import pytest
from django.urls import reverse

from core.models import UserPreference


@pytest.mark.django_db
def test_ui_preferences_disimpan_per_akun_dan_diterapkan_ke_semua_halaman(client, completed_setup):
    client.force_login(completed_setup)
    target = reverse("reports:monthly_recap")

    response = client.post(
        reverse("ui_preferences"),
        {"language": "ko", "theme": "dark", "next": target},
    )

    assert response.status_code == 302
    assert response.url == target
    preference = UserPreference.objects.get(user=completed_setup)
    assert preference.language == "ko"
    assert preference.theme == "dark"

    page = client.get(target)
    content = page.content.decode()
    assert page["Content-Language"] == "ko"
    assert '<html lang="ko" data-theme="dark"' in content
    assert "새 거래" in content
    assert "거래" in content
    assert 'id="ui-language" name="language"' in content
    assert 'id="ui-theme" name="theme"' in content


@pytest.mark.django_db
def test_ui_preferences_bahasa_inggris_dan_default_indonesia(client, completed_setup):
    client.force_login(completed_setup)
    url = reverse("ui_preferences")

    response = client.post(
        url,
        {"language": "en", "theme": "light", "next": reverse("dashboard")},
    )

    assert response.status_code == 302
    page = client.get(reverse("dashboard"))
    content = page.content.decode()
    assert page["Content-Language"] == "en"
    assert '<html lang="en" data-theme="light"' in content
    assert "New transaction" in content
    assert "Transactions" in content

    client.post(url, {"language": "id", "theme": "light"})
    page = client.get(reverse("dashboard"))
    assert page["Content-Language"] == "id"
    assert "Transaksi baru" in page.content.decode()


@pytest.mark.django_db
def test_ui_preferences_menolak_nilai_tidak_valid(client, completed_setup):
    client.force_login(completed_setup)

    response = client.post(
        reverse("ui_preferences"),
        {"language": "xx", "theme": "neon", "next": reverse("dashboard")},
    )

    assert response.status_code == 302
    assert not UserPreference.objects.filter(user=completed_setup).exists()
    content = client.get(reverse("dashboard")).content.decode()
    assert "Bahasa yang dipilih tidak didukung." in content
