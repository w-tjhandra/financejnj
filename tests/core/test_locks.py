"""Kunci periode berantai dan guard tanggal (K-00 Opsi A)."""

from datetime import date

import pytest

from core import messages
from core.errors import PeriodLocked
from core.models import PeriodLock
from core.services.locks import (
    assert_date_editable,
    chain_gap,
    is_date_editable,
    max_locked_period,
)

OPENING = date(2026, 9, 1)


def test_chain_gap_tanpa_lock_mengembalikan_bulan_opening():
    assert chain_gap(date(2026, 10, 1), locked_periods=[], opening_balance_date=OPENING) == date(
        2026, 9, 1
    )


def test_chain_gap_berurutan_tidak_ada_lubang():
    locked = [date(2026, 9, 1), date(2026, 10, 1)]
    assert chain_gap(date(2026, 11, 1), locked_periods=locked, opening_balance_date=OPENING) is None


def test_chain_gap_mengembalikan_lubang_pertama():
    locked = [date(2026, 9, 1), date(2026, 11, 1)]
    assert chain_gap(
        date(2026, 12, 1), locked_periods=locked, opening_balance_date=OPENING
    ) == date(2026, 10, 1)


def test_chain_gap_target_sebelum_opening_tidak_perlu_rantai():
    assert chain_gap(date(2026, 8, 1), locked_periods=[], opening_balance_date=OPENING) is None


def test_chain_gap_lock_sebelum_opening_menjadi_awal_rantai():
    assert chain_gap(
        date(2026, 10, 1),
        locked_periods=[date(2026, 8, 1)],
        opening_balance_date=OPENING,
    ) == date(2026, 9, 1)


@pytest.mark.django_db
def test_max_locked_period_mengambil_terbaru_yang_terkunci():
    PeriodLock.objects.create(period=date(2026, 9, 1))
    PeriodLock.objects.create(period=date(2026, 10, 1))
    PeriodLock.objects.create(period=date(2026, 11, 1), is_locked=False)

    assert max_locked_period() == date(2026, 10, 1)


@pytest.mark.django_db
def test_tanpa_lock_semua_tanggal_editable():
    assert assert_date_editable(date(2020, 1, 1)) is None
    assert is_date_editable(date(2020, 1, 1)) is True


@pytest.mark.django_db
def test_tanggal_di_bulan_terkunci_ditolak():
    PeriodLock.objects.create(period=date(2026, 9, 1))

    with pytest.raises(PeriodLocked) as exc:
        assert_date_editable(date(2026, 9, 30))

    assert str(exc.value) == messages.period_locked(date(2026, 9, 1))
    assert exc.value.period == date(2026, 9, 1)


@pytest.mark.django_db
def test_bulan_setelah_kunci_terakhir_lolos():
    PeriodLock.objects.create(period=date(2026, 9, 1))

    assert assert_date_editable(date(2026, 10, 1)) is None
    assert is_date_editable(date(2026, 10, 1)) is True


@pytest.mark.django_db
def test_tanggal_sebelum_opening_tetap_editable_bila_tidak_ada_lock():
    # Guard lock tidak memeriksa opening; validasi opening ada di service transaksi.
    assert assert_date_editable(date(2026, 8, 31)) is None
