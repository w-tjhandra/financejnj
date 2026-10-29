"""View integration S-05 form, S-06 detail, S-07 hapus (FR-08…FR-11)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditLog
from core import messages
from core.services.locks import lock_period
from core.utils.dates import today_wib
from ledger.forms import transaction_initial
from ledger.models import Transaction
from ledger.services.opening import record_opening_correction
from ledger.services.transactions import create_transaction
from master.models import Category, Item, StockItem
from master.services.seed import ensure_master_data
from stock import api as stock_api
from stock.models import StockMovement


@pytest.fixture
def seeded(completed_setup):
    ensure_master_data(
        stock={
            "feed": {"qty": Decimal("1000")},
            "egg": {"qty": Decimal("100")},
            "manure": {"qty": Decimal("30")},
        }
    )
    return completed_setup


@pytest.fixture
def auth_client(client, seeded):
    client.force_login(seeded)
    return client


def _create(*, item_code="egg_sales", amount="520000", **kwargs):
    item = Item.objects.get(code=item_code)
    kwargs.setdefault("date", date(2026, 9, 20))
    kwargs.setdefault("flow", item.flow)
    kwargs.setdefault("category", item.default_category)
    kwargs.setdefault("item", item)
    kwargs.setdefault("amount", amount)
    return create_transaction(**kwargs)


def _payload(item_code="egg_sales", **overrides):
    item = Item.objects.get(code=item_code)
    data = {
        "date": "2026-09-20",
        "flow": item.flow,
        "item": item.pk,
        "category": item.default_category_id,
        "amount": "520.000",
        "qty": "20" if item.stock_item_id else "",
        "unit": item.unit or "",
        "payment_method": "transfer",
        "notes": "",
        "period_month": "",
    }
    data.update(overrides)
    return data


def _post_create(client, item_code="egg_sales", **overrides):
    return client.post(reverse("transaction_create"), _payload(item_code, **overrides))


def _detail(client, txn):
    return client.get(reverse("transaction_detail", args=[txn.pk]))


# --- S-05 form: nilai awal, partial HTMX, fallback non-HTMX ---------------


def test_form_baru_default_tanggal_hari_ini_dan_maksimal_hari_ini(auth_client):
    response = auth_client.get(reverse("transaction_create"))

    assert response.status_code == 200
    assert today_wib().isoformat() in response.content.decode()
    assert f'max="{today_wib().isoformat()}"' in response.content.decode()


def test_form_tetap_bisa_diisi_tanpa_htmx(auth_client):
    """Fallback non-HTMX: qty, satuan, dan bulan gaji selalu ada di DOM."""
    response = auth_client.get(reverse("transaction_create"))

    body = response.content.decode()
    assert 'name="qty"' in body
    assert 'name="unit"' in body
    assert 'name="period_month"' in body


def test_item_options_mengikuti_arus(auth_client):
    income = auth_client.get(reverse("transaction_item_options"), {"flow": "income"})
    expense = auth_client.get(reverse("transaction_item_options"), {"flow": "expense"})

    assert "Pendapatan Telur" in income.content.decode()
    assert "Pakan" not in income.content.decode()
    assert "Pakan" in expense.content.decode()
    assert "Pendapatan Telur" not in expense.content.decode()


def test_ac_08_1_partial_item_ber_stok_qty_wajib_dan_satuan_readonly(auth_client):
    item = Item.objects.get(code="egg_sales")
    response = auth_client.get(reverse("transaction_item_fields"), {"item": item.pk})

    body = response.content.decode()
    assert 'name="qty"' in body
    assert "required" in body
    assert "readonly" in body
    assert ">kg<" in body or "kg" in body
    assert "Qty tidak mengubah stok" not in body


def test_ac_08_1_partial_item_non_stok_qty_opsional_dengan_hint(auth_client):
    item = Item.objects.get(code="afkir_sales")
    response = auth_client.get(reverse("transaction_item_fields"), {"item": item.pk})

    body = response.content.decode()
    assert "Qty tidak mengubah stok" in body
    start = body.find('name="qty"')
    qty_input = body[start : body.find(">", start)]
    assert "required" not in qty_input


def test_ac_08_7_item_pakan_default_metode_bayar_transfer(auth_client):
    item = Item.objects.get(code="feed")
    response = auth_client.get(reverse("transaction_item_fields"), {"item": item.pk})

    body = response.content.decode()
    assert '<option value="transfer" selected>Transfer</option>' in body


def test_ac_09_1_item_bulanan_memunculkan_bulan_gaji(auth_client):
    item = Item.objects.get(code="salary")
    response = auth_client.get(
        reverse("transaction_item_fields"), {"item": item.pk, "date": "2026-10-05"}
    )

    body = response.content.decode()
    assert 'type="month"' in body
    assert 'name="period_month"' in body
    assert 'value="2026-10"' in body


# --- Create ---------------------------------------------------------------


def test_create_transaksi_ber_stok_redirect_detail_dan_membuat_movement(auth_client):
    response = _post_create(auth_client)

    txn = Transaction.objects.get()
    assert response.status_code == 302
    assert response.url == reverse("transaction_detail", args=[txn.pk])
    assert txn.qty == Decimal("20.000")
    assert StockMovement.objects.get(transaction=txn).direction == "out"
    assert stock_api.on_hand(StockItem.objects.get(code="egg").pk) == Decimal("80")


def test_ac_08_1_simpan_tanpa_qty_item_ber_stok_ditolak(auth_client):
    response = _post_create(auth_client, qty="")

    assert response.status_code == 200
    assert messages.QTY_REQUIRED in response.content.decode()
    assert not Transaction.objects.exists()
    assert not StockMovement.objects.exists()


def test_ac_08_10_non_stok_tanpa_qty_tersimpan_dengan_qty_null(auth_client):
    response = _post_create(
        auth_client,
        "afkir_sales",
        amount="5.400.000",
        qty="",
        unit="",
        date="2026-09-20",
    )

    txn = Transaction.objects.get()
    assert response.status_code == 302
    assert txn.qty is None
    assert txn.unit is None
    assert not StockMovement.objects.exists()


def test_ac_08_11_non_stok_dengan_qty_informasional(auth_client):
    _post_create(
        auth_client,
        "afkir_sales",
        amount="5.400.000",
        qty="2.000",
        unit="ekor",
    )

    txn = Transaction.objects.get()
    assert txn.qty == Decimal("2000.000")
    assert txn.unit == "ekor"
    assert not StockMovement.objects.exists()


def test_ac_08_3_stok_kurang_pesan_rinci_tanpa_data(auth_client):
    egg = StockItem.objects.get(code="egg")
    egg.opening_qty = Decimal("10")
    egg.save(update_fields=["opening_qty", "updated_at"])

    response = _post_create(auth_client, qty="20")

    assert response.status_code == 409
    assert (
        messages.STOCK_INSUFFICIENT_DETAIL.format(
            name="Telur", date="20 Sep 2026", qty="10", unit="kg", requested="20"
        )
        in response.content.decode()
    )
    assert not Transaction.objects.exists()
    assert not StockMovement.objects.exists()


def test_ac_08_4_tanggal_sebelum_saldo_awal_ditolak(auth_client):
    response = _post_create(auth_client, "medicine", date="2026-08-31", amount="1.000", qty="")

    assert response.status_code == 200
    assert messages.date_before_opening(date(2026, 9, 1)) in response.content.decode()
    assert not Transaction.objects.exists()


def test_ac_08_5_tanggal_masa_depan_ditolak(auth_client):
    tomorrow = today_wib() + timedelta(days=1)
    response = _post_create(
        auth_client, "medicine", date=tomorrow.isoformat(), amount="1.000", qty=""
    )

    assert response.status_code == 200
    assert messages.TXN_DATE_AFTER_TODAY in response.content.decode()
    assert not Transaction.objects.exists()


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        ("0", messages.AMOUNT_MIN),
        ("-5.000", messages.AMOUNT_MIN),
        ("100000000001", messages.AMOUNT_MAX),
    ],
)
def test_ac_08_6_nominal_tidak_valid_ditolak(auth_client, amount, expected):
    response = _post_create(auth_client, "medicine", amount=amount, qty="")

    assert response.status_code == 200
    assert expected in response.content.decode()
    assert not Transaction.objects.exists()


def test_input_invalid_dipertahankan_di_form(auth_client):
    response = _post_create(auth_client, amount="-5.000", notes="catatan tetap")

    body = response.content.decode()
    assert "-5.000" in body
    assert "catatan tetap" in body


def test_ac_08_9_periode_terkunci_ditolak(auth_client, seeded):
    lock_period(date(2026, 9, 1), actor=seeded)

    response = _post_create(auth_client)

    assert response.status_code == 403
    assert messages.period_locked(date(2026, 9, 1)) in response.content.decode()
    assert not Transaction.objects.exists()
    assert not StockMovement.objects.exists()


# --- Gaji bulanan ---------------------------------------------------------


def _salary_payload(**overrides):
    salary = Item.objects.get(code="salary")
    data = {
        "date": "2026-10-05",
        "flow": "expense",
        "item": salary.pk,
        "category": Category.objects.get(code="LAYER").pk,
        "amount": "6.000.000",
        "qty": "",
        "unit": "",
        "payment_method": "transfer",
        "notes": "",
        "period_month": "2026-10",
    }
    data.update(overrides)
    return data


def _post_salary(client, **overrides):
    return client.post(reverse("transaction_create"), _salary_payload(**overrides))


def test_ac_09_1_gaji_tersimpan_dengan_period_month(auth_client):
    response = _post_salary(auth_client)

    txn = Transaction.objects.get()
    assert response.status_code == 302
    assert txn.period_month == date(2026, 10, 1)


def test_ac_09_2_gaji_duplikat_redirect_ke_edit_dengan_banner(auth_client):
    existing = create_transaction(
        date=date(2026, 10, 5),
        flow="expense",
        category=Category.objects.get(code="LAYER"),
        item=Item.objects.get(code="salary"),
        amount="6000000",
        period_month=date(2026, 10, 1),
    )

    response = _post_salary(auth_client, amount="6.500.000")

    assert response.status_code == 302
    assert response.url == f"{reverse('transaction_update', args=[existing.pk])}?duplicate=1"
    assert Transaction.objects.filter(item__code="salary").count() == 1

    form_response = auth_client.get(response.url)
    body = form_response.content.decode()
    assert messages.SALARY_DUPLICATE_BANNER.format(category="LAYER", month="Oktober 2026") in body
    assert "6.000.000,00" in body


def test_ac_09_2_setelah_edit_nominal_berganti_tanpa_baris_baru(auth_client):
    existing = create_transaction(
        date=date(2026, 10, 5),
        flow="expense",
        category=Category.objects.get(code="LAYER"),
        item=Item.objects.get(code="salary"),
        amount="6000000",
        period_month=date(2026, 10, 1),
    )

    response = auth_client.post(
        reverse("transaction_update", args=[existing.pk]),
        _salary_payload(amount="6.500.000"),
    )

    assert response.status_code == 302
    existing.refresh_from_db()
    assert existing.amount == Decimal("6500000.00")
    assert Transaction.objects.filter(item__code="salary").count() == 1


def test_ac_09_3_kategori_bukan_gaji_ditolak(auth_client):
    response = _post_salary(auth_client, category=Category.objects.get(code="AFKIR").pk)

    assert response.status_code == 200
    assert messages.SALARY_CATEGORY in response.content.decode()
    assert not Transaction.objects.exists()


def test_ac_09_4_bulan_gaji_berbeda_dari_tanggal_bayar(auth_client):
    _post_salary(auth_client, date="2026-10-03", period_month="2026-09")

    txn = Transaction.objects.get()
    assert txn.date == date(2026, 10, 3)
    assert txn.period_month == date(2026, 9, 1)


def test_ac_09_5_setelah_dihapus_gaji_bulan_sama_boleh_dibuat_lagi(auth_client):
    existing = create_transaction(
        date=date(2026, 10, 5),
        flow="expense",
        category=Category.objects.get(code="LAYER"),
        item=Item.objects.get(code="salary"),
        amount="6000000",
        period_month=date(2026, 10, 1),
    )
    auth_client.post(reverse("transaction_delete", args=[existing.pk]))

    response = _post_salary(auth_client, amount="6.500.000")

    assert response.status_code == 302
    assert Transaction.objects.filter(item__code="salary").count() == 1
    assert Transaction.all_objects.filter(item__code="salary").count() == 2


# --- Edit -----------------------------------------------------------------


def _update_payload(txn, **overrides):
    data = transaction_initial(txn)
    data.update(overrides)
    return data


def test_edit_form_mengisi_nilai_awal(auth_client):
    txn = _create(qty="20", amount="520000", notes="setoran")

    response = auth_client.get(reverse("transaction_update", args=[txn.pk]))

    body = response.content.decode()
    assert "520.000,00" in body
    assert "setoran" in body
    assert 'value="20"' in body


def test_ac_10_1_edit_qty_mengubah_movement_yang_sama(auth_client):
    txn = _create(qty="20")

    response = auth_client.post(
        reverse("transaction_update", args=[txn.pk]), _update_payload(txn, qty="30")
    )

    assert response.status_code == 302
    txn.refresh_from_db()
    assert txn.qty == Decimal("30.000")
    assert StockMovement.objects.filter(transaction=txn).count() == 1
    assert StockMovement.objects.get(transaction=txn).qty == Decimal("30.000")
    assert stock_api.on_hand(StockItem.objects.get(code="egg").pk) == Decimal("70")


def test_ac_10_2_edit_menjadi_item_non_stok_menghapus_movement(auth_client):
    txn = _create(qty="20")
    afkir = Item.objects.get(code="afkir_sales")

    auth_client.post(
        reverse("transaction_update", args=[txn.pk]),
        _update_payload(
            txn,
            item=afkir.pk,
            category=Category.objects.get(code="AFKIR").pk,
            qty="",
            unit="",
        ),
    )

    txn.refresh_from_db()
    assert txn.item_id == afkir.pk
    assert txn.qty is None
    assert not StockMovement.objects.filter(transaction=txn).exists()
    assert stock_api.on_hand(StockItem.objects.get(code="egg").pk) == Decimal("100")


def test_ac_10_3_edit_tanggal_membawa_movement(auth_client):
    txn = _create(qty="20", date=date(2026, 9, 30))

    auth_client.post(
        reverse("transaction_update", args=[txn.pk]),
        _update_payload(txn, date="2026-09-15"),
    )

    txn.refresh_from_db()
    assert txn.date == date(2026, 9, 15)
    assert StockMovement.objects.get(transaction=txn).date == date(2026, 9, 15)


def test_ac_10_4_edit_yang_membuat_saldo_minus_ditolak(auth_client):
    first = _create(qty="80", date=date(2026, 9, 10))
    _create(qty="15", date=date(2026, 9, 15))

    response = auth_client.post(
        reverse("transaction_update", args=[first.pk]), _update_payload(first, qty="90")
    )

    assert response.status_code == 409
    assert (
        messages.STOCK_WILL_NEGATIVE.format(
            name="Telur", date="15/09/2026", balance="-5", unit="kg"
        )
        in response.content.decode()
    )
    first.refresh_from_db()
    assert first.qty == Decimal("80.000")


def test_ac_10_5_edit_pada_periode_terkunci_read_only(auth_client, seeded):
    txn = _create(qty="20", date=date(2026, 9, 20))
    lock_period(date(2026, 9, 1), actor=seeded)

    response = auth_client.get(reverse("transaction_update", args=[txn.pk]))

    body = response.content.decode()
    assert response.status_code == 200
    assert "disabled" in body
    assert "Simpan" not in body
    assert "periode terkunci" in body.lower()


def test_ac_10_6_edit_mengubah_updated_at_dan_audit(auth_client, seeded):
    txn = _create(qty="2", amount="520000", actor=seeded)
    past = timezone.now() - timedelta(days=2)
    Transaction.objects.filter(pk=txn.pk).update(updated_at=past)
    txn.refresh_from_db()
    created_at = txn.created_at

    auth_client.post(
        reverse("transaction_update", args=[txn.pk]),
        _update_payload(txn, amount="600.000", qty="3"),
    )

    txn.refresh_from_db()
    assert txn.created_at == created_at
    assert txn.updated_at > past
    audit = AuditLog.objects.get(entity="transaction", action="update")
    assert audit.before["amount"] == "520000.00"
    assert audit.after["amount"] == "600000.00"


# --- Detail ---------------------------------------------------------------


def test_detail_menampilkan_semua_field_terformat(auth_client, seeded):
    txn = _create(
        qty="20",
        amount="520000",
        payment_method="transfer",
        notes="Setoran pagi",
        actor=seeded,
    )

    response = _detail(auth_client, txn)

    body = response.content.decode()
    assert response.status_code == 200
    assert "20 September 2026" in body
    assert "Rp 520.000,00" in body
    assert "20 kg" in body
    assert "Setoran pagi" in body
    assert "Transfer" in body
    assert seeded.username in body


def test_detail_item_non_stok_tanpa_qty_tidak_menampilkan_baris_qty(auth_client):
    txn = _create(item_code="afkir_sales", amount="5400000", qty=None)

    body = _detail(auth_client, txn).content.decode()

    assert '<dt class="text-slate-500">Qty</dt>' not in body


def test_detail_koreksi_saldo_awal_tanpa_tombol_edit_hapus(auth_client, seeded):
    _create(item_code="medicine", amount="1000", actor=seeded)
    correction = record_opening_correction(
        delta="100000", reason="Koreksi saldo awal uji", actor=seeded
    )

    body = _detail(auth_client, correction).content.decode()

    assert "Koreksi saldo awal" in body
    assert reverse("transaction_update", args=[correction.pk]) not in body
    assert reverse("transaction_delete", args=[correction.pk]) not in body


# --- Hapus ----------------------------------------------------------------


def test_ac_11_1_hapus_soft_delete_dan_stok_kembali(auth_client):
    txn = _create(qty="20")

    response = auth_client.post(reverse("transaction_delete", args=[txn.pk]))

    assert response.status_code == 302
    assert not Transaction.objects.filter(pk=txn.pk).exists()
    deleted = Transaction.all_objects.get(pk=txn.pk)
    assert deleted.deleted_at is not None
    assert stock_api.on_hand(StockItem.objects.get(code="egg").pk) == Decimal("100")


def test_ac_11_4_hapus_pada_periode_terkunci_ditolak(auth_client, seeded):
    txn = _create(qty="20", date=date(2026, 9, 20))
    lock_period(date(2026, 9, 1), actor=seeded)

    page = auth_client.get(reverse("transaction_delete", args=[txn.pk]))
    assert "Periode terkunci" in page.content.decode()
    assert "disabled" in page.content.decode()

    response = auth_client.post(reverse("transaction_delete", args=[txn.pk]))

    assert response.status_code == 403
    assert messages.period_locked(date(2026, 9, 1)) in response.content.decode()
    assert Transaction.objects.filter(pk=txn.pk).exists()


def test_ac_11_5_hapus_mengisi_deleted_by_dan_audit(auth_client, seeded):
    txn = _create(qty="20")

    auth_client.post(reverse("transaction_delete", args=[txn.pk]))

    deleted = Transaction.all_objects.get(pk=txn.pk)
    assert deleted.deleted_by_id == seeded.pk
    assert AuditLog.objects.filter(entity="transaction", action="delete").exists()


def test_hapus_stock_conflict_ditampilkan_sebagai_error_jelas(auth_client, seeded):
    egg = StockItem.objects.get(code="egg")
    purchase = Item.objects.create(
        name="Pembelian Telur Uji", flow="expense", stock_item=egg, unit="kg"
    )
    txn = create_transaction(
        date=date(2026, 9, 10),
        flow="expense",
        category=Category.objects.get(code="UMUM"),
        item=purchase,
        amount="1500000",
        qty="30",
    )
    _create(qty="120", date=date(2026, 9, 20))

    response = auth_client.post(reverse("transaction_delete", args=[txn.pk]))

    assert response.status_code == 409
    assert "Stok Telur akan minus" in response.content.decode()
    assert Transaction.objects.filter(pk=txn.pk).exists()


def test_hapus_koreksi_saldo_awal_ditolak(auth_client, seeded):
    _create(item_code="medicine", amount="1000", actor=seeded)
    correction = record_opening_correction(
        delta="100000", reason="Koreksi saldo awal uji", actor=seeded
    )

    page = auth_client.get(reverse("transaction_delete", args=[correction.pk]))
    assert "tidak bisa dihapus" in page.content.decode()
    response = auth_client.post(reverse("transaction_delete", args=[correction.pk]))

    assert response.status_code == 400
    assert Transaction.objects.filter(pk=correction.pk).exists()
