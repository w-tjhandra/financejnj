"""Ledger: akun kas, transaksi, dan lampiran transaksi."""

from __future__ import annotations

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import Q

from core.models import SoftDeleteModel, TimeStampedModel
from master.models import Category, Item

CURRENCY_RE = r"^[A-Z]{3}$"
FLOW_VALUES = ["income", "expense"]
PAYMENT_METHOD_VALUES = ["cash", "transfer"]
ATTACHMENT_MIME_TYPES = [
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/pdf",
]
ATTACHMENT_MAX_BYTES = 10 * 1024 * 1024


class Account(TimeStampedModel):
    name = models.CharField(max_length=100, default="Kas Utama")
    type = models.CharField(max_length=20, default="cash")
    currency = models.CharField(max_length=3, default="IDR")
    opening_balance = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    opening_balance_date = models.DateField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(type__in=["cash", "bank"]), name="account_type_allowed"
            ),
            models.CheckConstraint(
                condition=Q(currency__regex=CURRENCY_RE), name="account_currency_format"
            ),
            models.CheckConstraint(
                condition=Q(opening_balance__gte=0), name="account_opening_gte0"
            ),
        ]
        indexes = [models.Index(fields=["is_active"], name="account_is_active_idx")]

    def __str__(self):
        return self.name

    @classmethod
    def current(cls):
        return cls.objects.filter(is_active=True).order_by("id").first()


class Transaction(SoftDeleteModel):
    date = models.DateField()
    flow = models.CharField(max_length=10)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="transactions")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="transactions")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="transactions")
    currency = models.CharField(max_length=3, default="IDR")
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    qty = models.DecimalField(max_digits=18, decimal_places=3, null=True, blank=True)
    unit = models.CharField(max_length=10, null=True, blank=True)
    payment_method = models.CharField(max_length=10, null=True, blank=True)
    notes = models.CharField(max_length=500, blank=True, default="")
    period_month = models.DateField(null=True, blank=True)
    is_opening_correction = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="transactions_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    idempotency_key = models.UUIDField(null=True, blank=True, unique=True)

    class Meta:
        ordering = ["-date", "-id"]
        base_manager_name = "all_objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["item", "category", "account", "period_month"],
                condition=Q(deleted_at__isnull=True, period_month__isnull=False),
                name="uniq_active_monthly_salary",
            ),
            models.CheckConstraint(
                condition=Q(amount__gt=0) & Q(amount__lte=100_000_000_000),
                name="txn_amount_range",
            ),
            models.CheckConstraint(
                condition=Q(qty__isnull=True) | (Q(qty__gt=0) & Q(qty__lte=1_000_000)),
                name="txn_qty_range",
            ),
            models.CheckConstraint(
                condition=Q(qty__isnull=True) | Q(unit__isnull=False),
                name="txn_qty_requires_unit",
            ),
            models.CheckConstraint(
                condition=Q(period_month__isnull=True) | Q(period_month__day=1),
                name="txn_period_month_first",
            ),
            models.CheckConstraint(
                condition=Q(payment_method__isnull=True)
                | Q(payment_method__in=PAYMENT_METHOD_VALUES),
                name="txn_payment_method_allowed",
            ),
            models.CheckConstraint(condition=Q(flow__in=FLOW_VALUES), name="txn_flow_allowed"),
            models.CheckConstraint(
                condition=Q(currency__regex=CURRENCY_RE), name="txn_currency_format"
            ),
        ]
        indexes = [
            models.Index(fields=["date"], name="txn_date_idx"),
            models.Index(
                fields=["date"], condition=Q(deleted_at__isnull=True), name="txn_date_alive_idx"
            ),
            models.Index(fields=["category", "date"], name="txn_category_date_idx"),
            models.Index(fields=["item", "date"], name="txn_item_date_idx"),
            models.Index(fields=["account", "date"], name="txn_account_date_idx"),
            models.Index(
                fields=["-date", "-id"],
                condition=Q(deleted_at__isnull=True),
                name="txn_date_id_alive_idx",
            ),
            GinIndex(
                fields=["notes"],
                name="txn_notes_gin_idx",
                opclasses=["gin_trgm_ops"],
            ),
        ]

    def __str__(self):
        return f"{self.date} {self.flow} {self.amount}"


class Attachment(SoftDeleteModel):
    transaction = models.ForeignKey(
        Transaction, on_delete=models.PROTECT, related_name="attachments"
    )
    file = models.CharField(max_length=255)
    original_name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=100)
    size_bytes = models.PositiveIntegerField()
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        ordering = ["id"]
        base_manager_name = "all_objects"
        default_manager_name = "objects"
        constraints = [
            models.CheckConstraint(
                condition=Q(mime_type__in=ATTACHMENT_MIME_TYPES),
                name="attachment_mime_allowed",
            ),
            models.CheckConstraint(
                condition=Q(size_bytes__gt=0) & Q(size_bytes__lte=ATTACHMENT_MAX_BYTES),
                name="attachment_size_range",
            ),
        ]
        indexes = [
            models.Index(
                fields=["transaction"],
                condition=Q(deleted_at__isnull=True),
                name="attachment_txn_alive_idx",
            )
        ]

    def __str__(self):
        return self.original_name
