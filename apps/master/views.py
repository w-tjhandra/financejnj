"""Layar Pengaturan → Kategori (S-14) dan Item (S-15)."""

from __future__ import annotations

import json

from django.contrib import messages as flash
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from core.errors import DomainError
from core.types import RequestMeta
from master.forms import CategoryForm, ItemForm
from master.models import Category, Item, StockItem
from master.services import categories as category_service
from master.services import items as item_service
from master.services.stock import update_stock_unit


def _meta(request: HttpRequest) -> RequestMeta:
    return RequestMeta(
        ip=request.META.get("REMOTE_ADDR"),
        user_agent=request.headers.get("User-Agent"),
    )


def _is_htmx(request: HttpRequest) -> bool:
    return request.headers.get("HX-Request") == "true"


def _toast(message: str) -> str:
    return json.dumps({"toast": {"msg": message}})


def _attach_error(form, exc: DomainError) -> None:
    if exc.fields:
        for field, message in exc.fields.items():
            form.add_error(field if field in form.fields else None, message)
    else:
        form.add_error(None, exc.message)


def _category_context(*, form: CategoryForm | None = None, editing: Category | None = None):
    return {
        "categories": category_service.categories_with_usage(),
        "form": form if form is not None else CategoryForm(instance=editing),
        "editing": editing,
    }


def _item_context(*, form: ItemForm | None = None, editing: Item | None = None):
    return {
        "items": item_service.items_with_usage(),
        "form": form if form is not None else ItemForm(),
        "editing": editing,
        "category_options": category_service.category_choices(include_inactive=True),
        "stock_items": StockItem.objects.order_by("id"),
        "can_change_rules": editing is None or item_service.item_usage_count(editing) == 0,
    }


def _category_payload(form: CategoryForm) -> dict:
    return {
        "code": form.cleaned_data["code"],
        "name": form.cleaned_data["name"],
        "parent": form.cleaned_data.get("parent"),
        "sort_order": form.cleaned_data.get("sort_order") or 0,
    }


def _item_payload(form: ItemForm) -> dict:
    return {
        "name": form.cleaned_data["name"],
        "flow": form.cleaned_data["flow"],
        "frequency": form.cleaned_data["frequency"],
        "default_category": form.cleaned_data.get("default_category"),
        "has_stock": bool(form.cleaned_data.get("has_stock")),
        "stock_item": form.cleaned_data.get("stock_item"),
        "unit": form.cleaned_data.get("unit"),
        "default_payment_method": form.cleaned_data.get("default_payment_method") or None,
        "sort_order": form.cleaned_data.get("sort_order") or 0,
    }


def _category_panel(request: HttpRequest, *, status: int = 200, error: str | None = None):
    context = _category_context()
    if error:
        context["action_error"] = error
    return render(request, "master/_category_panel.html", context, status=status)


def _item_panel(request: HttpRequest, *, status: int = 200, error: str | None = None):
    context = _item_context()
    if error:
        context["action_error"] = error
    return render(request, "master/_item_panel.html", context, status=status)


# --- Kategori -------------------------------------------------------------


@login_required
@require_http_methods(["GET", "POST"])
def category_list(request: HttpRequest) -> HttpResponse:
    form = CategoryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            category_service.create_category(
                **_category_payload(form), actor=request.user, meta=_meta(request)
            )
        except DomainError as exc:
            _attach_error(form, exc)
        else:
            message = "Kategori ditambahkan."
            flash.success(request, message)
            if _is_htmx(request):
                response = _category_panel(request)
                response["HX-Trigger"] = _toast(message)
                return response
            return redirect("master:category_list")

    context = _category_context(form=form)
    status = 422 if request.method == "POST" and _is_htmx(request) else 200
    return render(request, "master/category_list.html", context, status=status)


@login_required
@require_http_methods(["GET", "POST"])
def category_update(request: HttpRequest, pk: int) -> HttpResponse:
    category = get_object_or_404(Category, pk=pk)
    form = CategoryForm(request.POST or None, instance=category)

    if request.method == "POST" and form.is_valid():
        try:
            category_service.update_category(
                category_id=category.pk,
                **_category_payload(form),
                actor=request.user,
                meta=_meta(request),
            )
        except DomainError as exc:
            _attach_error(form, exc)
        else:
            message = "Kategori diperbarui."
            flash.success(request, message)
            if _is_htmx(request):
                response = _category_panel(request)
                response["HX-Trigger"] = _toast(message)
                return response
            return redirect("master:category_list")

    context = _category_context(form=form, editing=category)
    if _is_htmx(request):
        return render(
            request,
            "master/_category_form.html",
            context,
            status=422 if request.method == "POST" else 200,
        )
    return render(request, "master/category_edit.html", context)


@login_required
@require_POST
def category_deactivate(request: HttpRequest, pk: int) -> HttpResponse:
    get_object_or_404(Category, pk=pk)
    try:
        category_service.deactivate_category(
            category_id=pk, actor=request.user, meta=_meta(request)
        )
    except DomainError as exc:
        flash.error(request, exc.message)
        if _is_htmx(request):
            return _category_panel(request, status=exc.http_status, error=exc.message)
        return render(
            request,
            "master/category_list.html",
            {**_category_context(), "action_error": exc.message},
            status=exc.http_status,
        )
    message = "Kategori dinonaktifkan."
    flash.success(request, message)
    if _is_htmx(request):
        response = _category_panel(request)
        response["HX-Trigger"] = _toast(message)
        return response
    return redirect("master:category_list")


@login_required
@require_POST
def category_activate(request: HttpRequest, pk: int) -> HttpResponse:
    get_object_or_404(Category, pk=pk)
    category_service.activate_category(category_id=pk, actor=request.user, meta=_meta(request))
    message = "Kategori diaktifkan kembali."
    flash.success(request, message)
    if _is_htmx(request):
        response = _category_panel(request)
        response["HX-Trigger"] = _toast(message)
        return response
    return redirect("master:category_list")


@login_required
@require_POST
def category_delete(request: HttpRequest, pk: int) -> HttpResponse:
    get_object_or_404(Category, pk=pk)
    try:
        category_service.delete_category(category_id=pk, actor=request.user, meta=_meta(request))
    except DomainError as exc:
        flash.error(request, exc.message)
        if _is_htmx(request):
            return _category_panel(request, status=exc.http_status, error=exc.message)
        return render(
            request,
            "master/category_list.html",
            {**_category_context(), "action_error": exc.message},
            status=exc.http_status,
        )
    message = "Kategori dihapus."
    flash.success(request, message)
    if _is_htmx(request):
        response = _category_panel(request)
        response["HX-Trigger"] = _toast(message)
        return response
    return redirect("master:category_list")


# --- Item -----------------------------------------------------------------


@login_required
@require_http_methods(["GET", "POST"])
def item_list(request: HttpRequest) -> HttpResponse:
    form = ItemForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            item_service.create_item(**_item_payload(form), actor=request.user, meta=_meta(request))
        except DomainError as exc:
            _attach_error(form, exc)
        else:
            message = "Item ditambahkan."
            flash.success(request, message)
            if _is_htmx(request):
                response = _item_panel(request)
                response["HX-Trigger"] = _toast(message)
                return response
            return redirect("master:item_list")

    context = _item_context(form=form)
    status = 422 if request.method == "POST" and _is_htmx(request) else 200
    return render(request, "master/item_list.html", context, status=status)


@login_required
@require_http_methods(["GET", "POST"])
def item_update(request: HttpRequest, pk: int) -> HttpResponse:
    item = get_object_or_404(Item, pk=pk)
    used_count = item_service.item_usage_count(item)
    form = ItemForm(request.POST or None, instance=item, used_count=used_count)

    if request.method == "POST" and form.is_valid():
        try:
            item_service.update_item(
                item_id=item.pk, **_item_payload(form), actor=request.user, meta=_meta(request)
            )
        except DomainError as exc:
            _attach_error(form, exc)
        else:
            message = "Item diperbarui."
            flash.success(request, message)
            if _is_htmx(request):
                response = _item_panel(request)
                response["HX-Trigger"] = _toast(message)
                return response
            return redirect("master:item_list")

    context = _item_context(form=form, editing=item)
    if _is_htmx(request):
        return render(
            request,
            "master/_item_form.html",
            context,
            status=422 if request.method == "POST" else 200,
        )
    return render(request, "master/item_edit.html", context)


@login_required
@require_POST
def item_deactivate(request: HttpRequest, pk: int) -> HttpResponse:
    get_object_or_404(Item, pk=pk)
    try:
        item_service.deactivate_item(item_id=pk, actor=request.user, meta=_meta(request))
    except DomainError as exc:
        flash.error(request, exc.message)
        if _is_htmx(request):
            return _item_panel(request, status=exc.http_status, error=exc.message)
        return render(
            request,
            "master/item_list.html",
            {**_item_context(), "action_error": exc.message},
            status=exc.http_status,
        )
    message = "Item dinonaktifkan."
    flash.success(request, message)
    if _is_htmx(request):
        response = _item_panel(request)
        response["HX-Trigger"] = _toast(message)
        return response
    return redirect("master:item_list")


@login_required
@require_POST
def item_activate(request: HttpRequest, pk: int) -> HttpResponse:
    get_object_or_404(Item, pk=pk)
    item_service.activate_item(item_id=pk, actor=request.user, meta=_meta(request))
    message = "Item diaktifkan kembali."
    flash.success(request, message)
    if _is_htmx(request):
        response = _item_panel(request)
        response["HX-Trigger"] = _toast(message)
        return response
    return redirect("master:item_list")


@login_required
@require_POST
def item_delete(request: HttpRequest, pk: int) -> HttpResponse:
    get_object_or_404(Item, pk=pk)
    try:
        item_service.delete_item(item_id=pk, actor=request.user, meta=_meta(request))
    except DomainError as exc:
        flash.error(request, exc.message)
        if _is_htmx(request):
            return _item_panel(request, status=exc.http_status, error=exc.message)
        return render(
            request,
            "master/item_list.html",
            {**_item_context(), "action_error": exc.message},
            status=exc.http_status,
        )
    message = "Item dihapus."
    flash.success(request, message)
    if _is_htmx(request):
        response = _item_panel(request)
        response["HX-Trigger"] = _toast(message)
        return response
    return redirect("master:item_list")


# --- Stok (satuan tetap, AC-06.4) ----------------------------------------


@login_required
@require_POST
def stock_unit_update(request: HttpRequest, code: str) -> HttpResponse:
    stock_item = get_object_or_404(StockItem, code=code)
    try:
        update_stock_unit(
            stock_item_id=stock_item.pk,
            unit=request.POST.get("unit"),
            actor=request.user,
            meta=_meta(request),
        )
    except DomainError as exc:
        return JsonResponse({"error": exc.message}, status=exc.http_status)
    return JsonResponse({"error": "Tidak ada perubahan."}, status=400)
