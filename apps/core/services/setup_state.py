"""Deteksi langkah setup dari keadaan database (bukan dari session).

Satu-satunya bagian yang boleh memakai session adalah draft stok langkah 4,
karena draft itu memang tidak disimpan di DB sampai finalisasi.

Middleware setup guard dan view wizard memakai fungsi yang sama supaya
keduanya tidak pernah berbeda pendapat soal langkah yang sedang aktif.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from enum import IntEnum

from django.apps import apps
from django.contrib.auth import get_user_model

from core.models import CompanyProfile

STOCK_CODES = ("feed", "egg", "manure")
STOCK_QTY_MAX = Decimal("1000000")
SETUP_DRAFT_KEY = "setup_draft"


class SetupStep(IntEnum):
    ACCOUNT = 1
    PROFILE = 2
    BALANCE = 3
    STOCK = 4
    REVIEW = 5
    COMPLETE = 6


STEP_URLS = {
    SetupStep.ACCOUNT: "/setup/akun",
    SetupStep.PROFILE: "/setup/profil",
    SetupStep.BALANCE: "/setup/saldo",
    SetupStep.STOCK: "/setup/stok",
    SetupStep.REVIEW: "/setup/ringkasan",
}


def step_url(step: SetupStep) -> str:
    return STEP_URLS[step]


def stock_draft_is_complete(session) -> bool:
    """Draft dianggap lengkap bila qty ketiga jenis stok ada dan valid."""
    if session is None:
        return False
    draft = (session.get(SETUP_DRAFT_KEY) or {}).get("stock")
    if not isinstance(draft, dict):
        return False
    for code in STOCK_CODES:
        entry = draft.get(code)
        if not isinstance(entry, dict):
            return False
        raw_qty = entry.get("qty")
        if raw_qty in (None, ""):
            return False
        try:
            qty = Decimal(str(raw_qty))
        except (InvalidOperation, ValueError):
            return False
        if qty < 0 or qty > STOCK_QTY_MAX:
            return False
    return True


def resolve_setup_step(session=None) -> SetupStep:
    """Hitung langkah setup aktif dari DB.

    Urutan query sengaja: cek profil selesai lebih dulu agar request normal
    (setup sudah selesai) hanya memakai satu query ringan.
    """
    profile_status = (
        CompanyProfile.objects.order_by("pk").values_list("setup_completed", flat=True).first()
    )
    if profile_status is True:
        return SetupStep.COMPLETE

    if not get_user_model().objects.exists():
        return SetupStep.ACCOUNT

    if profile_status is None:
        return SetupStep.PROFILE

    account_model = apps.get_model("ledger", "Account")
    if not account_model.objects.exists():
        return SetupStep.BALANCE

    if not stock_draft_is_complete(session):
        return SetupStep.STOCK

    return SetupStep.REVIEW
