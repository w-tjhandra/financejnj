"""Form kategori & item. Validasi bentuk di sini; invariant di service."""

from __future__ import annotations

from django import forms

from core import messages as core_messages
from master.models import (
    FLOW_CHOICES,
    FREQUENCY_CHOICES,
    PAYMENT_METHOD_CHOICES,
    Category,
    Item,
    StockItem,
)


class CategoryForm(forms.Form):
    code = forms.CharField(
        max_length=30,
        label="Kode",
        widget=forms.TextInput(
            attrs={
                "class": "input",
                "autocomplete": "off",
                "autocapitalize": "characters",
                "spellcheck": "false",
                "placeholder": "mis. BROILER",
            }
        ),
    )
    name = forms.CharField(
        max_length=80,
        label="Nama",
        widget=forms.TextInput(attrs={"class": "input", "placeholder": "mis. Broiler"}),
    )
    parent = forms.ModelChoiceField(
        queryset=Category.objects.none(),
        required=False,
        label="Induk",
        empty_label="— Tanpa induk —",
        widget=forms.Select(attrs={"class": "input"}),
    )
    sort_order = forms.IntegerField(
        required=False,
        initial=0,
        label="Urutan",
        widget=forms.NumberInput(attrs={"class": "input", "min": -32768, "max": 32767}),
    )

    def __init__(self, *args, instance: Category | None = None, **kwargs) -> None:
        self.instance = instance
        super().__init__(*args, **kwargs)
        queryset = Category.objects.filter(parent__isnull=True, is_active=True).order_by(
            "sort_order", "id"
        )
        if instance is not None:
            queryset = queryset.exclude(pk=instance.pk)
            self.initial.update(
                {
                    "code": instance.code,
                    "name": instance.name,
                    "parent": instance.parent_id,
                    "sort_order": instance.sort_order,
                }
            )
            if instance.is_system:
                self.fields["code"].disabled = True
                self.fields["code"].help_text = "Kode kategori sistem tidak bisa diubah."
        self.fields["parent"].queryset = queryset

    def clean_code(self) -> str:
        return (self.cleaned_data.get("code") or "").strip().upper()

    def clean_name(self) -> str:
        return (self.cleaned_data.get("name") or "").strip()


class ItemForm(forms.Form):
    name = forms.CharField(
        max_length=80,
        label="Nama item",
        widget=forms.TextInput(attrs={"class": "input", "placeholder": "mis. Pembelian DOC"}),
    )
    flow = forms.ChoiceField(
        choices=FLOW_CHOICES,
        label="Arus",
        widget=forms.Select(attrs={"class": "input"}),
    )
    frequency = forms.ChoiceField(
        choices=FREQUENCY_CHOICES,
        label="Frekuensi",
        widget=forms.Select(attrs={"class": "input"}),
    )
    default_category = forms.ModelChoiceField(
        queryset=Category.objects.none(),
        required=False,
        label="Kategori default",
        empty_label="— Tanpa kategori —",
        widget=forms.Select(attrs={"class": "input"}),
    )
    has_stock = forms.BooleanField(
        required=False,
        label="Terkait stok",
        widget=forms.CheckboxInput(
            attrs={
                "class": "h-5 w-5 rounded border-slate-300 text-emerald-700 focus:ring-emerald-600",
            }
        ),
    )
    stock_item = forms.ModelChoiceField(
        queryset=StockItem.objects.none(),
        required=False,
        label="Jenis stok",
        empty_label="— Pilih jenis stok —",
        widget=forms.Select(attrs={"class": "input"}),
    )
    unit = forms.CharField(
        max_length=10,
        required=False,
        label="Satuan",
        widget=forms.TextInput(
            attrs={"class": "input", "placeholder": "mis. kg, ekor", "autocomplete": "off"}
        ),
    )
    default_payment_method = forms.ChoiceField(
        choices=[("", "— Tidak ditentukan —"), *PAYMENT_METHOD_CHOICES],
        required=False,
        label="Metode bayar default",
        widget=forms.Select(attrs={"class": "input"}),
    )
    sort_order = forms.IntegerField(
        required=False,
        initial=0,
        label="Urutan",
        widget=forms.NumberInput(attrs={"class": "input", "min": -32768, "max": 32767}),
    )

    def __init__(
        self,
        *args,
        instance: Item | None = None,
        used_count: int = 0,
        category_queryset=None,
        stock_queryset=None,
        **kwargs,
    ) -> None:
        self.instance = instance
        self.used_count = used_count
        super().__init__(*args, **kwargs)

        categories = (
            category_queryset
            if category_queryset is not None
            else Category.objects.filter(is_active=True).order_by("sort_order", "id")
        )
        if instance is not None and instance.default_category_id is not None:
            categories = categories | Category.objects.filter(pk=instance.default_category_id)
        self.fields["default_category"].queryset = categories.order_by("sort_order", "id")
        self.fields["stock_item"].queryset = (
            stock_queryset if stock_queryset is not None else StockItem.objects.order_by("id")
        )

        if instance is not None:
            self.initial.update(
                {
                    "name": instance.name,
                    "flow": instance.flow,
                    "frequency": instance.frequency,
                    "default_category": instance.default_category_id,
                    "has_stock": instance.stock_item_id is not None,
                    "stock_item": instance.stock_item_id,
                    "unit": instance.unit or "",
                    "default_payment_method": instance.default_payment_method or "",
                    "sort_order": instance.sort_order,
                }
            )

        if used_count:
            note = core_messages.ITEM_USED_NOTE.format(count=used_count)
            for field_name in ("flow", "frequency", "has_stock", "stock_item"):
                self.fields[field_name].disabled = True
                self.fields[field_name].help_text = note

    def clean_name(self) -> str:
        return (self.cleaned_data.get("name") or "").strip()

    def clean(self):
        cleaned = super().clean()
        has_stock = bool(cleaned.get("has_stock"))
        stock_item = cleaned.get("stock_item")
        unit = (cleaned.get("unit") or "").strip() or None

        if has_stock and stock_item is None:
            self.add_error("stock_item", core_messages.ITEM_STOCK_UNIT)
        elif has_stock:
            # Satuan item ber-stok selalu mengikuti satuan jenis stok.
            cleaned["unit"] = stock_item.unit
        else:
            cleaned["stock_item"] = None
            cleaned["unit"] = unit
        return cleaned
