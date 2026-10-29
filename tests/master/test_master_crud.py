"""Test CRUD master kategori & item (FR-04, FR-05, FR-06)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.db.models import Q
from django.urls import reverse

from core import messages
from core.errors import DomainError
from core.models import PeriodLock
from ledger.models import Transaction
from master.forms import ItemForm
from master.models import Category, Item, StockItem
from master.services.categories import (
    category_choices,
    create_category,
    deactivate_category,
    delete_category,
    update_category,
)
from master.services.items import (
    active_items,
    assert_stock_direction,
    create_item,
    deactivate_item,
    delete_item,
    stock_direction_for,
    update_item,
)
from master.services.seed import ensure_master_data
from tests.factories import make_account, make_category, make_item, make_transaction


@pytest.fixture
def seeded(completed_setup):
    ensure_master_data()
    return completed_setup


@pytest.fixture
def auth_client(client, seeded):
    client.force_login(seeded)
    return client


def _txn_for_item(item, *, category, days=1, account=None):
    return make_transaction(
        item=item,
        category=category,
        account=account or make_account(),
        value_date=date(2026, 10, days),
    )


# --- Kategori -------------------------------------------------------------


@pytest.mark.django_db
def test_ac_04_1_tambah_kategori_broiler(seeded):
    category = create_category(code=" broiler ", name="Broiler", actor=seeded)

    assert category.code == "BROILER"
    assert Category.objects.filter(code="BROILER", is_active=True).exists()


@pytest.mark.django_db
def test_ac_04_2_kategori_sistem_tidak_bisa_dihapus_atau_dinonaktifkan(auth_client):
    layer = Category.objects.get(code="LAYER")

    with pytest.raises(DomainError) as exc:
        delete_category(category_id=layer.pk)
    assert exc.value.message == messages.CATEGORY_SYSTEM

    with pytest.raises(DomainError) as exc:
        deactivate_category(category_id=layer.pk)
    assert exc.value.message == messages.CATEGORY_SYSTEM

    response = auth_client.post(reverse("master:category_delete", args=[layer.pk]))
    assert response.status_code == 400
    assert messages.CATEGORY_SYSTEM in response.content.decode()
    assert Category.objects.filter(pk=layer.pk, is_active=True).exists()


@pytest.mark.django_db
def test_ac_04_3_kategori_terpakai_tidak_bisa_dihapus(seeded):
    category = create_category(code="BROILER", name="Broiler", actor=seeded)
    item = make_item(name="Penjualan Broiler", flow="income", default_category=category)
    account = make_account()
    for day in range(1, 6):
        _txn_for_item(item, category=category, days=day, account=account)

    with pytest.raises(DomainError) as exc:
        delete_category(category_id=category.pk)

    assert exc.value.message == messages.CATEGORY_IN_USE.format(count=5)


@pytest.mark.django_db
def test_ac_04_4_kode_kategori_duplikat_case_insensitive(seeded):
    with pytest.raises(DomainError) as exc:
        create_category(code="layer", name="Layer Baru", actor=seeded)

    assert exc.value.message == messages.CATEGORY_CODE_TAKEN


@pytest.mark.django_db
def test_ac_04_5_maksimal_satu_tingkat(seeded):
    broiler = create_category(code="BROILER", name="Broiler", actor=seeded)
    child = create_category(code="BROILER_CHILD", name="Anak Broiler", parent=broiler, actor=seeded)
    assert child.parent_id == broiler.pk

    afkir = Category.objects.get(code="AFKIR")
    with pytest.raises(DomainError) as exc:
        create_category(code="SUB_AFKIR", name="Sub Afkir", parent=afkir, actor=seeded)

    assert exc.value.message == messages.CATEGORY_DEPTH


@pytest.mark.django_db
def test_ac_04_6_pilihan_kategori_dari_master_termasuk_nonaktif(seeded):
    broiler = create_category(code="BROILER", name="Broiler", actor=seeded)
    lama = create_category(code="LAMA", name="Kategori Lama", actor=seeded)
    deactivate_category(category_id=lama.pk, actor=seeded)

    semua = category_choices(include_inactive=True)
    aktif = category_choices(include_inactive=False)

    assert (broiler.pk, "Broiler") in semua
    assert (lama.pk, "Kategori Lama (nonaktif)") in semua
    assert all(pk != lama.pk for pk, _ in aktif)


@pytest.mark.django_db
def test_ac_04_7_filter_layer_memuat_afkir(seeded):
    layer = Category.objects.get(code="LAYER")
    afkir = Category.objects.get(code="AFKIR")
    item = make_item(name="Penjualan Uji", flow="income", default_category=layer)
    account = make_account()
    make_transaction(
        item=item,
        category=layer,
        account=account,
        value_date=date(2026, 10, 1),
        amount=Decimal("1000000.00"),
    )
    make_transaction(
        item=item,
        category=afkir,
        account=account,
        value_date=date(2026, 10, 2),
        amount=Decimal("300000.00"),
    )

    layer_ids = Category.objects.filter(Q(pk=layer.pk) | Q(parent=layer)).values_list(
        "pk", flat=True
    )
    layer_total = sum(
        Transaction.objects.filter(category_id__in=layer_ids).values_list("amount", flat=True)
    )
    afkir_total = sum(Transaction.objects.filter(category=afkir).values_list("amount", flat=True))

    assert layer_total == Decimal("1300000.00")
    assert afkir_total == Decimal("300000.00")


@pytest.mark.django_db
def test_kategori_sistem_tidak_bisa_ubah_kode(seeded):
    layer = Category.objects.get(code="LAYER")

    with pytest.raises(DomainError) as exc:
        update_category(category_id=layer.pk, code="LAYER2", name="Layer", actor=seeded)

    assert exc.value.message == messages.CATEGORY_SYSTEM


@pytest.mark.django_db
def test_kategori_dengan_subkategori_tidak_bisa_dihapus(seeded):
    layer = Category.objects.get(code="LAYER")

    with pytest.raises(DomainError) as exc:
        delete_category(category_id=layer.pk)

    # LAYER adalah sistem, jadi pesan sistem yang lebih dulu muncul.
    assert exc.value.message == messages.CATEGORY_SYSTEM

    broiler = create_category(code="BROILER", name="Broiler", actor=seeded)
    create_category(code="BROILER_CHILD", name="Anak Broiler", parent=broiler, actor=seeded)
    with pytest.raises(DomainError) as exc:
        delete_category(category_id=broiler.pk)
    assert exc.value.message == messages.CATEGORY_HAS_CHILDREN


# --- Item -----------------------------------------------------------------


@pytest.mark.django_db
def test_ac_05_1_item_pembelian_doc_hanya_arus_pengeluaran(seeded):
    doc = Category.objects.get(code="DOC")
    item = create_item(
        name="Pembelian DOC",
        flow="expense",
        frequency="daily",
        default_category=doc,
        actor=seeded,
    )

    assert item in active_items(flow="expense")
    assert item not in active_items(flow="income")


@pytest.mark.django_db
def test_ac_05_2_item_terpakai_field_utama_terkunci_nama_tetap_bisa(seeded):
    pakan = Item.objects.get(code="feed")
    account = make_account()
    for day in range(1, 4):
        _txn_for_item(pakan, category=pakan.default_category, days=day, account=account)

    form = ItemForm(instance=pakan, used_count=3)
    assert form.fields["flow"].disabled is True
    assert form.fields["stock_item"].disabled is True
    assert form.fields["frequency"].disabled is True
    assert form.fields["name"].disabled is False

    data = {
        "name": "Pakan Baru",
        "flow": "income",
        "frequency": "monthly",
        "default_category": pakan.default_category_id,
        "has_stock": "",
        "stock_item": "",
        "unit": "",
        "default_payment_method": "",
        "sort_order": 0,
    }
    bound = ItemForm(data, instance=pakan, used_count=3)
    assert bound.is_valid(), bound.errors

    updated = update_item(
        item_id=pakan.pk,
        name=bound.cleaned_data["name"],
        flow=bound.cleaned_data["flow"],
        frequency=bound.cleaned_data["frequency"],
        default_category=bound.cleaned_data.get("default_category"),
        has_stock=bool(bound.cleaned_data.get("has_stock")),
        stock_item=bound.cleaned_data.get("stock_item"),
        unit=bound.cleaned_data.get("unit"),
        default_payment_method=None,
        sort_order=0,
        actor=seeded,
    )

    assert updated.name == "Pakan Baru"
    assert updated.flow == "expense"
    assert updated.frequency == "daily"
    assert updated.stock_item.code == "feed"


@pytest.mark.django_db
def test_ac_05_2_service_menolak_ubah_arus_item_terpakai(seeded):
    pakan = Item.objects.get(code="feed")
    _txn_for_item(pakan, category=pakan.default_category)

    with pytest.raises(DomainError) as exc:
        update_item(
            item_id=pakan.pk,
            name=pakan.name,
            flow="income",
            frequency=pakan.frequency,
            default_category=pakan.default_category,
            has_stock=True,
            stock_item=pakan.stock_item,
            unit=pakan.unit,
            actor=seeded,
        )

    assert "tidak bisa diubah" in exc.value.message


@pytest.mark.django_db
def test_ac_05_3_arah_stok_income_out_expense_in(seeded):
    assert stock_direction_for("income") == "out"
    assert stock_direction_for("expense") == "in"
    assert assert_stock_direction(flow="income", direction="out") == "out"
    assert assert_stock_direction(flow="expense", direction="in") == "in"

    with pytest.raises(DomainError) as exc:
        assert_stock_direction(flow="income", direction="in")
    assert exc.value.message == messages.ITEM_STOCK_DIRECTION


@pytest.mark.django_db
def test_ac_05_4_item_ber_stok_wajib_jenis_stok(seeded):
    with pytest.raises(DomainError) as exc:
        create_item(
            name="Tanpa Jenis Stok",
            flow="expense",
            has_stock=True,
            stock_item=None,
            actor=seeded,
        )
    assert exc.value.message == messages.ITEM_STOCK_UNIT


@pytest.mark.django_db
def test_ac_05_4_form_item_ber_stok_tanpa_jenis_stok_menampilkan_pesan(auth_client):
    response = auth_client.post(
        reverse("master:item_list"),
        {
            "name": "Tanpa Jenis Stok",
            "flow": "expense",
            "frequency": "daily",
            "default_category": "",
            "has_stock": "on",
            "stock_item": "",
            "unit": "",
            "default_payment_method": "",
            "sort_order": 0,
        },
    )

    assert response.status_code == 200
    assert messages.ITEM_STOCK_UNIT in response.content.decode()
    assert not Item.objects.filter(name="Tanpa Jenis Stok").exists()


@pytest.mark.django_db
def test_ac_05_5_item_nonaktif_hilang_dari_pilihan_transaksi_lama_tetap_resolve(seeded):
    obat = Item.objects.get(code="medicine")
    txn = _txn_for_item(obat, category=obat.default_category)

    deactivate_item(item_id=obat.pk, actor=seeded)
    obat.refresh_from_db()

    assert obat.is_active is False
    assert obat not in active_items()
    assert Transaction.objects.get(pk=txn.pk).item.name == "Obat"


@pytest.mark.django_db
def test_item_sistem_tidak_bisa_dihapus_dan_tersembunyi(seeded):
    correction = Item.objects.get(code="opening_correction")

    with pytest.raises(DomainError) as exc:
        delete_item(item_id=correction.pk)
    assert exc.value.message == messages.ITEM_SYSTEM
    assert correction not in active_items()


@pytest.mark.django_db
def test_item_terpakai_tidak_bisa_dihapus(seeded):
    obat = Item.objects.get(code="medicine")
    _txn_for_item(obat, category=obat.default_category)

    with pytest.raises(DomainError) as exc:
        delete_item(item_id=obat.pk)

    assert exc.value.message == messages.ITEM_IN_USE.format(count=1)


@pytest.mark.django_db
def test_item_belum_terpakai_bisa_dihapus(seeded):
    item = create_item(name="Item Sekali Pakai", flow="expense", actor=seeded)

    delete_item(item_id=item.pk)
    assert not Item.objects.filter(pk=item.pk).exists()


# --- Periode terkunci -----------------------------------------------------


@pytest.mark.django_db
def test_nonaktif_kategori_ditolak_bila_dipakai_di_periode_terkunci(seeded):
    PeriodLock.objects.create(period=date(2026, 10, 1), is_locked=True)
    category = create_category(code="BROILER", name="Broiler", actor=seeded)
    item = make_item(name="Penjualan Broiler", flow="income", default_category=category)
    _txn_for_item(item, category=category, days=5)

    with pytest.raises(DomainError) as exc:
        deactivate_category(category_id=category.pk, actor=seeded)

    assert exc.value.code == "period_locked"
    assert "terkunci" in exc.value.message


@pytest.mark.django_db
def test_nonaktif_item_ditolak_bila_dipakai_di_periode_terkunci(seeded):
    PeriodLock.objects.create(period=date(2026, 10, 1), is_locked=True)
    item = make_item(name="Item Terkunci", flow="expense")
    _txn_for_item(item, category=item.default_category or make_category(), days=5)

    with pytest.raises(DomainError) as exc:
        deactivate_item(item_id=item.pk, actor=seeded)

    assert exc.value.code == "period_locked"
    assert "terkunci" in exc.value.message


# --- AC-06.4 & guard HTTP -------------------------------------------------


@pytest.mark.django_db
def test_ac_06_4_endpoint_satuan_stok_menolak_400(auth_client):
    response = auth_client.post(reverse("master:stock_unit_update", args=["feed"]), {"unit": "ton"})

    assert response.status_code == 400
    assert "Satuan stok tidak bisa diubah" in response.json()["error"]
    assert StockItem.objects.get(code="feed").unit == "kg"


@pytest.mark.django_db
def test_aksi_pk_tidak_valid_menghasilkan_404(auth_client):
    missing = 999_999
    assert auth_client.post(reverse("master:category_delete", args=[missing])).status_code == 404
    assert (
        auth_client.post(reverse("master:category_deactivate", args=[missing])).status_code == 404
    )
    assert auth_client.post(reverse("master:item_delete", args=[missing])).status_code == 404
    assert auth_client.post(reverse("master:item_deactivate", args=[missing])).status_code == 404
    assert auth_client.get(reverse("master:category_update", args=[missing])).status_code == 404
    assert auth_client.get(reverse("master:item_update", args=[missing])).status_code == 404


# --- View integration -----------------------------------------------------


@pytest.mark.django_db
def test_halaman_kategori_dan_item_dapat_dibuka(auth_client):
    assert auth_client.get(reverse("master:category_list")).status_code == 200
    assert auth_client.get(reverse("master:item_list")).status_code == 200


@pytest.mark.django_db
def test_buat_kategori_lewat_view(auth_client, seeded):
    response = auth_client.post(
        reverse("master:category_list"),
        {"code": "broiler", "name": "Broiler", "parent": "", "sort_order": 0},
    )

    assert response.status_code == 302
    assert Category.objects.filter(code="BROILER", name="Broiler").exists()


@pytest.mark.django_db
def test_duplikat_kategori_lewat_view_menampilkan_pesan(auth_client):
    response = auth_client.post(
        reverse("master:category_list"),
        {"code": "layer", "name": "Layer Baru", "parent": "", "sort_order": 0},
    )

    assert response.status_code == 200
    assert messages.CATEGORY_CODE_TAKEN in response.content.decode()
    assert not Category.objects.filter(name="Layer Baru").exists()


@pytest.mark.django_db
def test_create_kategori_htmx_mengembalikan_panel(auth_client):
    response = auth_client.post(
        reverse("master:category_list"),
        {"code": "broiler", "name": "Broiler", "parent": "", "sort_order": 0},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert 'id="category-panel"' in response.content.decode()
    assert "HX-Trigger" in response
    assert Category.objects.filter(code="BROILER").exists()


@pytest.mark.django_db
def test_create_kategori_htmx_error_validasi_422(auth_client):
    response = auth_client.post(
        reverse("master:category_list"),
        {"code": "layer", "name": "Layer Baru", "parent": "", "sort_order": 0},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 422
    assert messages.CATEGORY_CODE_TAKEN in response.content.decode()


@pytest.mark.django_db
def test_buat_item_pembelian_doc_lewat_view(auth_client, seeded):
    doc = Category.objects.get(code="DOC")
    response = auth_client.post(
        reverse("master:item_list"),
        {
            "name": "Pembelian DOC",
            "flow": "expense",
            "frequency": "daily",
            "default_category": doc.pk,
            "has_stock": "",
            "stock_item": "",
            "unit": "",
            "default_payment_method": "",
            "sort_order": 0,
        },
    )

    assert response.status_code == 302
    assert Item.objects.filter(name="Pembelian DOC", flow="expense").exists()


@pytest.mark.django_db
def test_edit_item_terpakai_menampilkan_field_terkunci(auth_client, seeded):
    pakan = Item.objects.get(code="feed")
    _txn_for_item(pakan, category=pakan.default_category)

    response = auth_client.get(reverse("master:item_update", args=[pakan.pk]))
    body = response.content.decode()

    assert response.status_code == 200
    assert messages.ITEM_USED_NOTE.format(count=1) in body
    assert "Pakan" in body


@pytest.mark.django_db
def test_login_dibutuhkan_untuk_halaman_master(client, seeded):
    response = client.get(reverse("master:category_list"))
    assert response.status_code == 302
    assert response.url.startswith("/masuk")
