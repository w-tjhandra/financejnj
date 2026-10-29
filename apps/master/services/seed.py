"""Seed master data default (FR-02, D-03).

Dipanggil saat finalisasi setup, command seed demo, dan test. Idempoten:
baris yang sudah ada tidak ditimpa, sehingga perubahan pengguna tidak hilang.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from master.models import Category, Item, StockItem

CATEGORY_SEEDS = (
    {"code": "LAYER", "name": "Layer", "parent": None, "sort_order": 10},
    {"code": "AFKIR", "name": "AYAM AFKIR", "parent": "LAYER", "sort_order": 20},
    {"code": "DOC", "name": "DOC", "parent": None, "sort_order": 30},
    {"code": "UMUM", "name": "UMUM", "parent": None, "sort_order": 40},
)

STOCK_SEEDS = (
    {"code": "feed", "name": "Pakan", "unit": "kg"},
    {"code": "egg", "name": "Telur", "unit": "kg"},
    {"code": "manure", "name": "Kotoran", "unit": "karung"},
)

ITEM_SEEDS = (
    {
        "code": "egg_sales",
        "name": "Pendapatan Telur",
        "flow": "income",
        "frequency": "daily",
        "category": "LAYER",
        "stock": "egg",
        "unit": "kg",
        "sort_order": 10,
    },
    {
        "code": "manure_sales",
        "name": "Pendapatan Kotoran",
        "flow": "income",
        "frequency": "daily",
        "category": "UMUM",
        "stock": "manure",
        "unit": "karung",
        "sort_order": 20,
    },
    {
        "code": "afkir_sales",
        "name": "Pendapatan Ayam Afkir",
        "flow": "income",
        "frequency": "daily",
        "category": "AFKIR",
        "stock": None,
        "unit": "kg",
        "sort_order": 30,
    },
    {
        "code": "feed",
        "name": "Pakan",
        "flow": "expense",
        "frequency": "daily",
        "category": "LAYER",
        "stock": "feed",
        "unit": "kg",
        "payment_method": "transfer",
        "sort_order": 40,
    },
    {
        "code": "medicine",
        "name": "Obat",
        "flow": "expense",
        "frequency": "daily",
        "category": "LAYER",
        "stock": None,
        "unit": None,
        "sort_order": 50,
    },
    {
        "code": "daily_wage",
        "name": "Upah Harian",
        "flow": "expense",
        "frequency": "daily",
        "category": "LAYER",
        "stock": None,
        "unit": None,
        "sort_order": 60,
    },
    {
        "code": "kitchen",
        "name": "Bahan Dapur",
        "flow": "expense",
        "frequency": "daily",
        "category": "UMUM",
        "stock": None,
        "unit": None,
        "sort_order": 70,
    },
    {
        "code": "consumables",
        "name": "Bahan Habis Pakai",
        "flow": "expense",
        "frequency": "daily",
        "category": "UMUM",
        "stock": None,
        "unit": None,
        "sort_order": 80,
    },
    {
        "code": "salary",
        "name": "Gaji Karyawan",
        "flow": "expense",
        "frequency": "monthly",
        "category": "UMUM",
        "stock": None,
        "unit": None,
        "sort_order": 90,
    },
    {
        "code": "opening_correction",
        "name": "Koreksi Saldo Awal",
        "flow": "expense",
        "frequency": "daily",
        "category": "UMUM",
        "stock": None,
        "unit": None,
        "is_system": True,
        "sort_order": 100,
    },
)


def _stock_defaults(code: str, stock: dict | None) -> dict:
    values = stock or {}
    entry = values.get(code) or {}
    return {
        "opening_qty": entry.get("qty", Decimal("0")),
        "min_threshold": entry.get("min_threshold"),
    }


@transaction.atomic
def ensure_master_data(*, stock: dict | None = None) -> None:
    """Buat 4 kategori, 3 jenis stok, dan 10 item sistem bila belum ada.

    ``stock`` berbentuk ``{"feed": {"qty": Decimal, "min_threshold": Decimal|None}, ...}``.
    Nilai stok hanya dipakai saat baris dibuat, bukan untuk menimpa data lama.
    """
    categories: dict[str, Category] = {}
    for seed in CATEGORY_SEEDS:
        parent = categories.get(seed["parent"]) if seed["parent"] else None
        category, _ = Category.objects.get_or_create(
            code=seed["code"],
            defaults={
                "name": seed["name"],
                "parent": parent,
                "sort_order": seed["sort_order"],
                "is_system": True,
            },
        )
        categories[seed["code"]] = category

    stock_items: dict[str, StockItem] = {}
    for seed in STOCK_SEEDS:
        stock_item, _ = StockItem.objects.get_or_create(
            code=seed["code"],
            defaults={
                "name": seed["name"],
                "unit": seed["unit"],
                **_stock_defaults(seed["code"], stock),
            },
        )
        stock_items[seed["code"]] = stock_item

    for seed in ITEM_SEEDS:
        Item.objects.get_or_create(
            code=seed["code"],
            defaults={
                "name": seed["name"],
                "flow": seed["flow"],
                "frequency": seed["frequency"],
                "default_category": categories[seed["category"]],
                "stock_item": stock_items[seed["stock"]] if seed["stock"] else None,
                "unit": seed["unit"],
                "default_payment_method": seed.get("payment_method"),
                "is_system": seed.get("is_system", False),
                "sort_order": seed["sort_order"],
            },
        )
