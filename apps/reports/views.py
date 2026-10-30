"""Laporan rekap 4 periode (S-10…S-13, FR-16…FR-26)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.db.models.functions import TruncDate
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from core.utils.dates import format_month_id, month_start, today_wib
from core.utils.numbers import format_money
from core.utils.periods import week
from ledger.models import Account, Transaction
from master.models import Category
from reports.queries import daily_recap, monthly_recap, weekly_recap, yearly_recap

FLOW_LABELS = {"income": "Pemasukan", "expense": "Pengeluaran"}


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


@login_required
@require_GET
def dashboard(request: HttpRequest) -> HttpResponse:
    """S-10…S-13: Halaman dashboard ringkasan."""
    today = today_wib()
    month = month_start(today)
    account = Account.current()
    reporting_start = max(month, account.opening_balance_date) if account else month
    transactions = Transaction.objects.filter(
        date__gte=reporting_start,
        date__lte=today,
        is_opening_correction=False,
    )
    totals = transactions.aggregate(
        income=Sum("amount", filter=Q(flow="income")),
        expense=Sum("amount", filter=Q(flow="expense")),
    )
    income = totals["income"] or Decimal("0")
    expense = totals["expense"] or Decimal("0")
    daily_totals = {
        row["day"].day: row
        for row in transactions.annotate(day=TruncDate("date"))
        .values("day")
        .annotate(
            income=Sum("amount", filter=Q(flow="income")),
            expense=Sum("amount", filter=Q(flow="expense")),
        )
        .order_by("day")
    }
    expense_categories = list(
        transactions.filter(flow="expense")
        .values("category__name")
        .annotate(amount=Sum("amount"))
        .order_by("-amount", "category__name")[:5]
    )
    cashflow_chart = {
        "labels": [f"{day:02}" for day in range(1, today.day + 1)],
        "income": [
            float(daily_totals.get(day, {}).get("income") or 0)
            for day in range(1, today.day + 1)
        ],
        "expense": [
            float(daily_totals.get(day, {}).get("expense") or 0)
            for day in range(1, today.day + 1)
        ],
    }
    category_chart = {
        "labels": [row["category__name"] for row in expense_categories],
        "values": [float(row["amount"]) for row in expense_categories],
    }
    return render(
        request,
        "reports/dashboard.html",
        {
            "dashboard_month_label": format_month_id(month),
            "dashboard_income_display": format_money(income),
            "dashboard_expense_display": format_money(expense),
            "dashboard_net_display": format_money(income - expense),
            "dashboard_income": income,
            "dashboard_expense": expense,
            "dashboard_net": income - expense,
            "cashflow_chart": cashflow_chart,
            "category_chart": category_chart,
            "expense_category_count": len(expense_categories),
        },
    )


def _category_id(request: HttpRequest) -> int | None:
    raw = request.GET.get("category") or ""
    return int(raw) if raw.isdigit() else None


@login_required
@require_GET
def daily_recap_view(request: HttpRequest) -> HttpResponse:
    """S-10: Rekap harian (empat baris + detail per item)."""
    date_from = _parse_date(request.GET.get("date_from")) or today_wib()
    date_to = _parse_date(request.GET.get("date_to")) or today_wib()
    if date_from > date_to:
        date_from = date_to = today_wib()
    category_id = _category_id(request)
    result = daily_recap(date_from, date_to, category_id)
    return render(
        request,
        "reports/daily_recap.html",
        {
            "result": result,
            "categories": Category.objects.filter(is_active=True).order_by("sort_order", "id"),
            "selected_category": category_id,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "FLOW_LABELS": FLOW_LABELS,
        },
    )


@login_required
@require_GET
def weekly_recap_view(request: HttpRequest) -> HttpResponse:
    """S-11: Rekap mingguan (ISO Senin–Minggu)."""
    anchor = _parse_date(request.GET.get("week")) or today_wib()
    start = week(anchor).start
    result = weekly_recap(start, _category_id(request))
    return render(
        request,
        "reports/weekly_recap.html",
        {
            "result": result,
            "categories": Category.objects.filter(is_active=True).order_by("sort_order", "id"),
            "selected_category": _category_id(request),
            "week": start.isoformat(),
            "FLOW_LABELS": FLOW_LABELS,
        },
    )


@login_required
@require_GET
def monthly_recap_view(request: HttpRequest) -> HttpResponse:
    """S-12: Rekap bulanan (empat baris + gaji)."""
    anchor = _parse_date(request.GET.get("month")) or today_wib()
    result = monthly_recap(anchor, _category_id(request))
    return render(
        request,
        "reports/monthly_recap.html",
        {
            "result": result,
            "categories": Category.objects.filter(is_active=True).order_by("sort_order", "id"),
            "selected_category": _category_id(request),
            "month": month_start(anchor).isoformat(),
            "FLOW_LABELS": FLOW_LABELS,
        },
    )


@login_required
@require_GET
def yearly_recap_view(request: HttpRequest) -> HttpResponse:
    """S-13: Rekap tahunan (per bulan + per kategori, empat baris)."""
    raw_year = (request.GET.get("year") or "").strip()
    year = today_wib().year
    if raw_year.isdigit() and 1900 <= int(raw_year) <= 2100:
        year = int(raw_year)
    result = yearly_recap(year, _category_id(request))
    return render(
        request,
        "reports/yearly_recap.html",
        {
            "result": result,
            "categories": Category.objects.filter(is_active=True).order_by("sort_order", "id"),
            "selected_category": _category_id(request),
            "year": year,
            "FLOW_LABELS": FLOW_LABELS,
        },
    )
