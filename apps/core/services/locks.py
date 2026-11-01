"""Kunci periode berantai (D4, K-00 Opsi A).

`chain_gap` sengaja murni (tanpa query) agar mudah diuji; guard yang menyentuh
DB ada di `assert_date_editable`. Operasi lock/unlock diaudit di transaksi DB
yang sama dengan perubahan status.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from django.apps import apps
from django.db import transaction
from django.utils import timezone

from core import messages
from core.errors import AlreadyLocked, AlreadyUnlocked, DomainError, PeriodLocked
from core.models import PeriodLock
from core.utils.dates import add_months, month_start
from core.utils.periods import period_key

UNLOCK_REASON_MIN = 10
UNLOCK_REASON_MAX = 300


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
    del operation
    max_locked = max_locked_period()
    if max_locked is not None and value < add_months(max_locked, 1):
        raise PeriodLocked(messages.period_locked(max_locked), period=max_locked)


@dataclass(frozen=True)
class LockStatus:
    period: date
    is_locked: bool
    locked_at: object | None = None
    locked_by_id: int | None = None
    unlocked_at: object | None = None
    unlocked_by_id: int | None = None
    unlock_reason: str | None = None
    unlock_count: int = 0
    chain_gap: date | None = None

    @property
    def was_reopened(self) -> bool:
        return not self.is_locked and self.unlocked_at is not None


def period_start_date(fallback: date) -> date:
    """Bulan pertama yang dapat dikunci, setelah aplikasi dan saldo awal siap."""
    account_model = apps.get_model("ledger", "Account")
    opening_date = (
        account_model.objects.order_by("pk").values_list("opening_balance_date", flat=True).first()
    )
    profile_model = apps.get_model("core", "CompanyProfile")
    application_start = (
        profile_model.objects.order_by("pk")
        .values_list("application_start_date", flat=True)
        .first()
    )
    return max(opening_date or fallback, application_start or fallback)


def _locked_periods() -> list[date]:
    return list(PeriodLock.objects.filter(is_locked=True).values_list("period", flat=True))


def _period_counts(period: date) -> tuple[int, int]:
    """Jumlah transaksi & movement aktif pada bulan tersebut (untuk audit)."""
    start = month_start(period)
    end = add_months(start, 1)
    transaction_model = apps.get_model("ledger", "Transaction")
    movement_model = apps.get_model("stock", "StockMovement")
    transactions = transaction_model.objects.filter(date__gte=start, date__lt=end).count()
    movements = movement_model.objects.filter(date__gte=start, date__lt=end).count()
    return transactions, movements


def _audit(entity_id: int | None, action: str, *, actor, before, after, extra, meta) -> None:
    # `core` sengaja tidak mengimpor `audit` di tingkat modul (arah dependensi);
    # pintu audit resmi tetap `audit.service.log_audit`.
    from audit.service import log_audit

    log_audit(
        entity="period_lock",
        entity_id=entity_id,
        action=action,
        actor=actor,
        before=before,
        after=after,
        extra=extra,
        meta=meta,
    )


def _snapshot(row: PeriodLock | None) -> dict | None:
    if row is None:
        return None
    return {
        "period": row.period.isoformat(),
        "is_locked": row.is_locked,
        "locked_at": row.locked_at.isoformat() if row.locked_at else None,
        "locked_by": row.locked_by_id,
        "unlocked_at": row.unlocked_at.isoformat() if row.unlocked_at else None,
        "unlocked_by": row.unlocked_by_id,
        "unlock_reason": row.unlock_reason,
        "unlock_count": row.unlock_count,
    }


def period_status(period: date) -> LockStatus:
    """Status satu bulan; termasuk indikator bulan yang pernah dibuka."""
    period = month_start(period)
    row = PeriodLock.objects.filter(period=period).first()
    locked = _locked_periods()
    gap = chain_gap(
        period,
        locked_periods=locked,
        opening_balance_date=period_start_date(period),
    )
    if row is None:
        return LockStatus(period=period, is_locked=False, chain_gap=gap)
    return LockStatus(
        period=period,
        is_locked=row.is_locked,
        locked_at=row.locked_at,
        locked_by_id=row.locked_by_id,
        unlocked_at=row.unlocked_at,
        unlocked_by_id=row.unlocked_by_id,
        unlock_reason=row.unlock_reason,
        unlock_count=row.unlock_count,
        chain_gap=gap,
    )


def lock_period(period: date, actor=None, meta=None, *, source: str | None = None) -> PeriodLock:
    """Kunci satu bulan; rantai wajib lengkap tanpa lubang (AC-30.7)."""
    period = month_start(period)
    with transaction.atomic():
        row = PeriodLock.objects.select_for_update().filter(period=period).first()
        if row is not None and row.is_locked:
            raise AlreadyLocked(messages.already_locked(period))

        locked = _locked_periods()
        gap = chain_gap(
            period,
            locked_periods=locked,
            opening_balance_date=period_start_date(period),
        )
        if gap is not None:
            message = messages.chain_gap(gap)
            raise DomainError(
                message,
                code="period_chain_gap",
                fields={"period": message},
            )

        before = _snapshot(row)
        if row is None:
            row = PeriodLock(period=period)
        row.is_locked = True
        row.locked_at = timezone.now()
        row.locked_by = actor if getattr(actor, "pk", None) else None
        row.unlocked_at = None
        row.unlocked_by = None
        row.unlock_reason = None
        row.save()

        transactions, movements = _period_counts(period)
        extra = {
            "period": period_key(period),
            "transactions": transactions,
            "movements": movements,
        }
        if source:
            extra["source"] = source

        _audit(
            row.pk,
            "lock",
            actor=actor,
            before=before,
            after=_snapshot(row),
            extra=extra,
            meta=meta,
        )
        return row


def unlock_period(period: date, reason: str, actor=None, meta=None) -> PeriodLock:
    """Buka kunci bulan terkunci terakhir (K-00 Opsi A) dengan alasan wajib."""
    period = month_start(period)
    reason = (reason or "").strip()
    if len(reason) < UNLOCK_REASON_MIN or len(reason) > UNLOCK_REASON_MAX:
        raise DomainError(
            messages.UNLOCK_REASON,
            code="unlock_reason",
            fields={"reason": messages.UNLOCK_REASON},
        )

    with transaction.atomic():
        row = PeriodLock.objects.select_for_update().filter(period=period).first()
        if row is None or not row.is_locked:
            raise AlreadyUnlocked(messages.not_locked(period))

        latest = max_locked_period()
        if latest is not None and latest != period:
            raise DomainError(
                messages.unlock_latest_first(latest),
                code="unlock_latest_first",
                http_status=409,
                fields={"period": messages.unlock_latest_first(latest)},
            )

        transactions, movements = _period_counts(period)
        before = _snapshot(row)
        row.is_locked = False
        row.unlocked_at = timezone.now()
        row.unlocked_by = actor if getattr(actor, "pk", None) else None
        row.unlock_reason = reason
        row.unlock_count = (row.unlock_count or 0) + 1
        row.save()

        _audit(
            row.pk,
            "unlock",
            actor=actor,
            before=before,
            after=_snapshot(row),
            extra={
                "period": period_key(period),
                "reason": reason,
                "transactions": transactions,
                "movements": movements,
            },
            meta=meta,
        )
        return row
