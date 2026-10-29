"""Finalisasi setup: satu transaksi, idempoten, tanpa data setengah jadi."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.db import transaction

from audit.service import log_audit
from core.models import CompanyProfile
from ledger.models import Account
from master.services.seed import ensure_master_data
from onboarding.errors import SetupIncomplete
from onboarding.services.messages import (
    STEP_ACCOUNT_MISSING,
    STEP_BALANCE_MISSING,
    STEP_PROFILE_MISSING,
    STOCK_INVALID,
)

STOCK_CODES = ("feed", "egg", "manure")
STOCK_QTY_MAX = Decimal("1000000")
STOCK_THRESHOLD_MAX = Decimal("1000000")


@dataclass(frozen=True)
class FinalizeResult:
    profile: CompanyProfile
    created: bool


def _to_decimal(value, *, maximum: Decimal) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if number < 0 or number > maximum:
        return None
    return number


def clean_stock_draft(stock_draft: dict | None) -> dict[str, dict] | None:
    """Validasi draft session dan kembalikan nilai Decimal siap simpan."""
    if not isinstance(stock_draft, dict):
        return None
    cleaned: dict[str, dict] = {}
    for code in STOCK_CODES:
        entry = stock_draft.get(code)
        if not isinstance(entry, dict):
            return None
        qty = _to_decimal(entry.get("qty"), maximum=STOCK_QTY_MAX)
        if qty is None:
            return None
        threshold = _to_decimal(entry.get("min_threshold"), maximum=STOCK_THRESHOLD_MAX)
        cleaned[code] = {"qty": qty, "min_threshold": threshold}
    return cleaned


def finalize_setup(*, actor, stock_draft: dict | None) -> FinalizeResult:
    """Buat master data default, tandai selesai, dan tulis audit.

    Bila profil sudah bertanda selesai, tidak ada yang diubah (idempoten).
    Bila ada langkah yang hilang, seluruh transaksi dibatalkan.
    """
    with transaction.atomic():
        profile = CompanyProfile.objects.select_for_update().order_by("pk").first()
        if profile is not None and profile.setup_completed:
            return FinalizeResult(profile=profile, created=False)

        user_model = get_user_model()
        if not user_model.objects.exists():
            raise SetupIncomplete(STEP_ACCOUNT_MISSING, step=1)
        if profile is None:
            raise SetupIncomplete(STEP_PROFILE_MISSING, step=2)

        account = Account.objects.select_for_update().order_by("pk").first()
        if account is None:
            raise SetupIncomplete(STEP_BALANCE_MISSING, step=3)

        stock = clean_stock_draft(stock_draft)
        if stock is None:
            raise SetupIncomplete(STOCK_INVALID, step=4)

        ensure_master_data(stock=stock)

        profile.setup_completed = True
        profile.save(update_fields=["setup_completed", "updated_at"])
        log_audit(
            entity="company_profile",
            entity_id=profile.pk,
            action="update",
            actor=actor,
            before={"setup_completed": False},
            after={"setup_completed": True},
            extra={"event": "setup_completed"},
        )
        return FinalizeResult(profile=profile, created=True)
