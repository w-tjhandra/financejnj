"""Periode harian/mingguan ISO/bulanan/tahunan dan helper minggu."""

from datetime import date

from core.utils.dates import format_date_id, format_month_id
from core.utils.periods import (
    day,
    format_period_label,
    month,
    next_month,
    period_key,
    period_start_before_opening,
    week,
    week_owner,
    weeks_in_month,
    year,
)


def test_periode_harian():
    rentang = day(date(2026, 10, 29))
    assert (rentang.start, rentang.end) == (date(2026, 10, 29), date(2026, 10, 29))
    assert rentang.days == 1
    assert rentang.contains(date(2026, 10, 29))
    assert not rentang.contains(date(2026, 10, 30))


def test_periode_mingguan_senin_minggu():
    rentang = week(date(2026, 10, 29))  # Kamis
    assert (rentang.start, rentang.end) == (date(2026, 10, 26), date(2026, 11, 1))
    assert rentang.days == 7


def test_periode_mingguan_lintas_tahun():
    rentang = week(date(2025, 12, 31))
    assert (rentang.start, rentang.end) == (date(2025, 12, 29), date(2026, 1, 4))
    assert week_owner(date(2026, 1, 1)) == (2025, 12)


def test_periode_bulanan_termasuk_tahun_kabisat():
    rentang = month(date(2024, 2, 10))
    assert (rentang.start, rentang.end) == (date(2024, 2, 1), date(2024, 2, 29))
    assert rentang.days == 29


def test_periode_tahunan():
    rentang = year(date(2026, 10, 29))
    assert (rentang.start, rentang.end) == (date(2026, 1, 1), date(2026, 12, 31))
    assert rentang.days == 365


def test_weeks_in_month_hanya_senin_di_bulan_itu():
    assert weeks_in_month(2026, 10) == [
        date(2026, 10, 5),
        date(2026, 10, 12),
        date(2026, 10, 19),
        date(2026, 10, 26),
    ]
    assert weeks_in_month(2026, 6) == [
        date(2026, 6, 1),
        date(2026, 6, 8),
        date(2026, 6, 15),
        date(2026, 6, 22),
        date(2026, 6, 29),
    ]


def test_period_start_before_opening_strict_kurang_dari():
    opening = date(2026, 9, 1)
    assert period_start_before_opening(date(2026, 8, 1), opening) is True
    assert period_start_before_opening(date(2026, 9, 1), opening) is False
    assert period_start_before_opening(date(2026, 10, 1), opening) is False
    assert period_start_before_opening(date(2026, 8, 1), None) is False


def test_label_bulan_dan_periode_indonesia():
    assert format_month_id(date(2026, 9, 1)) == "September 2026"
    assert format_date_id(date(2026, 10, 28)) == "28 Okt 2026"
    assert format_period_label(date(2026, 10, 26), date(2026, 11, 1)) == (
        "Minggu ke-44 (26 Okt – 01 Nov 2026)"
    )
    assert format_period_label(date(2025, 12, 29), date(2026, 1, 4)) == (
        "Minggu ke-1 (29 Des 2025 – 04 Jan 2026)"
    )


def test_next_month_dan_period_key():
    assert next_month(date(2026, 12, 15)) == date(2027, 1, 1)
    assert period_key(date(2026, 9, 15)) == "2026-09"
