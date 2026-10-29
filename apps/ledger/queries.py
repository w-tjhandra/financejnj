"""Query untuk daftar transaksi & pencarian (S-04, FR-13)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from django.db.models import Q
from django.utils import timezone

from ledger.models import Transaction
from master.models import Category, Item


@dataclass(frozen=True)
class TransactionListFilters:
    """Filter pencarian transaksi."""

    date_from: date | None = None
    date_to: date | None = None
    flow: Literal["income", "expense"] | None = None
    category_id: int | None = None
    item_id: int | None = None
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    keyword: str | None = None
    show_deleted: bool = False
    sort: Literal[
        "date_desc",
        "date_asc",
        "amount_desc",
        "amount_asc",
        "created_desc",
        "created_asc",
    ] = "date_desc"
    page: int = 1
    page_size: int = 25


@dataclass(frozen=True)
class TransactionListResult:
    """Hasil query daftar transaksi."""

    transactions: list[Transaction]
    total_count: int
    total_active: int
    page: int
    page_size: int
    total_pages: int
    filters: TransactionListFilters


def _active_items_qs(flow: str | None):
    """Item aktif, filter arus bila diberikan."""
    qs = Item.objects.filter(is_active=True).select_related("default_category", "stock_item")
    if flow:
        qs = qs.filter(flow=flow)
    return qs


def _category_choices(flow: str | None) -> list[Category]:
    """Kategori aktif yang punya item aktif untuk arus tertentu."""
    items_qs = _active_items_qs(flow)
    category_ids = items_qs.values_list("default_category_id", flat=True).distinct()
    return list(Category.objects.filter(pk__in=category_ids, is_active=True).order_by("code"))


def _resolve_category_rollup(category_id: int | None) -> list[int] | None:
    """
    Resolve kategori filter dengan roll-up LAYER→AFKIR (D5).
    - category_id None → tidak filter
    - kategori LAYER → include LAYER + AFKIR
    - kategori AFKIR → hanya AFKIR
    - lain → kategori itu sendiri
    """
    if category_id is None:
        return None
    cat = Category.objects.filter(pk=category_id).first()
    if cat is None:
        return None
    if cat.code == "LAYER":
        return list(
            Category.objects.filter(Q(code="LAYER") | Q(code="AFKIR")).values_list("pk", flat=True)
        )
    if cat.code == "AFKIR":
        return [cat.pk]
    return [cat.pk]


def transaction_list(filters: TransactionListFilters) -> TransactionListResult:
    """
    Query daftar transaksi dengan filter, pagination, dan roll-up kategori.
    Mengembalikan object + total count (hanya aktif untuk footer).
    """
    qs = Transaction.all_objects if filters.show_deleted else Transaction.objects

    # Base queryset dengan related
    qs = qs.select_related("category", "item", "item__stock_item", "account")

    # Rentang tanggal default: bulan berjalan WIB
    if filters.date_from is None and filters.date_to is None:
        today = timezone.localdate()
        month_start_date = date(today.year, today.month, 1)
        if today.month == 12:
            month_end_date = date(today.year + 1, 1, 1) - timezone.timedelta(days=1)
        else:
            month_end_date = date(today.year, today.month + 1, 1) - timezone.timedelta(days=1)
        filters = TransactionListFilters(
            date_from=month_start_date,
            date_to=month_end_date,
            flow=filters.flow,
            category_id=filters.category_id,
            item_id=filters.item_id,
            amount_min=filters.amount_min,
            amount_max=filters.amount_max,
            keyword=filters.keyword,
            show_deleted=filters.show_deleted,
            sort=filters.sort,
            page=filters.page,
            page_size=filters.page_size,
        )

    if filters.date_from:
        qs = qs.filter(date__gte=filters.date_from)
    if filters.date_to:
        qs = qs.filter(date__lte=filters.date_to)

    if filters.flow:
        qs = qs.filter(flow=filters.flow)

    # Kategori roll-up
    category_pks = _resolve_category_rollup(filters.category_id)
    if category_pks is not None:
        qs = qs.filter(category_id__in=category_pks)

    if filters.item_id:
        qs = qs.filter(item_id=filters.item_id)

    if filters.amount_min is not None:
        qs = qs.filter(amount__gte=filters.amount_min)
    if filters.amount_max is not None:
        qs = qs.filter(amount__lte=filters.amount_max)

    if filters.keyword:
        qs = qs.filter(Q(notes__icontains=filters.keyword))

    # Sort
    sort_map = {
        "date_desc": "-date",
        "date_asc": "date",
        "amount_desc": "-amount",
        "amount_asc": "amount",
        "created_desc": "-created_at",
        "created_asc": "created_at",
    }
    qs = qs.order_by(sort_map.get(filters.sort, "-date"))

    # Total aktif untuk footer
    if filters.show_deleted:
        total_active = qs.filter(deleted_at__isnull=True).count()
    else:
        total_active = qs.count()

    # Pagination
    total_count = qs.count()
    page_size = filters.page_size
    page = max(1, filters.page)
    start = (page - 1) * page_size
    end = start + page_size
    transactions = list(qs[start:end])
    total_pages = (total_count + page_size - 1) // page_size

    return TransactionListResult(
        transactions=transactions,
        total_count=total_count,
        total_active=total_active,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        filters=filters,
    )


def get_filter_options(flow: str | None = None) -> dict:
    """Opsi untuk filter form: kategori & item."""
    return {
        "categories": _category_choices(flow),
        "items": list(_active_items_qs(flow)),
    }
