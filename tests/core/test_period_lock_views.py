from __future__ import annotations

from datetime import date

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_period_lock_list_uses_consistent_workspace_layout(completed_setup, client):
    client.force_login(completed_setup)

    response = client.get(reverse("period_lock_list"))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'class="workspace-page report-page period-lock-page"' in content
    assert 'class="card period-lock-rule"' in content
    assert "grid grid-cols-1 gap-4 mb-5 md:grid-cols-3" in content
    assert "Status per bulan" in content
    assert "Kunci secara berurutan" in content
    assert response.context["opening_period"] == date(2026, 9, 1)
    assert len(response.context["months"]) <= 12
    assert "Tampilkan 12 bulan terbaru atau cari bulan lain" in content


@pytest.mark.django_db
def test_period_lock_list_can_search_older_period_and_open_its_recap(completed_setup, client):
    client.force_login(completed_setup)

    response = client.get(reverse("period_lock_list"), {"month": "2026-09"})

    assert response.status_code == 200
    assert len(response.context["months"]) == 1
    assert response.context["months"][0].period == date(2026, 9, 1)
    assert "/rekap/bulanan?month=2026-09-01" in response.content.decode()


@pytest.mark.django_db
def test_period_lock_action_uses_consistent_workspace_layout(completed_setup, client):
    client.force_login(completed_setup)

    response = client.get(reverse("period_lock_action", args=["2026-10"]))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'class="workspace-page stock-adjustment-page period-lock-page"' in content
    assert "Status periode" in content
    assert "Pastikan transaksi, rekap, dan stok bulan ini sudah diperiksa" in content


@pytest.mark.django_db
def test_period_lock_action_rejects_period_before_application_start(completed_setup, client):
    client.force_login(completed_setup)

    response = client.get(reverse("period_lock_action", args=["2026-08"]))

    assert response.status_code == 302
    assert response.url == reverse("period_lock_list")
