from __future__ import annotations

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


@pytest.mark.django_db
def test_period_lock_action_uses_consistent_workspace_layout(completed_setup, client):
    client.force_login(completed_setup)

    response = client.get(reverse("period_lock_action", args=["2026-10"]))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'class="workspace-page stock-adjustment-page period-lock-page"' in content
    assert "Status periode" in content
    assert "Pastikan transaksi, rekap, dan stok bulan ini sudah diperiksa" in content
