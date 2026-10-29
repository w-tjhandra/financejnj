"""Audit: snapshot/diff, log_audit, dan sifat append-only."""

from datetime import date
from decimal import Decimal

import pytest

from audit.models import AppendOnlyError, AuditLog
from audit.service import diff, log_audit, snapshot
from core.types import RequestMeta
from tests.factories import make_item, make_transaction


@pytest.mark.django_db
def test_snapshot_menyerialkan_decimal_tanggal_dan_fk():
    item = make_item(stock_item=None, unit=None)
    txn = make_transaction(item=item, amount=Decimal("6500000.00"), value_date=date(2026, 10, 1))

    data = snapshot(txn, ["amount", "date", "item"])

    assert data == {
        "amount": "6500000.00",
        "date": "2026-10-01",
        "item": item.pk,
    }


def test_diff_hanya_mengembalikan_field_yang_berubah():
    before = {"amount": "6500000.00", "notes": "lama", "qty": None}
    after = {"amount": "6750000.00", "notes": "lama", "qty": None}

    changed_before, changed_after = diff(before, after)

    assert changed_before == {"amount": "6500000.00"}
    assert changed_after == {"amount": "6750000.00"}


@pytest.mark.django_db
def test_log_audit_export_entity_id_null(django_user_model):
    user = django_user_model.objects.create_user(username="auditor", password="RahasiaKandang2026")

    entry = log_audit(
        entity="export",
        entity_id=None,
        action="export",
        actor=user,
        extra={"kind": "xlsx", "period": date(2026, 9, 1), "sheets": ["Ringkasan"]},
        meta=RequestMeta(ip="203.0.113.5", user_agent="x" * 250),
    )

    assert entry.entity == "export"
    assert entry.entity_id is None
    assert entry.user_id == user.pk
    assert entry.extra["period"] == "2026-09-01"
    assert entry.ip == "203.0.113.5"
    assert len(entry.user_agent) == 200


@pytest.mark.django_db
def test_log_audit_menolak_entity_atau_action_tidak_dikenal():
    with pytest.raises(ValueError):
        log_audit(entity="tidak_ada", entity_id=1, action="create")
    with pytest.raises(ValueError):
        log_audit(entity="transaction", entity_id=1, action="tidak_ada")
    with pytest.raises(ValueError):
        log_audit(entity="export", entity_id=1, action="export")


@pytest.mark.django_db
def test_audit_log_tidak_bisa_diubah_atau_dihapus():
    entry = log_audit(entity="transaction", entity_id=1, action="create", after={"amount": "1.00"})

    entry.action = "delete"
    with pytest.raises(AppendOnlyError):
        entry.save()

    with pytest.raises(AppendOnlyError):
        AuditLog.objects.filter(pk=entry.pk).update(action="delete")

    with pytest.raises(AppendOnlyError):
        AuditLog.objects.filter(pk=entry.pk).delete()

    with pytest.raises(AppendOnlyError):
        entry.delete()

    assert AuditLog.objects.filter(pk=entry.pk, action="create").exists()
