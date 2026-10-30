"""Layar Stok: pengaturan (S-16), input harian (S-08), dan penyesuaian (S-09)."""

from __future__ import annotations

import json

from django.contrib import messages as flash
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from core import messages
from core.errors import DomainError, StockConflict
from core.types import RequestMeta
from master.models import StockItem
from stock.forms import StockAdjustmentForm, StockSettingsForm, StokHarianForm
from stock.models import StockMovement
from stock.queries import stock_overview
from stock.services.daily import (
    CONSUMPTION_CODES,
    PRODUCTION_CODES,
    adjust_stock,
    record_consumption,
    record_production,
)
from stock.services.settings import update_stock_settings


def _meta(request: HttpRequest) -> RequestMeta:
    return RequestMeta(
        ip=request.META.get("REMOTE_ADDR"),
        user_agent=request.headers.get("User-Agent"),
    )


def _toast(message: str) -> str:
    return json.dumps({"toast": {"msg": message}})


def _is_htmx(request: HttpRequest) -> bool:
    return request.headers.get("HX-Request") == "true"


def _cards(*, bound_form: StockSettingsForm | None = None):
    rows = []
    for card in stock_overview():
        code = card.stock_item.code
        form = (
            bound_form
            if bound_form is not None and bound_form.stock_item.pk == card.stock_item.pk
            else StockSettingsForm(
                stock_item=card.stock_item,
                locked_since=card.locked_since,
                auto_id=f"stok-{code}-%s",
            )
        )
        rows.append((card, form))
    return rows


def _render(request: HttpRequest, *, bound_form=None, status: int = 200) -> HttpResponse:
    return render(
        request,
        "master/stock_settings.html",
        {"cards": _cards(bound_form=bound_form)},
        status=status,
    )


@login_required
@require_http_methods(["GET"])
def stock_settings(request: HttpRequest) -> HttpResponse:
    return _render(request)


@login_required
@require_POST
def stock_update(request: HttpRequest, code: str) -> HttpResponse:
    stock_item = get_object_or_404(StockItem, code=code)
    card = next((row for row in stock_overview() if row.stock_item.pk == stock_item.pk), None)
    if card is None:  # pragma: no cover - get_object_or_404 sudah menutup
        raise StockItem.DoesNotExist(code)

    form = StockSettingsForm(
        request.POST,
        stock_item=stock_item,
        locked_since=card.locked_since,
        auto_id=f"stok-{code}-%s",
    )
    if form.is_valid():
        try:
            update_stock_settings(
                stock_item_id=stock_item.pk,
                opening_qty=form.cleaned_data["opening_qty"],
                min_threshold=form.cleaned_data["min_threshold"],
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
            flash.success(request, messages.STOCK_SETTINGS_SAVED)
            if _is_htmx(request):
                response = _render(request)
                response["HX-Trigger"] = _toast(messages.STOCK_SETTINGS_SAVED)
                return response
            return redirect("stock:settings")

    return _render(request, bound_form=form, status=200)


def _attach_error(form, exc: DomainError) -> None:
    if exc.fields:
        for field, message in exc.fields.items():
            form.add_error(field if field in form.fields else None, message)
    else:
        form.add_error(None, exc.message)


def _daily_context(form, show_deleted: bool = False) -> dict:
    return {
        "form": form,
        "cards": stock_overview(),
        "movements": _movements(show_deleted),
        "show_deleted": show_deleted,
    }


def _movements(show_deleted: bool):
    qs = StockMovement.all_objects if show_deleted else StockMovement.objects
    return (
        qs.filter(source__in=["manual", "adjustment"])
        .select_related("stock_item")
        .order_by("-date", "-id")
    )


@login_required
@require_http_methods(["GET", "POST"])
def daily_stock(request: HttpRequest) -> HttpResponse:
    """S-08: input stok harian (produksi telur/kotoran, pemakaian pakan)."""
    form = StokHarianForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        stock_item = form.cleaned_data["stock_item"]
        value_date = form.cleaned_data["date"]
        quantity = form.cleaned_data["qty"]
        actor = request.user
        meta = RequestMeta(
            ip=request.META.get("REMOTE_ADDR"),
            user_agent=request.headers.get("User-Agent"),
        )
        try:
            if stock_item.code in PRODUCTION_CODES:
                record_production(
                    stock_item=stock_item, date=value_date, qty=quantity, actor=actor, meta=meta
                )
            elif stock_item.code in CONSUMPTION_CODES:
                record_consumption(
                    stock_item=stock_item, date=value_date, qty=quantity, actor=actor, meta=meta
                )
            else:  # pragma: no cover - kode stok dibatasi skema
                form.add_error(None, messages.DAILY_PEMAKAIAN_HANYA_PAKAN)
                return render(request, "stock/daily.html", _daily_context(form, False), status=200)
        except (DomainError, StockConflict) as exc:
            print(f"VIEW DEBUG: caught exception: {exc}", flush=True)
            import traceback

            traceback.print_exc()
            _attach_error(form, exc)
            return render(request, "stock/daily.html", _daily_context(form, False), status=200)
        flash.success(request, messages.STOCK_MOVEMENT_DICATAT)
        return redirect("stock:daily")

    show_deleted = request.GET.get("show_deleted") == "1"
    return render(
        request,
        "stock/daily.html",
        {
            "form": form,
            "cards": stock_overview(),
            "movements": _movements(show_deleted),
            "show_deleted": show_deleted,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def stock_adjustment(request: HttpRequest) -> HttpResponse:
    """S-09: penyesuaian stok (+/-) dengan alasan."""
    form = StockAdjustmentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        stock_item = form.cleaned_data["stock_item"]
        value_date = form.cleaned_data["date"]
        signed_qty = form.cleaned_data["qty"]
        reason = form.cleaned_data["reason"]
        actor = request.user
        meta = RequestMeta(
            ip=request.META.get("REMOTE_ADDR"),
            user_agent=request.headers.get("User-Agent"),
        )
        try:
            adjust_stock(
                stock_item=stock_item,
                date=value_date,
                signed_qty=signed_qty,
                reason=reason,
                actor=actor,
                meta=meta,
            )
        except (DomainError, StockConflict) as exc:
            _attach_error(form, exc)
            return render(request, "stock/adjustment.html", _adjustment_context(form), status=200)
        flash.success(request, messages.STOCK_MOVEMENT_DICATAT)
        return redirect("stock:adjustment")

    return render(request, "stock/adjustment.html", _adjustment_context(form))


def _adjustment_context(form: StockAdjustmentForm) -> dict:
    return {"form": form}
