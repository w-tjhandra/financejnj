"""Definisi periode laporan (harian, mingguan ISO, bulanan, tahunan)."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

from .dates import MONTHS_ID_SHORT, add_months, month_start


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date

    def __iter__(self):
        yield self.start
        yield self.end

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def contains(self, value: date) -> bool:
        return self.start <= value <= self.end


def day(anchor: date) -> DateRange:
    return DateRange(anchor, anchor)


def week(anchor: date) -> DateRange:
    """Minggu ISO: Senin sampai Minggu."""
    start = anchor - timedelta(days=anchor.weekday())
    return DateRange(start, start + timedelta(days=6))


def month(anchor: date) -> DateRange:
    start = month_start(anchor)
    end = start.replace(day=calendar.monthrange(start.year, start.month)[1])
    return DateRange(start, end)


def year(anchor: date) -> DateRange:
    return DateRange(date(anchor.year, 1, 1), date(anchor.year, 12, 31))


def week_owner(anchor: date) -> tuple[int, int]:
    """Bulan pemilik minggu = bulan hari Senin (BR-09)."""
    monday = week(anchor).start
    return monday.year, monday.month


def weeks_in_month(year: int, month_number: int) -> list[date]:
    """Senin yang jatuh di bulan itu; dipakai navigator/export mingguan."""
    first = date(year, month_number, 1)
    first_monday = first + timedelta(days=(7 - first.weekday()) % 7)
    weeks: list[date] = []
    current = first_monday
    while current.month == month_number:
        weeks.append(current)
        current += timedelta(days=7)
    return weeks


def period_start_before_opening(period_start: date, opening_balance_date: date | None) -> bool:
    """K-01: periode yang mulai tepat pada opening date BUKAN pra-opening."""
    if opening_balance_date is None:
        return False
    return period_start < opening_balance_date


def next_month(value: date) -> date:
    return add_months(month_start(value), 1)


def period_key(value: date) -> str:
    """Kode periode untuk log/extra, mis. 2026-09 (bukan untuk pesan UI)."""
    return f"{value.year:04d}-{value.month:02d}"


def format_period_label(start: date, end: date) -> str:
    """Contoh: Minggu ke-44 (26 Okt – 01 Nov 2026)."""
    iso_week = start.isocalendar().week
    if start.year == end.year:
        span = (
            f"{start.day:02d} {MONTHS_ID_SHORT[start.month - 1]} – "
            f"{end.day:02d} {MONTHS_ID_SHORT[end.month - 1]} {end.year}"
        )
    else:
        span = (
            f"{start.day:02d} {MONTHS_ID_SHORT[start.month - 1]} {start.year} – "
            f"{end.day:02d} {MONTHS_ID_SHORT[end.month - 1]} {end.year}"
        )
    return f"Minggu ke-{iso_week} ({span})"
