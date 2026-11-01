"""Wizard setup 5 langkah (FR-02).

Langka 1-3 menyimpan ke DB, langkah 4 ke session, langkah 5 memfinalisasi
semua dalam satu transaksi. Untuk langkah 2-5 pengguna wajib login.
"""

from __future__ import annotations

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_not_required
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import urlencode
from django.views.decorators.http import require_http_methods

from core.models import CompanyProfile
from core.services.setup_state import SETUP_DRAFT_KEY, SetupStep, resolve_setup_step, step_url
from core.utils.dates import format_date_long_id, format_date_short, today_wib
from core.utils.numbers import format_id_number, format_money, format_qty
from ledger.models import ACCOUNT_CHOICES, Account
from ledger.services.accounts import ensure_default_accounts
from onboarding.errors import SetupIncomplete
from onboarding.forms import (
    AccountSetupForm,
    BalanceSetupForm,
    ProfileSetupForm,
    StockSetupForm,
)
from onboarding.services import messages as setup_messages
from onboarding.services.finalize import finalize_setup

STOCK_META = (
    ("feed", "Pakan", "kg"),
    ("egg", "Telur", "kg"),
    ("manure", "Kotoran", "karung"),
)

STEP_LABELS = (
    (1, "Akun"),
    (2, "Profil"),
    (3, "Saldo"),
    (4, "Stok"),
    (5, "Ringkasan"),
)


def _current_step(request: HttpRequest) -> SetupStep:
    return getattr(request, "setup_step", None) or resolve_setup_step(request.session)


def _login_redirect(request: HttpRequest) -> HttpResponse:
    return redirect(f"{reverse('login')}?{urlencode({'next': request.path})}")


def _render(request: HttpRequest, template: str, *, step: int, **context) -> HttpResponse:
    stepper = [
        {
            "number": number,
            "label": label,
            "state": "done" if number < step else "current" if number == step else "todo",
        }
        for number, label in STEP_LABELS
    ]
    context.setdefault("step", step)
    context.setdefault("stepper", stepper)
    context.setdefault("setup_wizard", True)
    return render(request, template, context)


def _gone_if_complete(request: HttpRequest, step: SetupStep) -> HttpResponse | None:
    if step is SetupStep.COMPLETE:
        if request.user.is_authenticated:
            raise Http404("Setup sudah selesai.")
        return redirect("login")
    return None


@login_not_required
@require_http_methods(["GET"])
def setup_entry(request: HttpRequest) -> HttpResponse:
    step = _current_step(request)
    completed_response = _gone_if_complete(request, step)
    if completed_response is not None:
        return completed_response
    return redirect(step_url(step))


@login_not_required
@require_http_methods(["GET", "POST"])
def step_account(request: HttpRequest) -> HttpResponse:
    step = _current_step(request)
    completed_response = _gone_if_complete(request, step)
    if completed_response is not None:
        return completed_response
    if step is not SetupStep.ACCOUNT:
        return redirect(step_url(step))

    form = AccountSetupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = get_user_model().objects.create_user(
            username=form.cleaned_data["username"],
            first_name=form.cleaned_data["first_name"].strip(),
            password=form.cleaned_data["password"],
        )
        login(request, user)
        return redirect("setup_profile")

    return _render(
        request,
        "onboarding/step_1.html",
        step=1,
        form=form,
        wizard_title="Buat akun pemilik",
        wizard_subtitle="Akun ini dipakai untuk masuk ke aplikasi.",
    )


def _authorized_step(request: HttpRequest, step: SetupStep) -> HttpResponse | None:
    """Kembalikan respons redirect bila langkah belum boleh diakses."""
    if step is SetupStep.COMPLETE:
        raise Http404("Setup sudah selesai.")
    if step is SetupStep.ACCOUNT:
        return redirect(step_url(step))
    if not request.user.is_authenticated:
        return _login_redirect(request)
    return None


@login_not_required
@require_http_methods(["GET", "POST"])
def step_profile(request: HttpRequest) -> HttpResponse:
    step = _current_step(request)
    denied = _authorized_step(request, step)
    if denied is not None:
        return denied
    if step is not SetupStep.PROFILE:
        return redirect(step_url(step))

    form = ProfileSetupForm(
        request.POST or None,
        initial={"application_start_date": today_wib().isoformat()},
    )
    if request.method == "POST" and form.is_valid():
        CompanyProfile.objects.create(
            name=form.cleaned_data["name"],
            business_start_date=form.cleaned_data["business_start_date"],
            application_start_date=form.cleaned_data["application_start_date"],
            setup_completed=False,
        )
        return redirect("setup_balance")

    return _render(
        request,
        "onboarding/step_2.html",
        step=2,
        form=form,
        wizard_title="Profil usaha",
        wizard_subtitle="Nama usaha dipakai di header aplikasi dan laporan.",
    )


@login_not_required
@require_http_methods(["GET", "POST"])
def step_balance(request: HttpRequest) -> HttpResponse:
    step = _current_step(request)
    denied = _authorized_step(request, step)
    if denied is not None:
        return denied
    if step < SetupStep.BALANCE:
        return redirect(step_url(step))

    profile = CompanyProfile.get_solo()
    accounts = {account.code: account for account in Account.objects.all()}

    initial = {
        f"opening_balance_{code}": format_id_number(
            accounts[code].opening_balance if code in accounts else 0, 2
        )
        for code, _label in ACCOUNT_CHOICES
    }
    if accounts:
        initial["opening_balance_date"] = (
            next(iter(accounts.values())).opening_balance_date.isoformat()
        )
    else:
        initial["opening_balance_date"] = (
            profile.business_start_date.isoformat()
            if profile and profile.business_start_date
            else ""
        )

    form = BalanceSetupForm(
        request.POST or None,
        business_start_date=profile.business_start_date if profile else None,
        initial=initial,
    )
    if request.method == "POST" and form.is_valid():
        opening_balances = {
            code: form.cleaned_data[f"opening_balance_{code}"]
            for code, _label in ACCOUNT_CHOICES
        }
        with transaction.atomic():
            saved_accounts = ensure_default_accounts(
                opening_balance_date=form.cleaned_data["opening_balance_date"],
                opening_balances=opening_balances,
            )
            for account in saved_accounts:
                account.opening_balance = opening_balances[account.code]
                account.opening_balance_date = form.cleaned_data["opening_balance_date"]
                account.save(
                    update_fields=["opening_balance", "opening_balance_date", "updated_at"]
                )
        return redirect("setup_stock")

    context = {
        "form": form,
        "business_start_date": profile.business_start_date if profile else None,
    }
    return _render(
        request,
        "onboarding/step_3.html",
        step=3,
        wizard_title="Saldo awal kas",
        wizard_subtitle="Masukkan saldo kas saat usaha mulai.",
        **context,
    )


def _stock_initial(request: HttpRequest) -> dict[str, str]:
    draft = (request.session.get(SETUP_DRAFT_KEY) or {}).get("stock") or {}
    initial: dict[str, str] = {}
    for code, _name, _unit in STOCK_META:
        entry = draft.get(code) or {}
        qty = entry.get("qty")
        threshold = entry.get("min_threshold")
        initial[f"{code}_qty"] = format_qty(qty) if qty not in (None, "") else "0"
        initial[f"{code}_min"] = format_qty(threshold) if threshold not in (None, "") else ""
    return initial


@login_not_required
@require_http_methods(["GET", "POST"])
def step_stock(request: HttpRequest) -> HttpResponse:
    step = _current_step(request)
    denied = _authorized_step(request, step)
    if denied is not None:
        return denied
    if step < SetupStep.STOCK:
        return redirect(step_url(step))

    form = StockSetupForm(request.POST or None, initial=_stock_initial(request))
    if request.method == "POST" and form.is_valid():
        draft = request.session.get(SETUP_DRAFT_KEY) or {}
        draft["stock"] = form.stock_draft()
        request.session[SETUP_DRAFT_KEY] = draft
        return redirect("setup_review")

    return _render(
        request,
        "onboarding/step_4.html",
        step=4,
        form=form,
        wizard_title="Stok awal",
        wizard_subtitle="Isi jumlah stok saat setup; boleh 0 bila belum ada.",
    )


def _summary_context(request: HttpRequest) -> dict:
    profile = CompanyProfile.get_solo()
    accounts = {
        account.code: account
        for account in Account.objects.filter(is_active=True)
    }
    draft = (request.session.get(SETUP_DRAFT_KEY) or {}).get("stock") or {}
    user = request.user

    stock_rows = []
    for code, name, unit in STOCK_META:
        entry = draft.get(code) or {}
        qty = entry.get("qty") or "0"
        threshold = entry.get("min_threshold")
        stock_rows.append(
            {
                "name": name,
                "qty": format_qty(qty),
                "unit": unit,
                "threshold": format_qty(threshold) if threshold not in (None, "") else None,
            }
        )

    return {
        "user": user,
        "profile": profile,
        "accounts": [
            {
                "name": label,
                "balance": format_money(
                    accounts[code].opening_balance if code in accounts else Decimal("0")
                ),
            }
            for code, label in ACCOUNT_CHOICES
        ],
        "balance_total_display": format_money(
            sum(
                (account.opening_balance for account in accounts.values()),
                Decimal("0"),
            )
        ),
        "stock_rows": stock_rows,
        "balance_date_display": format_date_short(
            next(iter(accounts.values())).opening_balance_date
        ) if accounts else "-",
        "business_start_display": (
            format_date_long_id(profile.business_start_date)
            if profile and profile.business_start_date
            else "—"
        ),
    }


@login_not_required
@require_http_methods(["GET", "POST"])
def step_review(request: HttpRequest) -> HttpResponse:
    step = _current_step(request)
    denied = _authorized_step(request, step)
    if denied is not None:
        return denied
    if step is not SetupStep.REVIEW:
        return redirect(step_url(step))

    if request.method == "POST":
        stock_draft = (request.session.get(SETUP_DRAFT_KEY) or {}).get("stock")
        try:
            finalize_setup(actor=request.user, stock_draft=stock_draft)
        except SetupIncomplete as exc:
            messages.error(request, str(exc))
            return redirect(step_url(exc.step))

        request.session.pop(SETUP_DRAFT_KEY, None)
        messages.success(request, setup_messages.SETUP_DONE)
        return redirect("dashboard")

    return _render(
        request,
        "onboarding/step_5.html",
        step=5,
        wizard_title="Ringkasan setup",
        wizard_subtitle="Periksa data sebelum menyelesaikan setup.",
        **_summary_context(request),
    )
