from __future__ import annotations

from datetime import datetime

from django.utils import timezone

from core.models import PeriodLock
from core.services.locks import lock_period, period_start_date
from core.types import RequestMeta
from core.utils.dates import add_months, month_start, today_wib


def maybe_auto_lock_previous_period(now: datetime | None = None) -> PeriodLock | None:
    """Lock the previous month after 00:05 WIB on the first day of a month."""
    local_now = timezone.localtime(now) if now is not None else timezone.localtime()
    if local_now.day == 1 and (local_now.hour, local_now.minute) < (0, 5):
        return None

    today = local_now.date()
    previous_month = add_months(month_start(today), -1)
    first_month = month_start(period_start_date(today_wib()))
    if previous_month < first_month:
        return None

    if PeriodLock.objects.filter(period=previous_month).exists():
        return None

    return lock_period(
        previous_month,
        meta=RequestMeta(user_agent="automatic monthly close"),
        source="automatic",
    )
