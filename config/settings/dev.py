"""Setelan pengembangan: DEBUG aktif, host longgar."""

from .base import *  # noqa: F401,F403

DEBUG = True
ALLOWED_HOSTS = ["*"]

# Email ke console agar tidak butuh SMTP di lokal.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
