"""Route test-only untuk memicu 403/404/500 saat DEBUG=False."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.urls import path


def boom(request: HttpRequest) -> HttpResponse:
    raise RuntimeError("kegagalan uji")


def forbidden(request: HttpRequest) -> HttpResponse:
    raise PermissionDenied("akses uji ditolak")


urlpatterns = [
    path("boom", boom),
    path("forbidden", forbidden),
]

handler403 = "core.views.error_403"
handler404 = "core.views.error_404"
handler500 = "core.views.error_500"
