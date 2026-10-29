"""Pembatas percobaan login berbasis cache (FR-01 / BR-16).

Cache hanya menyimpan hash kombinasi IP+username dan jumlah kegagalan.
Kata sandi, username mentah, dan data pribadi lain tidak pernah ditulis ke
cache. Batas berlaku per kombinasi IP+username agar satu akun yang diserang
tidak mengunci semua pengguna dari IP lain.
"""

from __future__ import annotations

import hashlib

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest

CACHE_KEY_PREFIX = "auth:login-fail:"
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_LOCKOUT_SECONDS = 15 * 60


def _max_attempts() -> int:
    return int(getattr(settings, "LOGIN_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS))


def _lockout_seconds() -> int:
    return int(getattr(settings, "LOGIN_LOCKOUT_SECONDS", DEFAULT_LOCKOUT_SECONDS))


def client_ip(request: HttpRequest) -> str:
    """IP klien; header proxy hanya dipercaya bila dikonfigurasi eksplisit."""
    if getattr(settings, "TRUST_PROXY_HEADERS", False):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            first = forwarded.split(",", 1)[0].strip()
            if first:
                return first
    return request.META.get("REMOTE_ADDR") or "unknown"


def _cache_key(request: HttpRequest, username: str) -> str:
    identity = f"{client_ip(request)}|{username.strip().casefold()}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"{CACHE_KEY_PREFIX}{digest}"


def is_login_locked(request: HttpRequest, username: str) -> bool:
    username = (username or "").strip()
    if not username:
        return False
    attempts = cache.get(_cache_key(request, username), 0) or 0
    return attempts >= _max_attempts()


def register_login_failure(request: HttpRequest, username: str) -> int:
    """Catat satu kegagalan dan kembalikan jumlah kegagalan saat ini."""
    username = (username or "").strip()
    if not username:
        return 0

    key = _cache_key(request, username)
    timeout = _lockout_seconds()
    if cache.add(key, 1, timeout=timeout):
        return 1
    try:
        return int(cache.incr(key))
    except ValueError:
        # Key kedaluwarsa di antara add dan incr; mulai hitungan baru.
        cache.add(key, 1, timeout=timeout)
        return 1


def reset_login_failures(request: HttpRequest, username: str) -> None:
    username = (username or "").strip()
    if username:
        cache.delete(_cache_key(request, username))
