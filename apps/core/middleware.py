"""Setup guard: kunci aplikasi sampai wizard setup selesai (FR-02/AC-02.6).

Urutan middleware: Session -> Authentication -> SetupGuard -> LoginRequired.
Path setup, login, logout, health, dan aset statis selalu boleh lewat supaya
user yang baru dibuat di langkah 1 bisa login dan melanjutkan.
"""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect

from core.services.setup_state import SetupStep, resolve_setup_step, step_url

ALLOWED_PATHS = frozenset({"/setup", "/healthz", "/favicon.ico", "/masuk", "/keluar"})
ALLOWED_PREFIXES = ("/setup/", "/static/")
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def _is_allowed_path(path: str) -> bool:
    return path in ALLOWED_PATHS or path.startswith(ALLOWED_PREFIXES)


def _is_setup_path(path: str) -> bool:
    return path == "/setup" or path.startswith("/setup/")


class SetupGuardMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        step = resolve_setup_step(request.session)
        request.setup_step = step

        if step is SetupStep.COMPLETE:
            if _is_setup_path(request.path_info):
                if request.user.is_authenticated:
                    return HttpResponse(status=404)
                return redirect("login")
            return self.get_response(request)

        if _is_allowed_path(request.path_info):
            return self.get_response(request)

        if request.method in SAFE_METHODS:
            return redirect(step_url(step))

        message = "Selesaikan setup terlebih dahulu."
        if "application/json" in request.headers.get("Accept", ""):
            return JsonResponse({"error": message}, status=403)
        return HttpResponseForbidden(message)
