"""Validator model: kategori (kedalaman/siklus) dan item (unit stok)."""

import pytest
from django.core.exceptions import ValidationError

from core import messages
from master.models import Category, Item
from tests.factories import make_category, make_stock_item


@pytest.mark.django_db
def test_kategori_tidak_boleh_menjadi_induk_dirinya():
    category = make_category(code="LAYER", name="Layer")
    category.parent = category

    with pytest.raises(ValidationError) as exc:
        category.full_clean()

    assert messages.CATEGORY_DEPTH in str(exc.value)


@pytest.mark.django_db
def test_kategori_maksimal_satu_tingkat():
    root = make_category(code="LAYER", name="Layer")
    child = make_category(code="AFKIR", name="Afkir", parent=root)
    grandchild = Category(code="SUB", name="Sub", parent=child)

    with pytest.raises(ValidationError) as exc:
        grandchild.full_clean()

    assert messages.CATEGORY_DEPTH in str(exc.value)


@pytest.mark.django_db
def test_kategori_tidak_boleh_siklus():
    root = make_category(code="LAYER", name="Layer")
    child = make_category(code="AFKIR", name="Afkir", parent=root)

    root.parent = child
    with pytest.raises(ValidationError) as exc:
        root.full_clean()

    assert messages.CATEGORY_DEPTH in str(exc.value)


@pytest.mark.django_db
def test_kategori_menormalkan_kode_uppercase():
    category = Category(code=" layer ", name="Layer")
    category.full_clean()

    assert category.code == "LAYER"


@pytest.mark.django_db
def test_item_ber_stok_wajib_unit():
    stock = make_stock_item()
    item = Item(name="Pakan Uji", flow="expense", stock_item=stock, unit=None)

    with pytest.raises(ValidationError) as exc:
        item.full_clean()

    assert messages.ITEM_STOCK_UNIT in str(exc.value)


@pytest.mark.django_db
def test_item_non_stok_boleh_tanpa_unit():
    item = Item(name="Obat Uji", flow="expense", stock_item=None, unit=None)
    item.full_clean()

    assert item.unit is None


@pytest.mark.django_db
def test_item_menormalkan_unit_kosong_ke_null():
    item = Item(name="Obat Uji", flow="expense", stock_item=None, unit="")
    item.full_clean()

    assert item.unit is None
