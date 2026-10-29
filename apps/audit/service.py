"""Penulisan audit: satu pintu `log_audit`, serialisasi aman, diff before/after."""

from __future__ import annotations

import ipaddress
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from django.core.exceptions import FieldDoesNotExist
from django.db import models

from audit.constants import ACTION_VALUES, ENTITY_VALUES
from audit.models import AuditLog
from core.types import RequestMeta


def serialize_value(value):
    """Ubah nilai domain menjadi JSON-safe tanpa membocorkan objek internal."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, models.Model):
        return value.pk
    if isinstance(value, dict):
        return {str(key): serialize_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [serialize_value(item) for item in value]
    return value


def snapshot(obj, fields) -> dict:
    """Ambil nilai field tertentu dari objek model (FK menjadi id)."""
    result: dict[str, object] = {}
    for name in fields:
        try:
            field = obj._meta.get_field(name)
        except FieldDoesNotExist:
            value = getattr(obj, name)
        else:
            if field.is_relation and field.many_to_one:
                value = getattr(obj, f"{name}_id")
            else:
                value = getattr(obj, name)
        result[name] = serialize_value(value)
    return result


def diff(before: dict | None, after: dict | None) -> tuple[dict, dict]:
    """Kembalikan hanya field yang nilainya berubah."""
    before = before or {}
    after = after or {}
    changed_before: dict[str, object] = {}
    changed_after: dict[str, object] = {}
    for key in before.keys() | after.keys():
        if before.get(key) != after.get(key):
            changed_before[key] = before.get(key)
            changed_after[key] = after.get(key)
    return changed_before, changed_after


def _clean_ip(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def log_audit(
    *,
    entity: str,
    entity_id: int | None,
    action: str,
    actor=None,
    before: dict | None = None,
    after: dict | None = None,
    extra: dict | None = None,
    meta: RequestMeta | None = None,
) -> AuditLog:
    if entity not in ENTITY_VALUES:
        raise ValueError(f"entity audit tidak dikenal: {entity!r}")
    if action not in ACTION_VALUES:
        raise ValueError(f"action audit tidak dikenal: {action!r}")
    if entity == "export" and entity_id is not None:
        raise ValueError("entity export wajib entity_id NULL")
    if action == "login_failed" and entity_id is not None:
        raise ValueError("login_failed wajib entity_id NULL")

    user = actor if actor is not None and getattr(actor, "is_authenticated", True) else None
    user_agent = (meta.user_agent or "")[:200] if meta and meta.user_agent else None
    return AuditLog.objects.create(
        user=user,
        entity=entity,
        entity_id=entity_id,
        action=action,
        before=serialize_value(before) if before is not None else None,
        after=serialize_value(after) if after is not None else None,
        extra=serialize_value(extra) if extra is not None else None,
        ip=_clean_ip(meta.ip) if meta else None,
        user_agent=user_agent,
    )
