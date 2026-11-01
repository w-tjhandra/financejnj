"""Koreksi saldo awal (FR-07, AC-07.3/07.4/07.5/07.8)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from audit.models import AuditLog
from core import messages
from core.errors import DomainError, PeriodLocked
from core.services.locks import lock_period
from ledger.models import Account, Transaction
from ledger.services.opening import record_opening_correction
from master.models import Category, Item
from master.services.seed import ensure_master_data
from tests.factories import make_transaction


@pytest.fixture
def seeded(completed_setup):
    ensure_master_data()
    return completed_setup


def _lock_cash(user) -> Account:
    account = Account.objects.get(code="cash")
    make_transaction(
        item=Item.objects.get(code="medicine"),
        account=account,
        value_date=date(2026, 9, 5),
    )
    return account


def test_koreksi_ditolak_bila_kas_belum_terkunci(seeded):
    with pytest.raises(DomainError) as exc:
        record_opening_correction(delta="10000000", reason="Kas awal kurang dicatat", actor=seeded)

    assert exc.value.code == "opening_not_locked"


def test_ac_07_3_koreksi_positif_membuat_transaksi_sistem(seeded):
    account = _lock_cash(seeded)
    before = account.opening_balance

    txn = record_opening_correction(
        delta="10000000",
        reason="Kas awal kurang catat setoran modal",
        actor=seeded,
    )

    assert txn.is_opening_correction is True
    assert txn.date == account.opening_balance_date
    assert txn.flow == "income"
    assert txn.amount == Decimal("10000000.00")
    assert txn.category == Category.objects.get(code="UMUM")
    assert txn.item == Item.objects.get(code="opening_correction")
    assert txn.qty is None and txn.unit is None and txn.period_month is None
    assert txn.notes == "[Koreksi saldo awal] Kas awal kurang catat setoran modal"
    assert txn.created_by_id == seeded.pk

    account.refresh_from_db()
    assert account.opening_balance == before

    audit = AuditLog.objects.get(entity="transaction", action="create")
    assert audit.entity_id == txn.pk
    assert audit.after["is_opening_correction"] is True
    assert audit.after["amount"] == "10000000.00"


def test_koreksi_negatif_memakai_arus_expense(seeded):
    _lock_cash(seeded)

    txn = record_opening_correction(
        delta="-4000000",
        reason="Ada setoran modal yang dobel",
        actor=seeded,
    )

    assert txn.flow == "expense"
    assert txn.amount == Decimal("4000000.00")


def test_ac_07_4_dan_07_8_mutasi_non_operasional_neto(seeded):
    _lock_cash(seeded)
    record_opening_correction(
        delta="10000000", reason="Kas awal kurang catat setoran modal", actor=seeded
    )
    record_opening_correction(delta="-4000000", reason="Ada setoran modal yang dobel", actor=seeded)

    corrections = Transaction.objects.filter(is_opening_correction=True)
    net = sum(txn.amount if txn.flow == "income" else -txn.amount for txn in corrections)

    assert corrections.count() == 2
    assert net == Decimal("6000000.00")
    # Koreksi tidak pernah mengubah saldo awal tersimpan.
    assert Account.objects.get(code="cash").opening_balance == Decimal("250000000.00")


def test_ac_07_5_alasan_minimal_10_karakter(seeded):
    _lock_cash(seeded)

    with pytest.raises(DomainError) as exc:
        record_opening_correction(delta="1000", reason="abc", actor=seeded)

    assert exc.value.message == messages.REASON_MIN_10
    assert exc.value.fields == {"reason": messages.REASON_MIN_10}
    assert not Transaction.objects.filter(is_opening_correction=True).exists()


def test_koreksi_nol_ditolak(seeded):
    _lock_cash(seeded)

    with pytest.raises(DomainError) as exc:
        record_opening_correction(delta="0", reason="Koreksi tidak seharusnya nol", actor=seeded)

    assert exc.value.code == "amount_zero"


def test_ac_30_9_koreksi_ditolak_saat_periode_saldo_awal_terkunci(seeded):
    _lock_cash(seeded)
    lock_period(date(2026, 9, 1), actor=seeded)

    with pytest.raises(PeriodLocked):
        record_opening_correction(
            delta="10000000", reason="Kas awal kurang catat setoran modal", actor=seeded
        )

    assert not Transaction.objects.filter(is_opening_correction=True).exists()
    assert Account.objects.get(code="cash").opening_balance == Decimal("250000000.00")
