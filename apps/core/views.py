"""Health check, autentikasi, pengaturan akun, dan halaman error (FR-01)."""

from __future__ import annotations

from datetime import date

from django.contrib import messages
from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.decorators import login_not_required, login_required
from django.contrib.auth.views import LoginView as DjangoLoginView
from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core import messages as core_messages
from core.errors import DomainError
from core.forms import AccountPasswordChangeForm, CompanyProfileForm, LoginForm
from core.models import CompanyProfile
from core.services.locks import (
    AlreadyLocked,
    AlreadyUnlocked,
    lock_period,
    max_locked_period,
    period_status,
    unlock_period,
)
from core.services.login_throttle import (
    is_login_locked,
    register_login_failure,
    reset_login_failures,
)
from core.services.profile import update_company_profile
from core.types import RequestMeta
from core.utils.dates import add_months, month_start, today_wib


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


def _safe_next_url(request: HttpRequest) -> str | None:
    """Hanya izinkan path internal; tolak URL absolut, protocol-relative, backslash."""
    candidate = (request.POST.get("next") or request.GET.get("next") or "").strip()
    if not candidate:
        return None
    if not candidate.startswith("/") or candidate.startswith("//"):
        return None
    if "\\" in candidate or "%5c" in candidate.casefold():
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in candidate):
        return None
    if not url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return None
    return candidate


@method_decorator(login_not_required, name="dispatch")
class LoginView(DjangoLoginView):
    template_name = "core/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def get_redirect_url(self) -> str | None:
        return _safe_next_url(self.request)

    def get_success_url(self) -> str:
        return self.get_redirect_url() or self.get_default_redirect_url()

    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        username = (request.POST.get("username") or "").strip()
        if is_login_locked(request, username):
            form = self.get_form()
            form.add_error(None, core_messages.RATE_LIMITED)
            return self.render_to_response(self.get_context_data(form=form))
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form) -> HttpResponse:
        username = (self.request.POST.get("username") or "").strip()
        # Percobaan dengan field kosong bukan percobaan kredensial.
        if username and self.request.POST.get("password"):
            register_login_failure(self.request, username)
        return super().form_invalid(form)

    def form_valid(self, form) -> HttpResponse:
        response = super().form_valid(form)
        username = form.cleaned_data.get("username") or self.request.POST.get("username", "")
        reset_login_failures(self.request, username)
        return response


@login_not_required
@require_POST
def logout_view(request: HttpRequest):
    """Logout hanya lewat POST (CSRF) sesuai rancangan §6.2."""
    logout(request)
    return redirect("login")


@login_required
@require_http_methods(["GET", "POST"])
def account_settings(request: HttpRequest) -> HttpResponse:
    """Ganti kata sandi; sesi tetap aktif setelah berhasil."""
    form = AccountPasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        # Perbarui hash sesi agar tidak logout dan sesi lama tidak valid.
        update_session_auth_hash(request, form.user)
        messages.success(request, core_messages.PASSWORD_CHANGED)
        return redirect("account_settings")

    return render(request, "core/account_settings.html", {"form": form})


@login_required
@require_http_methods(["GET", "POST"])
def profile_view(request: HttpRequest) -> HttpResponse:
    """S-20 Profil usaha. Header aplikasi memakai `company_name` terbaru."""
    profile = CompanyProfile.get_solo()
    form = CompanyProfileForm(
        request.POST or None,
        initial={
            "name": profile.name if profile else "",
            "address": profile.address if profile else "",
            "phone": profile.phone if profile else "",
            "email": profile.email if profile else "",
        },
    )
    if request.method == "POST" and form.is_valid():
        try:
            update_company_profile(
                name=form.cleaned_data["name"],
                address=form.cleaned_data["address"],
                phone=form.cleaned_data["phone"],
                email=form.cleaned_data["email"],
                actor=request.user,
                meta=RequestMeta(
                    ip=request.META.get("REMOTE_ADDR"),
                    user_agent=request.headers.get("User-Agent"),
                ),
            )
        except DomainError as exc:
            if exc.fields:
                for field, message in exc.fields.items():
                    form.add_error(field if field in form.fields else None, message)
            else:
                form.add_error(None, exc.message)
        else:
            messages.success(request, core_messages.PROFILE_SAVED)
            return redirect("profile")

    return render(request, "core/profile.html", {"form": form})


def error_403(request: HttpRequest, exception: Exception) -> HttpResponse:
    return render(request, "403.html", status=403)


def error_404(request: HttpRequest, exception: Exception) -> HttpResponse:
    return render(request, "404.html", status=404)


@never_cache
def error_500(request: HttpRequest) -> HttpResponse:
    return render(request, "500.html", status=500)


# --- Period Lock UI (S-16, AC-30.x) --------------------------------------


@login_required
@require_GET
def period_lock_list(request: HttpRequest) -> HttpResponse:
    """Daftar status kunci periode (termasuk yang pernah dibuka)."""
    today = today_wib()
    max_locked = max_locked_period()
    opening_date = add_months(today, -24)  # tampilkan 24 bulan mundur
    if max_locked:
        opening_date = min(opening_date, max_locked)

    months = []
    current = month_start(opening_date)
    while current <= add_months(today, 1):
        status = period_status(current)
        months.append(status)
        current = add_months(current, 1)

    return render(
        request,
        "core/period_lock_list.html",
        {
            "months": months,
            "today": today,
            "max_locked": max_locked,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def period_lock_action(request: HttpRequest, period: str) -> HttpResponse:
    """Kunci atau buka kunci periode (POST)."""
    try:
        target = date.fromisoformat(f"{period}-01")
    except ValueError:
        messages.error(request, "Format periode tidak valid.")
        return redirect("period_lock_list")

    target = month_start(target)

    if request.method == "POST":
        action = request.POST.get("action")
        meta = RequestMeta(
            ip=request.META.get("REMOTE_ADDR"),
            user_agent=request.headers.get("User-Agent"),
        )
        try:
            if action == "lock":
                lock_period(target, actor=request.user, meta=meta)
                messages.success(request, core_messages.PERIOD_LOCKED)
            elif action == "unlock":
                reason = request.POST.get("reason", "").strip()
                unlock_period(target, reason, actor=request.user, meta=meta)
                messages.success(request, core_messages.PERIOD_UNLOCKED)
            else:
                messages.error(request, "Aksi tidak valid.")
        except AlreadyLocked as exc:
            messages.error(request, exc.message)
        except AlreadyUnlocked as exc:
            messages.error(request, exc.message)
        except DomainError as exc:
            messages.error(request, exc.message)
        return redirect("period_lock_list")

    # GET - tampilkan detail
    status = period_status(target)
    return render(
        request,
        "core/period_lock_action.html",
        {"status": status},
    )
