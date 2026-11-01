"""Audit log viewer (BR-14, AC-32.x) - read-only."""

from __future__ import annotations

from datetime import date

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from audit.constants import ACTION_VALUES, HISTORY_ENTITIES
from audit.models import AuditLog
from core.utils.dates import today_wib
from core.utils.numbers import format_id_number

ACTION_LABELS = {
    "create": "Dicatat",
    "update": "Diubah",
    "delete": "Dihapus",
}


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


@login_required
@require_GET
def audit_log_list(request: HttpRequest) -> HttpResponse:
    """Daftar riwayat transaksi dan pindah dana."""
    action = request.GET.get("action", "").strip()
    date_from = _parse_date(request.GET.get("date_from"))
    date_to = _parse_date(request.GET.get("date_to"))
    q = request.GET.get("q", "").strip()

    qs = AuditLog.objects.filter(entity__in=HISTORY_ENTITIES).select_related("user")

    if action and action in ACTION_VALUES:
        qs = qs.filter(action=action)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    if q:
        # Search in entity_id, before/after/extra JSON fields
        qs = qs.filter(
            Q(entity_id__icontains=q)
            | Q(before__icontains=q)
            | Q(after__icontains=q)
            | Q(extra__icontains=q)
        )

    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get("page", 1))

    return render(
        request,
        "audit/log_list.html",
        {
            "page": page,
            "actions": ACTION_LABELS.items(),
            "selected_action": action,
            "date_from": date_from.isoformat() if date_from else "",
            "date_to": date_to.isoformat() if date_to else "",
            "q": q,
        },
    )


@login_required
@require_GET
def audit_log_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Detail satu perubahan transaksi atau pindah dana."""
    log = (
        AuditLog.objects.filter(entity__in=HISTORY_ENTITIES)
        .select_related("user")
        .filter(pk=pk)
        .first()
    )
    if not log:
        return render(request, "404.html", status=404)

    before = log.before or {}
    after = log.after or {}
    all_keys = set(before.keys()) | set(after.keys())

    diff = []
    for key in sorted(all_keys):
        b = before.get(key)
        a = after.get(key)
        if b != a:
            diff.append(
                {
                    "field": key,
                    "before": format_id_number(b) if isinstance(b, str) and b.isdigit() else b,
                    "after": format_id_number(a) if isinstance(a, str) and a.isdigit() else a,
                }
            )

    return render(
        request,
        "audit/log_detail.html",
        {
            "log": log,
            "diff": diff,
            "before": before,
            "after": after,
            "extra": log.extra or {},
        },
    )


@login_required
@require_GET
def audit_export(request: HttpRequest) -> HttpResponse:
    """Export audit log as XLSX."""
    from io import BytesIO

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    action = request.GET.get("action", "").strip()
    date_from = _parse_date(request.GET.get("date_from"))
    date_to = _parse_date(request.GET.get("date_to"))

    qs = AuditLog.objects.filter(entity__in=HISTORY_ENTITIES).select_related("user")
    if action and action in ACTION_VALUES:
        qs = qs.filter(action=action)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)

    wb = Workbook()
    ws = wb.active
    ws.title = "Riwayat transaksi"

    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )
    header_style = {
        "font": Font(bold=True, color="FFFFFF"),
        "fill": PatternFill(start_color="10B981", end_color="10B981", fill_type="solid"),
        "alignment": Alignment(horizontal="center", vertical="center", wrap_text=True),
        "border": thin_border,
    }
    cell_style = {
        "alignment": Alignment(horizontal="left", vertical="center", wrap_text=True),
        "border": thin_border,
    }

    headers = [
        "Waktu",
        "Jenis",
        "Nomor",
        "Aktivitas",
        "Pengguna",
        "Sebelum",
        "Sesudah",
        "Catatan tambahan",
    ]
    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        for k, v in header_style.items():
            setattr(cell, k, v)

    row = 2
    for log in qs.iterator(chunk_size=100):
        ws.cell(row=row, column=1, value=log.created_at.strftime("%Y-%m-%d %H:%M:%S"))
        ws.cell(
            row=row,
            column=2,
            value="Pindah dana" if log.entity == "account_transfer" else "Transaksi",
        )
        ws.cell(row=row, column=3, value=log.entity_id)
        ws.cell(
            row=row,
            column=4,
            value=ACTION_LABELS.get(log.action, log.action),
        )
        ws.cell(row=row, column=5, value=str(log.user) if log.user else "-")
        ws.cell(row=row, column=6, value=str(log.before or ""))
        ws.cell(row=row, column=7, value=str(log.after or ""))
        ws.cell(row=row, column=8, value=str(log.extra or ""))

        for col_idx in range(1, 9):
            cell = ws.cell(row=row, column=col_idx)
            for k, v in cell_style.items():
                setattr(cell, k, v)
        row += 1

    for col in ws.columns:
        max_len = 12
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            if cell.value:
                max_len = max(max_len, min(len(str(cell.value)) + 2, 60))
        ws.column_dimensions[col_letter].width = max_len

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)

    today = today_wib()
    resp = HttpResponse(
        bio.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="riwayat_transaksi_{today:%Y%m%d}.xlsx"'
    return resp
