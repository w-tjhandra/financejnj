"""Nilai template global: nama usaha untuk header aplikasi (AC-03.1)."""

from __future__ import annotations

from django.db import DatabaseError
from django.http import HttpRequest

from core.models import CompanyProfile

DEFAULT_COMPANY_NAME = "Telur Finance"


def company_profile(request: HttpRequest) -> dict:
    """Satu query ringan; aman saat tabel belum tersedia (mis. halaman error awal)."""
    try:
        profile = CompanyProfile.objects.order_by("pk").first()
    except DatabaseError:
        profile = None
    return {
        "company_profile": profile,
        "company_name": profile.name if profile is not None else DEFAULT_COMPANY_NAME,
    }
