"""Helper tanggal & nama bulan Indonesia (tanpa locale OS)."""

from __future__ import annotations

import calendar
from datetime import date, datetime

from django.utils import timezone

MONTHS_ID = (
    "Januari",
    "Februari",
    "Maret",
    "April",
    "Mei",
    "Juni",
    "Juli",
    "Agustus",
    "September",
    "Oktober",
    "November",
    "Desember",
)

MONTHS_ID_SHORT = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "Mei",
    "Jun",
    "Jul",
    "Agu",
    "Sep",
    "Okt",
    "Nov",
    "Des",
)


def today_wib() -> date:
    """Tanggal kalender hari ini menurut TIME_ZONE (Asia/Jakarta)."""
    return timezone.localdate()


def month_start(value: date) -> date:
    return value.replace(day=1)


def add_months(value: date, months: int) -> date:
    """Geser bulan dengan aman; hari dijepit ke akhir bulan tujuan."""
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def as_date(value: date | datetime) -> date:
    if isinstance(value, datetime):
        return timezone.localtime(value).date() if timezone.is_aware(value) else value.date()
    return value


def format_month_id(value: date | datetime) -> str:
    value = as_date(value)
    return f"{MONTHS_ID[value.month - 1]} {value.year}"


def format_date_id(value: date | datetime) -> str:
    value = as_date(value)
    return f"{value.day} {MONTHS_ID_SHORT[value.month - 1]} {value.year}"


def format_date_long_id(value: date | datetime) -> str:
    value = as_date(value)
    return f"{value.day} {MONTHS_ID[value.month - 1]} {value.year}"


def format_date_short(value: date | datetime) -> str:
    value = as_date(value)
    return f"{value.day:02d}/{value.month:02d}/{value.year:04d}"


def format_datetime_wib(value: datetime) -> str:
    local = timezone.localtime(value)
    return f"{format_date_id(local)} {local:%H:%M} WIB"
