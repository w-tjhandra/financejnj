"""Layar Pengaturan → Saldo Awal (S-17, FR-07).

Koreksi saldo awal belum dibangun (T-006.4); tombolnya diarahkan ke halaman
placeholder yang menjelaskan ketersediaannya.
"""

from __future__ import annotations

from django.contrib import messages as flash
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from core import messages
from core.errors import DomainError
from core.models import CompanyProfile
from core.types import RequestMeta
from core.utils.dates import format_date_long_id, format_date_short
from core.utils.numbers import format_id_number, format_money
from ledger.forms import OpeningBalanceForm
from ledger.services.opening import (
    cash_is_locked,
    cash_locked_since,
    current_account,
    set_opening_balance,
)


def _meta(request: HttpRequest) -> RequestMeta:
    return RequestMeta(
        ip=request.META.get("REMOTE_ADDR"),
        user_agent=request.headers.get("User-Agent"),
    )


@login_required
@require_http_methods(["GET", "POST"])
def opening_balance(request: HttpRequest) -> HttpResponse:
    account = current_account()
    if account is None:
        raise Http404("Akun kas belum tersedia.")

    profile = CompanyProfile.get_solo()
    business_start_date = profile.business_start_date if profile is not None else None
    locked = cash_is_locked()
    locked_since = cash_locked_since() if locked else None

    form = OpeningBalanceForm(
        request.POST or None,
        business_start_date=business_start_date,
        initial={
            "opening_balance": format_id_number(account.opening_balance, 2),
            "opening_balance_date": account.opening_balance_date.isoformat(),
        },
    )
    if request.method == "POST":
        if locked:
            flash.error(request, messages.OPENING_BALANCE_LOCKED)
            return redirect("opening_balance")
        if form.is_valid():
            try:
                set_opening_balance(
                    amount=form.cleaned_data["opening_balance"],
                    value_date=form.cleaned_data["opening_balance_date"],
                    actor=request.user,
                    meta=_meta(request),
                )
            except DomainError as exc:
                if exc.fields:
                    for field, message in exc.fields.items():
                        form.add_error(field if field in form.fields else None, message)
                else:
                    form.add_error(None, exc.message)
            else:
                flash.success(request, messages.OPENING_BALANCE_SAVED)
                return redirect("opening_balance")

    return render(
        request,
        "ledger/opening_balance.html",
        {
            "form": form,
            "account": account,
            "locked": locked,
            "locked_since": locked_since,
            "locked_since_short": format_date_short(locked_since) if locked_since else "",
            "opening_display": format_money(account.opening_balance),
            "opening_date_display": format_date_long_id(account.opening_balance_date),
        },
    )


@login_required
@require_GET
def opening_correction(request: HttpRequest) -> HttpResponse:
    """Placeholder sampai modul transaksi (T-006.4) menyediakan koreksi."""
    return render(
        request,
        "ledger/opening_correction_placeholder.html",
        {"account": current_account()},
    )
