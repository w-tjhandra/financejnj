"""Laporan rekap 4 periode (S-10…S-13, FR-16…FR-26)."""

from __future__ import annotations

from datetime import date
from io import BytesIO

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from core.utils.dates import month_start, today_wib
from core.utils.periods import week
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


def _category_id(request: HttpRequest) -> int | None:
    raw = request.GET.get("category") or ""
    return int(raw) if raw.isdigit() else None


def _thin_border():
    return Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )


def _header_style():
    return {
        "font": Font(bold=True, color="FFFFFF"),
        "fill": PatternFill(start_color="10B981", end_color="10B981", fill_type="solid"),
        "alignment": Alignment(horizontal="center", vertical="center", wrap_text=True),
        "border": _thin_border(),
    }


def _number_style():
    return {
        "alignment": Alignment(horizontal="right"),
        "border": _thin_border(),
    }


def _text_style():
    return {
        "alignment": Alignment(horizontal="left", vertical="center"),
        "border": _thin_border(),
    }


def _write_header_row(ws, row, headers, style_fn=_header_style):
    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=row, column=col_idx, value=header)
        for k, v in style_fn().items():
            setattr(cell, k, v)


def _auto_width(ws, min_width=10, max_width=40):
    for col in ws.columns:
        max_len = min_width
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            if cell.value:
                max_len = max(max_len, min(len(str(cell.value)) + 2, max_width))
        ws.column_dimensions[col_letter].width = max_len


@login_required
@require_GET
def dashboard(request: HttpRequest) -> HttpResponse:
    """S-10…S-13: Halaman dashboard ringkasan."""
    return render(request, "reports/dashboard.html")


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


def _export_recap_xlsx(request: HttpRequest, period_type: str) -> HttpResponse:
    """Generate XLSX export for any recap period type."""
    wb = Workbook()

    # Parse parameters
    category_id = _category_id(request)
    today = today_wib()

    if period_type == "daily":
        date_from = _parse_date(request.GET.get("date_from")) or today
        date_to = _parse_date(request.GET.get("date_to")) or today
        if date_from > date_to:
            date_from = date_to = today
        result = daily_recap(date_from, date_to, category_id)
        filename = f"rekap_harian_{date_from:%Y%m%d}_{date_to:%Y%m%d}.xlsx"
        period_label = f"{date_from:%d/%m/%Y} – {date_to:%d/%m/%Y}"
    elif period_type == "weekly":
        anchor = _parse_date(request.GET.get("week")) or today
        start = week(anchor).start
        result = weekly_recap(start, category_id)
        filename = f"rekap_mingguan_{start:%Y%m%d}.xlsx"
        period_label = f"Minggu {start:%d/%m/%Y} – {(start.replace(day=start.day+6)):%d/%m/%Y}"
    elif period_type == "monthly":
        anchor = _parse_date(request.GET.get("month")) or today
        result = monthly_recap(anchor, category_id)
        filename = f"rekap_bulanan_{anchor:%Y%m}.xlsx"
        period_label = f"Bulan {anchor:%m/%Y}"
    elif period_type == "yearly":
        raw_year = (request.GET.get("year") or "").strip()
        year = today.year
        if raw_year.isdigit() and 1900 <= int(raw_year) <= 2100:
            year = int(raw_year)
        result = yearly_recap(year, category_id)
        filename = f"rekap_tahunan_{year}.xlsx"
        period_label = f"Tahun {year}"
    else:
        return HttpResponse("Invalid period type", status=400)

    cat = Category.objects.filter(pk=category_id).first() if category_id else None
    cat_name = f" ({cat.name})" if cat else " (Semua Kategori)"

    # Sheet 1: Ringkasan (4 baris)
    ws1 = wb.active
    ws1.title = "Ringkasan"
    _write_header_row(ws1, 1, ["Rekap" + cat_name, period_label])
    ws1.merge_cells("A1:B1")
    _write_header_row(ws1, 2, ["Kategori", "Jumlah"])
    row = 3
    for sr in result.summary:
        cell_k = ws1.cell(row=row, column=1, value=sr.label)
        cell_v = ws1.cell(row=row, column=2, value=sr.amount)
        for k, v in _text_style().items():
            setattr(cell_k, k, v)
        for k, v in _number_style().items():
            setattr(cell_v, k, v)
        cell_v.number_format = '#,##0.00'
        row += 1
    _auto_width(ws1)

    # Sheet 2: Pemasukan
    ws2 = wb.create_sheet("Pemasukan")
    _write_header_row(ws2, 1, ["Pemasukan" + cat_name, period_label])
    ws2.merge_cells("A1:C1")
    _write_header_row(ws2, 2, ["Tanggal", "Item", "Jumlah"])
    row = 3
    for detail in result.income_detail:
        ws2.cell(row=row, column=1, value=detail.date.strftime("%d/%m/%Y"))
        ws2.cell(row=row, column=2, value=detail.item_name)
        cell_v = ws2.cell(row=row, column=3, value=detail.amount)
        for k, v in _number_style().items():
            setattr(cell_v, k, v)
        cell_v.number_format = '#,##0.00'
        row += 1
    _auto_width(ws2)

    # Sheet 3: Pengeluaran
    ws3 = wb.create_sheet("Pengeluaran")
    _write_header_row(ws3, 1, ["Pengeluaran" + cat_name, period_label])
    ws3.merge_cells("A1:C1")
    _write_header_row(ws3, 2, ["Tanggal", "Item", "Jumlah"])
    row = 3
    for detail in result.expense_detail:
        ws3.cell(row=row, column=1, value=detail.date.strftime("%d/%m/%Y"))
        ws3.cell(row=row, column=2, value=detail.item_name)
        cell_v = ws3.cell(row=row, column=3, value=detail.amount)
        for k, v in _number_style().items():
            setattr(cell_v, k, v)
        cell_v.number_format = '#,##0.00'
        row += 1
    _auto_width(ws3)

    # Sheet 4: Stok
    ws4 = wb.create_sheet("Stok")
    _write_header_row(ws4, 1, ["Stok" + cat_name, period_label])
    ws4.merge_cells("A1:F1")
    _write_header_row(ws4, 2, ["Kode", "Nama", "Satuan", "Saldo Awal", "Masuk", "Keluar", "Penyesuaian", "Saldo Akhir"])
    row = 3
    for stock in result.stock:
        ws4.cell(row=row, column=1, value=stock.kode)
        ws4.cell(row=row, column=2, value=stock.nama)
        ws4.cell(row=row, column=3, value=stock.satuan)
        for col_idx, val in enumerate([stock.opening, stock.in_qty, stock.out_qty, stock.adj, stock.closing], 4):
            cell = ws4.cell(row=row, column=col_idx, value=val)
            for k, v in _number_style().items():
                setattr(cell, k, v)
            cell.number_format = '#,##0.000'
        row += 1
    _auto_width(ws4)

    # Sheet 5: Detail Transaksi
    ws5 = wb.create_sheet("Detail Transaksi")
    _write_header_row(ws5, 1, ["Detail Transaksi" + cat_name, period_label])
    ws5.merge_cells("A1:G1")
    _write_header_row(ws5, 2, ["Tanggal", "Kategori", "Item", "Jenis", "Jumlah", "Qty", "Satuan"])
    row = 3
    for detail in result.income_detail + result.expense_detail:
        ws5.cell(row=row, column=1, value=detail.date.strftime("%d/%m/%Y"))
        ws5.cell(row=row, column=2, value=detail.category_name)
        ws5.cell(row=row, column=3, value=detail.item_name)
        ws5.cell(row=row, column=4, value="Pemasukan" if detail.flow == "income" else "Pengeluaran")
        cell_amt = ws5.cell(row=row, column=5, value=detail.amount)
        for k, v in _number_style().items():
            setattr(cell_amt, k, v)
        cell_amt.number_format = '#,##0.00'
        if detail.qty is not None:
            cell_qty = ws5.cell(row=row, column=6, value=detail.qty)
            for k, v in _number_style().items():
                setattr(cell_qty, k, v)
            cell_qty.number_format = '#,##0.000'
        ws5.cell(row=row, column=7, value=detail.unit or "")
        row += 1
    _auto_width(ws5)

    # Write to response
    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    resp = HttpResponse(
        bio.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


@login_required
@require_GET
def export_daily_xlsx(request: HttpRequest) -> HttpResponse:
    return _export_recap_xlsx(request, "daily")


@login_required
@require_GET
def export_weekly_xlsx(request: HttpRequest) -> HttpResponse:
    return _export_recap_xlsx(request, "weekly")


@login_required
@require_GET
def export_monthly_xlsx(request: HttpRequest) -> HttpResponse:
    return _export_recap_xlsx(request, "monthly")


@login_required
@require_GET
def export_yearly_xlsx(request: HttpRequest) -> HttpResponse:
    return _export_recap_xlsx(request, "yearly")