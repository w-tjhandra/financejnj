"""Master data: kategori usaha, item, dan jenis stok."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower

from core import messages
from core.models import TimeStampedModel

FLOW_CHOICES = [("income", "Pemasukan"), ("expense", "Pengeluaran")]
FREQUENCY_CHOICES = [("daily", "Harian"), ("monthly", "Bulanan")]
PAYMENT_METHOD_CHOICES = [("cash", "Tunai"), ("transfer", "Transfer")]
STOCK_CODES = ["feed", "egg", "manure"]


class Category(TimeStampedModel):
    code = models.CharField(max_length=30)
    name = models.CharField(max_length=80)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
    )
    sort_order = models.SmallIntegerField(default=0)
    is_system = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "id"]
        constraints = [
            models.UniqueConstraint(Lower("code"), name="uniq_category_code_ci"),
            models.CheckConstraint(
                condition=~Q(id=F("parent_id")), name="category_parent_not_self"
            ),
        ]
        indexes = [
            models.Index(fields=["parent"], name="category_parent_idx"),
            models.Index(fields=["is_active", "sort_order"], name="category_active_sort_idx"),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        self.code = (self.code or "").strip().upper()
        if self.parent_id is not None:
            if self.pk is not None and self.parent_id == self.pk:
                raise ValidationError({"parent": messages.CATEGORY_DEPTH})
            parent = self.parent
            if parent is not None and parent.parent_id is not None:
                raise ValidationError({"parent": messages.CATEGORY_DEPTH})


class StockItem(TimeStampedModel):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=50)
    unit = models.CharField(max_length=10)
    opening_qty = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    min_threshold = models.DecimalField(max_digits=18, decimal_places=3, null=True, blank=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(code__in=STOCK_CODES), name="stock_item_code_allowed"
            ),
            models.CheckConstraint(condition=Q(opening_qty__gte=0), name="stock_item_opening_gte0"),
            models.CheckConstraint(
                condition=Q(min_threshold__isnull=True) | Q(min_threshold__gte=0),
                name="stock_item_min_gte0",
            ),
        ]

    def __str__(self):
        return self.name


class Item(TimeStampedModel):
    code = models.CharField(max_length=40, unique=True, null=True, blank=True)
    name = models.CharField(max_length=80)
    flow = models.CharField(max_length=10, choices=FLOW_CHOICES)
    frequency = models.CharField(max_length=10, choices=FREQUENCY_CHOICES, default="daily")
    default_category = models.ForeignKey(
        Category,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="items",
    )
    stock_item = models.ForeignKey(
        StockItem,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="items",
    )
    unit = models.CharField(max_length=10, null=True, blank=True)
    default_payment_method = models.CharField(
        max_length=10, choices=PAYMENT_METHOD_CHOICES, null=True, blank=True
    )
    is_system = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    sort_order = models.SmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["name", "flow"], name="uniq_item_name_flow"),
            models.CheckConstraint(
                condition=Q(flow__in=["income", "expense"]), name="item_flow_allowed"
            ),
            models.CheckConstraint(
                condition=Q(frequency__in=["daily", "monthly"]),
                name="item_frequency_allowed",
            ),
            models.CheckConstraint(
                condition=Q(default_payment_method__isnull=True)
                | Q(default_payment_method__in=["cash", "transfer"]),
                name="item_payment_method_allowed",
            ),
            models.CheckConstraint(
                condition=Q(stock_item__isnull=True) | Q(unit__isnull=False),
                name="item_stock_requires_unit",
            ),
        ]
        indexes = [
            models.Index(
                fields=["flow", "is_active", "sort_order"], name="item_flow_active_sort_idx"
            ),
            models.Index(fields=["stock_item"], name="item_stock_item_idx"),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        # Normalisasi string kosong ke NULL agar CHECK "ber-stok wajib unit" benar.
        if self.unit == "":
            self.unit = None
        if self.default_payment_method == "":
            self.default_payment_method = None
        if self.stock_item_id is not None and not self.unit:
            raise ValidationError({"unit": messages.ITEM_STOCK_UNIT})
