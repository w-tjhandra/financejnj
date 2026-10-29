"""Fixture lintas test: keadaan instalasi yang sudah melewati setup."""

from __future__ import annotations

from datetime import date

import pytest

from core.models import CompanyProfile
from ledger.models import Account

TEST_PASSWORD = "RahasiaKandang2026"


@pytest.fixture
def completed_setup(db, django_user_model):
    user = django_user_model.objects.create_user(username="pemilik", password=TEST_PASSWORD)
    CompanyProfile.objects.create(
        name="Telur Jaya Farm",
        business_start_date=date(2026, 9, 1),
        setup_completed=True,
    )
    Account.objects.create(
        name="Kas Utama",
        type="cash",
        currency="IDR",
        opening_balance="250000000.00",
        opening_balance_date=date(2026, 9, 1),
    )
    return user
