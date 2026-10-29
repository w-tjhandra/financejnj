"""Kunci periode berantai (D4, K-00 Opsi A).

`chain_gap` sengaja murni (tanpa query) agar mudah diuji; guard yang menyentuh
DB ada di `assert_date_editable`.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from core import messages
from core.errors import PeriodLocked
from core.models import PeriodLock
from core.utils.dates import add_months, month_start


def chain_gap(
    target: date,
    *,
    locked_periods: Iterable[date],
    opening_balance_date: date,
) -> date | None:
    """Bulan pertama yang belum terkunci antara opening dan `target`.

    ``None`` berarti rantai lengkap (atau target berada sebelum opening).
    """
    target_month = month_start(target)
    locked = {month_start(period) for period in locked_periods}
    anchor = month_start(opening_balance_date)
    if locked:
        anchor = min(anchor, min(locked))

    if target_month < anchor:
        return None

    current = anchor
    while current < target_month:
        if current not in locked:
            return current
        current = add_months(current, 1)
    return None


def max_locked_period() -> date | None:
    """Bulan terkunci terbaru; menutup seluruh bulan sebelumnya (D4)."""
    return (
        PeriodLock.objects.filter(is_locked=True)
        .order_by("-period")
        .values_list("period", flat=True)
        .first()
    )


def is_date_editable(value: date) -> bool:
    max_locked = max_locked_period()
    if max_locked is None:
        return True
    return value >= add_months(max_locked, 1)


def assert_date_editable(value: date, *, operation: str = "write") -> None:
    """Tolak tulisan yang menyentuh bulan terkunci (BR-12).

    ``operation`` hanya untuk konteks log; pesan pengguna tetap sama.
    """
    max_locked = max_locked_period()
    if max_locked is not None and value < add_months(max_locked, 1):
        raise PeriodLocked(messages.period_locked(max_locked), period=max_locked)
