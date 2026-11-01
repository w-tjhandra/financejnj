"""Layar Pengaturan → Saldo Awal (S-17, FR-07) & Transaksi (S-04…S-07, FR-08…FR-12)."""

from __future__ import annotations

import mimetypes
import os
from datetime import date
from decimal import Decimal
from io import BytesIO

from django.contrib import messages as flash
from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from weasyprint import HTML

from core import messages
from core.errors import DomainError, DuplicateSalary, NotFound, StockConflict, StockInsufficient
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
from ledger.forms import (
    AccountTransferForm,
    MultiAccountOpeningBalanceForm,
    OpeningCorrectionForm,
    TransactionForm,
    transaction_initial,
)
from ledger.models import ACCOUNT_CHOICES, Account, AccountTransfer, Attachment, Transaction
from ledger.services.account_transfers import (
    create_account_transfer,
    delete_account_transfer,
)
from ledger.services.accounts import account_balances_at, ensure_default_accounts
from ledger.services.opening import (
    cash_is_locked,
    cash_locked_since,
    current_account,
    record_opening_correction,
    set_opening_balances,
)
from ledger.services.transactions import (
    create_transaction,
    delete_transaction,
    duplicate_prefill,
    update_transaction,
)
from master.models import Item
from master.services.items import active_items
from reports.queries import daily_recap, monthly_recap, weekly_recap, yearly_recap

FLOW_LABELS = {"income": "Pemasukan", "expense": "Pengeluaran"}
PAYMENT_LABELS = {"cash": "Tunai", "transfer": "Transfer"}


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


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

    if any(not Account.objects.filter(code=code).exists() for code, _label in ACCOUNT_CHOICES):
        ensure_default_accounts(opening_balance_date=account.opening_balance_date)
    accounts = {
        row.code: row
        for row in Account.objects.filter(is_active=True)
    }
    profile = CompanyProfile.get_solo()
    business_start_date = profile.business_start_date if profile is not None else None
    locked = cash_is_locked()
    locked_since = cash_locked_since() if locked else None

    initial = {
        f"opening_balance_{code}": format_id_number(accounts[code].opening_balance, 2)
        for code, _label in ACCOUNT_CHOICES
    }
    initial["opening_balance_date"] = account.opening_balance_date.isoformat()
    form = MultiAccountOpeningBalanceForm(
        request.POST or None,
        business_start_date=business_start_date,
        initial=initial,
    )
    if request.method == "POST":
        if locked:
            flash.error(request, messages.OPENING_BALANCE_LOCKED)
            return redirect("opening_balance")
        if form.is_valid():
            try:
                set_opening_balances(
                    balances={
                        code: form.cleaned_data[f"opening_balance_{code}"]
                        for code, _label in ACCOUNT_CHOICES
                    },
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
            "opening_date_display": format_date_long_id(account.opening_balance_date),
            "accounts": [accounts[code] for code, _label in ACCOUNT_CHOICES],
            "opening_fields": [
                {
                    "account": accounts[code],
                    "field": form[f"opening_balance_{code}"],
                }
                for code, _label in ACCOUNT_CHOICES
            ],
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def account_transfers(request: HttpRequest) -> HttpResponse:
    form = AccountTransferForm(request.POST or None, initial={"date": today_wib()})
    if request.method == "POST" and form.is_valid():
        try:
            create_account_transfer(
                value_date=form.cleaned_data["date"],
                from_code=form.cleaned_data["from_account"].code,
                to_code=form.cleaned_data["to_account"].code,
                amount=form.cleaned_data["amount"],
                notes=form.cleaned_data["notes"],
                actor=request.user,
                meta=_meta(request),
            )
        except DomainError as exc:
            _attach_error(form, exc)
            flash.error(request, exc.message)
        else:
            flash.success(request, "Pindah dana berhasil dicatat.")
            return redirect("account_transfers")

    return render(
        request,
        "ledger/account_transfers.html",
        {
            "form": form,
            "balances": account_balances_at(today_wib()),
            "transfers": AccountTransfer.objects.select_related(
                "from_account", "to_account"
            )[:50],
            "today": today_wib(),
        },
    )


@login_required
@require_POST
def account_transfer_delete(request: HttpRequest, pk: int) -> HttpResponse:
    try:
        delete_account_transfer(transfer_id=pk, actor=request.user, meta=_meta(request))
    except NotFound as exc:
        raise Http404(exc.message) from exc
    except DomainError as exc:
        flash.error(request, exc.message)
    else:
        flash.success(request, "Pindah dana berhasil dibatalkan.")
    return redirect("account_transfers")


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
        "transfer_bank": data.get("transfer_bank") or None,
        "notes": data.get("notes") or "",
        "period_month": data.get("period_month"),
    }


def _form_initial_with_item(request: HttpRequest) -> dict:
    """Initial form baru; mendukung pemilihan item lewat query (tautan cepat) & prefill duplikat."""
    initial = {"date": today_wib().isoformat(), "flow": "expense"}

    # Handle prefill dari duplikat transaksi
    prefill_keys = [
        "date",
        "flow",
        "category",
        "item",
        "amount",
        "qty",
        "unit",
        "payment_method",
        "transfer_bank",
        "notes",
        "period_month",
    ]
    has_prefill = any(request.GET.get(k) for k in prefill_keys)
    if has_prefill:
        initial["date"] = request.GET.get("date", today_wib().isoformat())
        initial["flow"] = request.GET.get("flow", "expense")
        if request.GET.get("category"):
            initial["category"] = int(request.GET["category"])
        if request.GET.get("item"):
            initial["item"] = int(request.GET["item"])
        if request.GET.get("amount"):
            initial["amount"] = request.GET["amount"]
        if request.GET.get("qty"):
            initial["qty"] = request.GET["qty"]
        if request.GET.get("unit"):
            initial["unit"] = request.GET["unit"]
        if request.GET.get("payment_method"):
            initial["payment_method"] = request.GET["payment_method"]
        if request.GET.get("transfer_bank"):
            initial["transfer_bank"] = request.GET["transfer_bank"]
        if request.GET.get("notes"):
            initial["notes"] = request.GET["notes"]
        if request.GET.get("period_month"):
            initial["period_month"] = request.GET["period_month"]
        return initial

    # Fallback: item selection via query param
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
        "transfer_bank_display": txn.get_transfer_bank_display() if txn.transfer_bank else "",
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
        "transfer_bank_display": txn.get_transfer_bank_display() if txn.transfer_bank else "",
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
        "payment_method": request.GET.get("payment_method") or "",
        "transfer_bank": request.GET.get("transfer_bank") or "",
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


# --- Duplikat transaksi (FR-12, BR-08) ----------------------------------------


@login_required
@require_GET
def transaction_duplicate(request: HttpRequest, pk: int) -> HttpResponse:
    """GET /transaksi/<pk>/duplikat → redirect ke form create dengan prefill.

    Tidak menulis DB. Menggunakan service duplicate_prefill().
    """
    txn = Transaction.objects.filter(pk=pk).first()
    if txn is None:
        raise Http404(messages.TRANSACTION_NOT_FOUND)
    if txn.deleted_at is not None or txn.is_opening_correction:
        flash.error(request, "Transaksi ini tidak bisa diduplikat.")
        return redirect("transaction_detail", pk=pk)

    try:
        prefill = duplicate_prefill(pk)
    except NotFound:
        raise Http404(messages.TRANSACTION_NOT_FOUND) from None
    except DomainError as exc:
        flash.error(request, exc.message)
        return redirect("transaction_detail", pk=pk)

    # Redirect ke form create dengan parameter prefill
    params = []
    for key, value in prefill.items():
        if value is None:
            continue
        if key in ("category", "item") and hasattr(value, "pk"):
            params.append(f"{key}={value.pk}")
        elif key == "period_month" and value:
            params.append(f"{key}={value.strftime('%Y-%m')}")
        elif key == "date":
            params.append(f"{key}={value.isoformat()}")
        else:
            params.append(f"{key}={value}")
    return redirect(f"{reverse('transaction_create')}?{'&'.join(params)}")


# --- Koreksi Saldo Awal UI (S-17, FR-07) --------------------------------------


@login_required
@require_http_methods(["GET", "POST"])
def opening_correction(request: HttpRequest) -> HttpResponse:
    """Halaman koreksi saldo awal.

    GET: tampil form (tanggal read-only = opening_balance_date)
    POST: validasi, panggil record_opening_correction(), redirect ke opening_balance + pesan sukses
    """
    account_code = request.POST.get("account_code", "cash") if request.method == "POST" else "cash"
    account = Account.by_code(account_code) or current_account()
    if account is None:
        raise Http404("Akun kas belum tersedia.")

    if not cash_is_locked():
        flash.error(request, "Saldo awal belum terkunci; ubah saldo awal secara langsung.")
        return redirect("opening_balance")

    # Cek apakah periode saldo awal terkunci
    from core.services.locks import is_date_editable

    if not is_date_editable(account.opening_balance_date):
        flash.error(request, messages.period_locked(account.opening_balance_date))
        return redirect("opening_balance")

    form = OpeningCorrectionForm(
        request.POST or None,
        opening_balance_date=account.opening_balance_date,
        account_code=account.code or "cash",
    )
    if request.method == "POST" and form.is_valid():
        try:
            delta = form.cleaned_data["amount"]
            # Flow menentukan tanda delta: income = positif, expense = negatif
            if form.cleaned_data["flow"] == "expense":
                delta = -delta
            record_opening_correction(
                delta=delta,
                reason=form.cleaned_data["reason"],
                account_code=form.cleaned_data["account_code"],
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
            flash.success(
                request,
                "Koreksi saldo awal tercatat. Saldo sumber dan mutasi diperbarui.",
            )
            return redirect("opening_balance")

    return render(
        request,
        "ledger/opening_correction.html",
        {
            "form": form,
            "account": account,
            "opening_balance_display": format_money(account.opening_balance),
            "opening_date_display": format_date_long_id(account.opening_balance_date),
        },
    )


# --- Lampiran Transaksi (FR-14, S-06) ----------------------------------------


def _validate_upload(file) -> tuple[bytes, str, str]:
    """Validasi file upload: tipe, ukuran. Kembalikan (content, mime, ext)."""
    if not file:
        raise DomainError("File wajib diisi.", code="file_required")
    content = file.read()
    if len(content) == 0:
        raise DomainError("File kosong.", code="file_empty")
    if len(content) > 10 * 1024 * 1024:
        raise DomainError("File maksimal 10 MB.", code="file_too_large")

    mime = mimetypes.guess_type(file.name)[0] or ""
    allowed = ["image/jpeg", "image/png", "image/webp", "application/pdf"]
    if mime not in allowed:
        raise DomainError(
            "Format file tidak didukung (JPEG, PNG, WebP, PDF).", code="mime_not_allowed"
        )

    # Re-check extension matches mime

    ext = os.path.splitext(file.name)[1].lower()
    return content, mime, ext


@login_required
@require_http_methods(["GET", "POST"])
def attachment_upload(request: HttpRequest, pk: int) -> HttpResponse:
    """Upload lampiran untuk transaksi."""
    txn = Transaction.objects.filter(pk=pk).first()
    if txn is None:
        raise Http404("Transaksi tidak ditemukan.")
    if txn.deleted_at is not None:
        raise Http404("Transaksi tidak ditemukan.")

    if request.method == "POST":
        file = request.FILES.get("file")
        try:
            content, mime, ext = _validate_upload(file)
        except DomainError as exc:
            flash.error(request, exc.message)
            return render(request, "ledger/_attachment_form.html", {"txn": txn}, status=200)

        # Save file to media/attachments/
        import os
        import uuid

        filename = f"{txn.pk}_{uuid.uuid4().hex[:8]}{ext}"
        save_path = os.path.join("attachments", filename)
        from django.core.files.storage import default_storage

        full_path = default_storage.save(save_path, file)
        default_storage.url(full_path)  # ensure accessible

        # Create attachment record
        from ledger.models import Attachment

        Attachment.objects.create(
            transaction=txn,
            file=full_path,
            original_name=file.name,
            mime_type=mime,
            size_bytes=len(content),
            uploaded_by=request.user,
        )

        flash.success(request, "Lampiran ditambahkan.")
        return redirect("transaction_detail", pk=txn.pk)

    return render(request, "ledger/_attachment_form.html", {"txn": txn})


@login_required
@require_http_methods(["GET", "POST"])
def attachment_delete(request: HttpRequest, pk: int, att_pk: int) -> HttpResponse:
    """Hapus lampiran (soft delete)."""
    txn = Transaction.objects.filter(pk=pk).first()
    if txn is None:
        raise Http404("Transaksi tidak ditemukan.")

    att = Attachment.objects.filter(pk=att_pk, transaction=txn).first()
    if att is None:
        raise Http404("Lampiran tidak ditemukan.")

    if request.method == "POST":
        att.soft_delete(actor=request.user)
        flash.success(request, "Lampiran dihapus.")
        return redirect("transaction_detail", pk=txn.pk)

    return render(
        request,
        "ledger/_attachment_confirm_delete.html",
        {"txn": txn, "att": att},
    )


@login_required
@require_GET
def attachment_download(request: HttpRequest, pk: int, att_pk: int) -> HttpResponse:
    """Unduh lampiran."""
    txn = Transaction.objects.filter(pk=pk).first()
    if txn is None:
        raise Http404("Transaksi tidak ditemukan.")

    att = Attachment.objects.filter(pk=att_pk, transaction=txn).first()
    if att is None:
        raise Http404("Lampiran tidak ditemukan.")

    if not default_storage.exists(att.file):
        raise Http404("File tidak ditemukan di storage.")

    response = HttpResponse(default_storage.open(att.file, "rb"), content_type=att.mime_type)
    response["Content-Disposition"] = f'attachment; filename="{att.original_name}"'
    return response


# --- PDF Investor Report (FR-27, FR-28) --------------------------------------


@login_required
@require_GET
def investor_pdf(request: HttpRequest) -> HttpResponse:
    """Generate PDF laporan investor (ID/EN) via WeasyPrint."""

    from core.models import CompanyProfile
    from core.utils.dates import format_date_long_id, today_wib

    # Parse parameters
    lang = request.GET.get("lang", "id")
    if lang not in ("id", "en"):
        lang = "id"

    period_type = request.GET.get("period", "monthly")
    anchor = _parse_date(request.GET.get("date")) or today_wib()

    # Get company profile
    profile = CompanyProfile.get_solo()

    # Get recap data based on period
    if period_type == "daily":
        result = daily_recap(anchor, anchor, None)
        period_label = format_date_long_id(anchor) if lang == "id" else anchor.strftime("%B %d, %Y")
    elif period_type == "weekly":
        from core.utils.periods import week

        week_range = week(anchor)
        start = week_range.start
        result = weekly_recap(start, None)
        if lang == "id":
            period_label = (
                f"Minggu {start.strftime('%d %B %Y')} – "
                f"{week_range.end.strftime('%d %B %Y')}"
            )
        else:
            period_label = (
                f"Week {start.strftime('%B %d, %Y')} – "
                f"{week_range.end.strftime('%B %d, %Y')}"
            )
    elif period_type == "yearly":
        result = yearly_recap(anchor.year, None)
        period_label = str(anchor.year)
    else:
        # monthly default
        result = monthly_recap(anchor, None)
        period_label = format_month_id(anchor) if lang == "id" else anchor.strftime("%B %Y")

    # Labels by language
    if lang == "en":
        labels = {
            "company": "Company",
            "period": "Period",
            "summary": "Summary",
            "income": "Income",
            "expense": "Expense",
            "non_operational": "Non-Operational",
            "net": "Net",
            "stock": "Stock",
            "opening": "Opening",
            "in_qty": "In",
            "out_qty": "Out",
            "adjustment": "Adjustment",
            "closing": "Closing",
            "unit": "Unit",
            "detail_transactions": "Transaction Details",
            "date": "Date",
            "category": "Category",
            "item": "Item",
            "type": "Type",
            "amount": "Amount",
            "qty": "Qty",
            "unit_label": "Unit",
            "generated_at": f"Generated on {today_wib().strftime('%Y-%m-%d %H:%M')}",
        }
        flow_labels = {"income": "Income", "expense": "Expense"}
    else:
        labels = {
            "company": "Perusahaan",
            "period": "Periode",
            "summary": "Ringkasan",
            "income": "Pemasukan",
            "expense": "Pengeluaran",
            "non_operational": "Mutasi Non-Operasional",
            "net": "Selisih",
            "stock": "Stok",
            "opening": "Saldo Awal",
            "in_qty": "Masuk",
            "out_qty": "Keluar",
            "adjustment": "Penyesuaian",
            "closing": "Saldo Akhir",
            "unit": "Satuan",
            "detail_transactions": "Detail Transaksi",
            "date": "Tanggal",
            "category": "Kategori",
            "item": "Item",
            "type": "Jenis",
            "amount": "Jumlah",
            "qty": "Qty",
            "unit_label": "Satuan",
            "generated_at": f"Dibuat pada {today_wib().strftime('%Y-%m-%d %H:%M')}",
        }
        flow_labels = {"income": "Pemasukan", "expense": "Pengeluaran"}

    # Build context for template
    context = {
        "profile": profile,
        "result": result,
        "labels": labels,
        "flow_labels": flow_labels,
        "period_label": period_label,
        "period_type": period_type,
        "lang": lang,
        "today": today_wib(),
        "format_money": format_id_number,
    }

    # Render HTML
    html_string = render_to_string("ledger/investor_pdf.html", context)

    # Generate PDF
    bio = BytesIO()
    HTML(string=html_string).write_pdf(bio)
    bio.seek(0)

    filename = f"investor_report_{period_type}_{period_label}_{today_wib().strftime('%Y%m%d')}.pdf"
    filename = filename.replace(" ", "_").replace("/", "-")

    response = HttpResponse(bio.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
