"""Setelan test: deterministik, tanpa debug, hasher cepat."""

from .base import *  # noqa: F401,F403

DEBUG = False
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]

# Test membuat user; Argon2 terlalu lambat untuk itu. Produksi tetap Argon2.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Test tidak butuh tabel cache; hindari createcachetable.
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
}
