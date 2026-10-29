"""Tipe bersama yang dipakai lintas lapisan (bukan model)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RequestMeta:
    """Metadata request untuk audit; tidak pernah memuat isi form."""

    ip: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
