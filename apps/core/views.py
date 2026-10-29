"""Health check dan autentikasi dasar (FR-01)."""

from __future__ import annotations

from django.contrib.auth import logout
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.views import LoginView as DjangoLoginView
from django.db import connection
from django.http import HttpRequest, JsonResponse
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from core.forms import LoginForm


@login_not_required
@require_GET
@never_cache
def healthz(request: HttpRequest) -> JsonResponse:
    """Liveness + kesiapan DB. Dipakai Docker healthcheck dan monitoring."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:  # noqa: BLE001 - health tidak boleh melempar 500
        return JsonResponse({"status": "error", "db": "error"}, status=503)
    return JsonResponse({"status": "ok", "db": "ok"})


@method_decorator(login_not_required, name="dispatch")
class LoginView(DjangoLoginView):
    template_name = "core/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


@login_not_required
@require_POST
def logout_view(request: HttpRequest):
    """Logout hanya lewat POST (CSRF) sesuai rancangan §6.2."""
    logout(request)
    return redirect("login")
