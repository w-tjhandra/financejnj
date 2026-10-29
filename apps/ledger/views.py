"""Layar Pengaturan → Saldo Awal (S-17, FR-07).

Koreksi saldo awal belum dibangun (T-006.4); tombolnya diarahkan ke halaman
placeholder yang menjelaskan ketersediaannya.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib import messages as flash
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from core import messages
from core.errors import DomainError, DuplicateSalary, StockConflict, StockInsufficient
from core.models import CompanyProfile
from core.services.locks import is_date_editable, max_locked_period
from core.types import RequestMeta
from core.utils.dates import (
    format_date_long_id,
    format_date_short,
    format_datetime_wib,
    format_month_id,
    month_start,
    today_wib,
)
from core.utils.numbers import format_id_number, format_money, format_qty
from ledger.forms import OpeningBalanceForm, TransactionForm, transaction_initial
from ledger.models import Transaction
from ledger.services.opening import (
    cash_is_locked,
    cash_locked_since,
    current_account,
    set_opening_balance,
)
from ledger.services.transactions import create_transaction, delete_transaction, update_transaction
from master.models import Item
from master.services.items import active_items

FLOW_LABELS = {"income": "Pemasukan", "expense": "Pengeluaran"}
PAYMENT_LABELS = {"cash": "Tunai", "transfer": "Transfer"}


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


# --- Transaksi: form, detail, hapus (FR-08…FR-11) -------------------------


def _attach_error(form, exc: DomainError) -> None:
    if exc.fields:
        for field, message in exc.fields.items():
            form.add_error(field if field in form.fields else None, message)
    else:
        form.add_error(None, exc.message)


def _form_status(exc: DomainError) -> int:
    if isinstance(exc, (StockInsufficient, StockConflict)):
        return 409
    return exc.http_status if exc.http_status in (403, 409) else 200


def _duplicate_redirect(existing_id: int):
    url = reverse("transaction_update", args=[existing_id])
    return redirect(f"{url}?duplicate=1")


def _duplicate_banner(txn: Transaction) -> str:
    period = txn.period_month or month_start(txn.date)
    return messages.SALARY_DUPLICATE_BANNER.format(
        category=txn.category.code,
        month=format_month_id(period),
    )


def _transaction_payload(form: TransactionForm) -> dict:
    data = form.cleaned_data
    return {
        "date": data["date"],
        "flow": data["flow"],
        "category": data["category"],
        "item": data["item"],
        "amount": data["amount"],
        "qty": data.get("qty"),
        "unit": data.get("unit"),
        "payment_method": data.get("payment_method") or None,
        "notes": data.get("notes") or "",
        "period_month": data.get("period_month"),
    }


def _form_initial_with_item(request: HttpRequest) -> dict:
    """Initial form baru; mendukung pemilihan item lewat query (tautan cepat)."""
    initial = {"date": today_wib().isoformat(), "flow": "expense"}
    item_id = request.GET.get("item")
    if item_id:
        item = (
            Item.objects.select_related("default_category").filter(pk=item_id).first()
            if item_id.isdigit()
            else None
        )
        if item is not None:
            initial.update(
                {
                    "flow": item.flow,
                    "item": item.pk,
                    "category": item.default_category_id,
                }
            )
    return initial


@login_required
@require_http_methods(["GET", "POST"])
def transaction_create(request: HttpRequest) -> HttpResponse:
    form = TransactionForm(request.POST or None, initial=_form_initial_with_item(request))
    if request.method == "POST" and form.is_valid():
        try:
            txn = create_transaction(
                **_transaction_payload(form), actor=request.user, meta=_meta(request)
            )
        except DuplicateSalary as exc:
            if exc.existing_id is not None:
                return _duplicate_redirect(exc.existing_id)
            flash.error(request, exc.message)
            form.add_error(None, exc.message)
        except DomainError as exc:
            _attach_error(form, exc)
            flash.error(request, exc.message)
            return render(
                request,
                "ledger/transaction_form.html",
                _form_context(form=form, mode="create"),
                status=_form_status(exc),
            )
        else:
            flash.success(request, messages.TRANSACTION_CREATED)
            return redirect("transaction_detail", pk=txn.pk)

    return render(
        request,
        "ledger/transaction_form.html",
        _form_context(form=form, mode="create"),
    )


def _form_context(*, form: TransactionForm, mode: str, txn: Transaction | None = None, **extra):
    context = {
        "form": form,
        "mode": mode,
        "txn": txn,
        "selected_item": form.selected_item,
        "read_only": form.read_only,
        "today": today_wib(),
        "month_max": today_wib().strftime("%Y-%m"),
    }
    context.update(extra)
    return context


@login_required
@require_http_methods(["GET", "POST"])
def transaction_update(request: HttpRequest, pk: int) -> HttpResponse:
    txn = (
        Transaction.objects.select_related("category", "item", "item__stock_item")
        .filter(pk=pk)
        .first()
    )
    if txn is None:
        raise Http404(messages.TRANSACTION_NOT_FOUND)
    if txn.is_opening_correction:
        flash.error(request, messages.TRANSACTION_CORRECTION_READONLY)
        return redirect("transaction_detail", pk=txn.pk)

    locked = not is_date_editable(txn.date)
    if request.method == "POST" and locked:
        period = max_locked_period() or month_start(txn.date)
        flash.error(request, messages.period_locked(period))
        return redirect("transaction_detail", pk=txn.pk)

    form = TransactionForm(
        request.POST or None,
        instance=txn,
        initial=transaction_initial(txn),
        read_only=locked,
    )
    if request.method == "POST" and form.is_valid():
        try:
            updated = update_transaction(
                transaction_id=txn.pk,
                **_transaction_payload(form),
                actor=request.user,
                meta=_meta(request),
            )
        except DuplicateSalary as exc:
            if exc.existing_id is not None and exc.existing_id != txn.pk:
                return _duplicate_redirect(exc.existing_id)
            form.add_error(None, exc.message)
        except DomainError as exc:
            _attach_error(form, exc)
            flash.error(request, exc.message)
            return render(
                request,
                "ledger/transaction_form.html",
                _form_context(
                    form=form,
                    mode="edit",
                    txn=txn,
                    duplicate_banner=False,
                    locked=locked,
                ),
                status=_form_status(exc),
            )
        else:
            flash.success(request, messages.TRANSACTION_UPDATED)
            return redirect("transaction_detail", pk=updated.pk)

    duplicate_banner = request.GET.get("duplicate") == "1" and txn.period_month is not None
    return render(
        request,
        "ledger/transaction_form.html",
        _form_context(
            form=form,
            mode="edit",
            txn=txn,
            duplicate_banner=_duplicate_banner(txn) if duplicate_banner else "",
            locked=locked,
        ),
        status=403 if request.method == "POST" and locked else 200,
    )


@login_required
@require_GET
def transaction_detail(request: HttpRequest, pk: int) -> HttpResponse:
    txn = (
        Transaction.all_objects.select_related(
            "category",
            "item",
            "account",
            "created_by",
            "updated_by",
        )
        .filter(pk=pk)
        .first()
    )
    if txn is None:
        raise Http404(messages.TRANSACTION_NOT_FOUND)

    deleted = txn.deleted_at is not None
    correction = txn.is_opening_correction
    locked = not is_date_editable(txn.date)
    can_edit = not deleted and not correction
    can_delete = not deleted and not correction
    context = {
        "txn": txn,
        "amount_display": format_money(txn.amount),
        "date_display": format_date_long_id(txn.date),
        "flow_display": FLOW_LABELS.get(txn.flow, txn.flow),
        "payment_display": PAYMENT_LABELS.get(txn.payment_method or "", "—"),
        "qty_display": format_qty(txn.qty) if txn.qty is not None else "",
        "period_display": format_month_id(txn.period_month) if txn.period_month else "",
        "created_at_display": format_datetime_wib(txn.created_at),
        "updated_at_display": format_datetime_wib(txn.updated_at),
        "deleted_at_display": (
            format_datetime_wib(txn.deleted_at) if txn.deleted_at is not None else ""
        ),
        "deleted": deleted,
        "correction": correction,
        "locked": locked,
        "can_edit": can_edit,
        "can_delete": can_delete,
    }
    return render(request, "ledger/transaction_detail.html", context)


def _delete_context(txn: Transaction, *, error: str = "", **extra) -> dict:
    context = {
        "txn": txn,
        "amount_display": format_money(txn.amount),
        "date_display": format_date_long_id(txn.date),
        "flow_display": FLOW_LABELS.get(txn.flow, txn.flow),
        "payment_display": PAYMENT_LABELS.get(txn.payment_method or "", "—"),
        "qty_display": format_qty(txn.qty) if txn.qty is not None else "",
        "period_display": format_month_id(txn.period_month) if txn.period_month else "",
        "deleted": txn.deleted_at is not None,
        "correction": txn.is_opening_correction,
        "locked": not is_date_editable(txn.date),
        "error": error,
    }
    context.update(extra)
    return context


@login_required
@require_http_methods(["GET", "POST"])
def transaction_delete(request: HttpRequest, pk: int) -> HttpResponse:
    txn = Transaction.all_objects.select_related("category", "item").filter(pk=pk).first()
    if txn is None:
        raise Http404(messages.TRANSACTION_NOT_FOUND)
    if txn.deleted_at is not None:
        flash.error(request, messages.TRANSACTION_NOT_FOUND)
        return redirect("transaction_detail", pk=txn.pk)

    if request.method == "POST":
        try:
            delete_transaction(
                transaction_id=txn.pk,
                actor=request.user,
                meta=_meta(request),
            )
        except DomainError as exc:
            flash.error(request, exc.message)
            return render(
                request,
                "ledger/transaction_delete.html",
                _delete_context(txn, error=exc.message),
                status=exc.http_status,
            )
        else:
            flash.success(request, messages.TRANSACTION_DELETED)
            return redirect("transaction_detail", pk=txn.pk)

    return render(request, "ledger/transaction_delete.html", _delete_context(txn))


@login_required
@require_GET
def transaction_item_options(request: HttpRequest) -> HttpResponse:
    flow = request.GET.get("flow") or "expense"
    if flow not in {"income", "expense"}:
        flow = "expense"
    return render(
        request,
        "ledger/_item_options.html",
        {"items": active_items(flow=flow)},
    )


@login_required
@require_GET
def transaction_item_fields(request: HttpRequest) -> HttpResponse:
    initial = {
        "date": request.GET.get("date") or today_wib().isoformat(),
        "flow": request.GET.get("flow") or "expense",
        "item": request.GET.get("item") or "",
    }
    form = TransactionForm(initial=initial)
    return render(
        request,
        "ledger/_item_fields.html",
        _form_context(form=form, mode="create"),
    )


# --- Transaksi: daftar & pencarian (FR-13, S-04) ----------------------------


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _parse_decimal(s: str | None) -> Decimal | None:
    if not s:
        return None
    from core.utils.numbers import parse_id_number

    try:
        return parse_id_number(s, 2)
    except Exception:
        return None


@login_required
@require_GET
def transaction_list(request: HttpRequest) -> HttpResponse:
    """S-04: Daftar transaksi dengan filter, pencarian, pagination."""
    today = today_wib()
    month_start_date = date(today.year, today.month, 1)
    if today.month == 12:
        month_end_date = date(today.year + 1, 1, 1) - timezone.timedelta(days=1)
    else:
        month_end_date = date(today.year, today.month + 1, 1) - timezone.timedelta(days=1)

    # Parse filter dari GET
    date_from = _parse_date(request.GET.get("date_from")) or month_start_date
    date_to = _parse_date(request.GET.get("date_to")) or month_end_date
    flow = request.GET.get("flow") or None
    if flow not in {"income", "expense"}:
        flow = None
    category_id = request.GET.get("category")
    category_id = int(category_id) if category_id and category_id.isdigit() else None
    item_id = request.GET.get("item")
    item_id = int(item_id) if item_id and item_id.isdigit() else None
    amount_min = _parse_decimal(request.GET.get("amount_min"))
    amount_max = _parse_decimal(request.GET.get("amount_max"))
    keyword = request.GET.get("keyword") or None
    show_deleted = request.GET.get("show_deleted") == "1"
    sort = request.GET.get("sort") or "date_desc"
    allowed_sorts = {
        "date_desc",
        "date_asc",
        "amount_desc",
        "amount_asc",
        "created_desc",
        "created_asc",
    }
    if sort not in allowed_sorts:
        sort = "date_desc"
    page = int(request.GET.get("page") or 1)
    if page < 1:
        page = 1

    # Validasi range nominal
    if amount_min is not None and amount_max is not None and amount_min > amount_max:
        # Kembalikan ke halaman 1 dengan error
        page = 1

    from ledger.queries import TransactionListFilters, get_filter_options, transaction_list

    filters = TransactionListFilters(
        date_from=date_from,
        date_to=date_to,
        flow=flow,
        category_id=category_id,
        item_id=item_id,
        amount_min=amount_min,
        amount_max=amount_max,
        keyword=keyword,
        show_deleted=show_deleted,
        sort=sort,
        page=page,
    )
    result = transaction_list(filters)

    # Opsi filter
    filter_options = get_filter_options(flow)

    # Build query string untuk pagination (tanpa page)
    from urllib.parse import urlencode

    query_params = request.GET.copy()
    query_params.pop("page", None)
    query_string = urlencode(query_params)

    context = {
        "result": result,
        "filters": filters,
        "categories": filter_options["categories"],
        "items": filter_options["items"],
        "query_string": query_string,
        "FLOW_LABELS": {"income": "Pemasukan", "expense": "Pengeluaran"},
        "date_from_display": format_date_short(date_from),
        "date_to_display": format_date_short(date_to),
        "amount_min_display": format_money(amount_min) if amount_min is not None else "",
        "amount_max_display": format_money(amount_max) if amount_max is not None else "",
    }
    return render(request, "ledger/transaction_list.html", context)
