"""Service kunci periode: rantai, unlock terakhir, dan audit (FR-30/31)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from audit.models import AuditLog
from core import messages
from core.errors import AlreadyLocked, AlreadyUnlocked, DomainError, PeriodLocked
from core.models import PeriodLock
from core.services.locks import (
    assert_date_editable,
    lock_period,
    period_status,
    unlock_period,
)
from ledger.models import Account
from tests.factories import make_item, make_movement, make_stock_item, make_transaction

SEPTEMBER = date(2026, 9, 1)
OCTOBER = date(2026, 10, 1)
REASON = "Salah input nominal pakan 15 Sep"


def test_lock_bulan_pertama_dan_audit_jumlah(completed_setup):
    account = Account.objects.get()
    make_transaction(
        item=make_item(name="Obat Uji", flow="expense"),
        account=account,
        value_date=date(2026, 9, 5),
    )
    make_movement(
        stock_item=make_stock_item(),
        value_date=date(2026, 9, 6),
        direction="in",
        qty=Decimal("2"),
    )

    row = lock_period(SEPTEMBER, actor=completed_setup)

    assert row.is_locked is True
    assert row.locked_by_id == completed_setup.pk
    assert row.locked_at is not None

    audit = AuditLog.objects.get(entity="period_lock", action="lock")
    assert audit.entity_id == row.pk
    assert audit.user_id == completed_setup.pk
    assert audit.extra == {"period": "2026-09", "transactions": 1, "movements": 1}
    assert audit.after["is_locked"] is True
    assert audit.before is None


def test_lock_dengan_lubang_ditolak(completed_setup):
    with pytest.raises(DomainError) as exc:
        lock_period(OCTOBER, actor=completed_setup)

    assert exc.value.message == messages.chain_gap(SEPTEMBER)
    assert not PeriodLock.objects.exists()


def test_lock_berantai_september_lalu_oktober(completed_setup):
    lock_period(SEPTEMBER, actor=completed_setup)
    lock_period(OCTOBER, actor=completed_setup)

    assert list(PeriodLock.objects.values_list("period", flat=True)) == [OCTOBER, SEPTEMBER]


def test_lock_ganda_ditolak(completed_setup):
    lock_period(SEPTEMBER, actor=completed_setup)

    with pytest.raises(AlreadyLocked) as exc:
        lock_period(SEPTEMBER, actor=completed_setup)

    assert exc.value.message == messages.already_locked(SEPTEMBER)
    assert AuditLog.objects.filter(entity="period_lock", action="lock").count() == 1


def test_unlock_hanya_bulan_terkunci_terakhir(completed_setup):
    lock_period(SEPTEMBER, actor=completed_setup)
    lock_period(OCTOBER, actor=completed_setup)

    with pytest.raises(DomainError) as exc:
        unlock_period(SEPTEMBER, REASON, actor=completed_setup)

    assert exc.value.code == "unlock_latest_first"
    assert exc.value.message == messages.unlock_latest_first(OCTOBER)


def test_unlock_menyimpan_alasan_dan_audit(completed_setup):
    lock_period(SEPTEMBER, actor=completed_setup)

    row = unlock_period(SEPTEMBER, REASON, actor=completed_setup)

    assert row.is_locked is False
    assert row.unlock_reason == REASON
    assert row.unlocked_by_id == completed_setup.pk
    assert row.unlocked_at is not None
    assert row.unlock_count == 1

    audit = AuditLog.objects.get(entity="period_lock", action="unlock")
    assert audit.extra["reason"] == REASON
    assert audit.extra["period"] == "2026-09"
    assert audit.before["is_locked"] is True
    assert audit.after["is_locked"] is False


def test_unlock_alasan_pendek_ditolak(completed_setup):
    lock_period(SEPTEMBER, actor=completed_setup)

    with pytest.raises(DomainError) as exc:
        unlock_period(SEPTEMBER, "salah", actor=completed_setup)

    assert exc.value.message == messages.UNLOCK_REASON
    assert PeriodLock.objects.get().is_locked is True


def test_unlock_bulan_belum_terkunci_ditolak(completed_setup):
    with pytest.raises(AlreadyUnlocked) as exc:
        unlock_period(SEPTEMBER, REASON, actor=completed_setup)

    assert exc.value.message == messages.not_locked(SEPTEMBER)


def test_k00_guard_max_locked_edit_september_tetap_ditolak(completed_setup):
    lock_period(SEPTEMBER, actor=completed_setup)
    lock_period(OCTOBER, actor=completed_setup)
    unlock_period(OCTOBER, REASON, actor=completed_setup)

    # Oktober sudah terbuka, tetapi September masih terkunci dan menjadi max.
    with pytest.raises(PeriodLocked):
        assert_date_editable(date(2026, 9, 15))

    unlock_period(SEPTEMBER, REASON, actor=completed_setup)

    assert assert_date_editable(date(2026, 9, 15)) is None


def test_relock_setelah_unlock_mencatat_tiga_audit(completed_setup):
    lock_period(SEPTEMBER, actor=completed_setup)
    unlock_period(SEPTEMBER, REASON, actor=completed_setup)
    row = lock_period(SEPTEMBER, actor=completed_setup)

    assert row.is_locked is True
    assert row.unlock_count == 1
    assert row.unlock_reason is None
    actions = list(
        AuditLog.objects.filter(entity="period_lock")
        .order_by("created_at", "id")
        .values_list("action", flat=True)
    )
    assert actions == ["lock", "unlock", "lock"]


def test_period_status_terbuka_terkunci_dan_pernah_dibuka(completed_setup):
    status = period_status(SEPTEMBER)
    assert status.is_locked is False
    assert status.was_reopened is False
    assert status.chain_gap is None

    lock_period(SEPTEMBER, actor=completed_setup)
    assert period_status(SEPTEMBER).is_locked is True

    unlock_period(SEPTEMBER, REASON, actor=completed_setup)
    reopened = period_status(SEPTEMBER)
    assert reopened.is_locked is False
    assert reopened.was_reopened is True
    assert reopened.unlock_count == 1
    assert reopened.unlock_reason == REASON


def test_lock_bulan_berjalan_dinormalisasi_ke_hari_pertama(completed_setup):
    row = lock_period(date(2026, 9, 18), actor=completed_setup)

    assert row.period == SEPTEMBER


def test_movement_terhapus_tidak_dihitung_di_audit_lock(completed_setup):
    movement = make_movement(
        stock_item=make_stock_item(),
        value_date=date(2026, 9, 6),
        direction="in",
        qty=Decimal("2"),
    )
    movement.soft_delete()

    lock_period(SEPTEMBER, actor=completed_setup)

    audit = AuditLog.objects.get(entity="period_lock", action="lock")
    assert audit.extra["movements"] == 0
