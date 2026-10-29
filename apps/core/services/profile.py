"""Profil usaha (S-20, FR-03).

Satu baris `CompanyProfile`; perubahan identitas dipakai header aplikasi dan
laporan PDF. Semua penulisan lewat service agar audit tidak bisa terlewat.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction

from audit.service import diff, log_audit, snapshot
from core import messages
from core.errors import DomainError
from core.models import CompanyProfile

AUDIT_FIELDS = ("name", "address", "phone", "email")


def _text(value: object) -> str:
    return str(value or "").strip()


def _validate_email(value: str) -> str:
    if not value:
        return ""
    try:
        validate_email(value)
    except ValidationError as exc:
        raise DomainError(
            messages.EMAIL_INVALID, code="email_invalid", fields={"email": messages.EMAIL_INVALID}
        ) from exc
    return value


def update_company_profile(
    *,
    name: object,
    address: object = "",
    phone: object = "",
    email: object = "",
    actor=None,
    meta=None,
) -> CompanyProfile:
    """Perbarui identitas usaha dan catat audit `company_profile:update`."""
    clean_name = _text(name)
    if not clean_name:
        raise DomainError(
            messages.BUSINESS_NAME_REQUIRED,
            code="name_required",
            fields={"name": messages.BUSINESS_NAME_REQUIRED},
        )
    clean_email = _validate_email(_text(email))
    values = {
        "name": clean_name,
        "address": _text(address),
        "phone": _text(phone),
        "email": clean_email,
    }

    with transaction.atomic():
        profile = CompanyProfile.get_solo(for_update=True)
        if profile is None:
            raise DomainError(
                "Profil usaha belum dibuat. Selesaikan setup terlebih dahulu.",
                code="profile_missing",
            )

        before = snapshot(profile, AUDIT_FIELDS)
        for field, value in values.items():
            setattr(profile, field, value)
        profile.save(update_fields=[*values.keys(), "updated_at"])

        changed_before, changed_after = diff(before, snapshot(profile, AUDIT_FIELDS))
        if changed_before:
            log_audit(
                entity="company_profile",
                entity_id=profile.pk,
                action="update",
                actor=actor,
                before=changed_before,
                after=changed_after,
                meta=meta,
            )
        return profile
