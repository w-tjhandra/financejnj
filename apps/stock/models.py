"""Pergerakan stok: dari transaksi, input harian, dan penyesuaian."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q

from core.models import SoftDeleteModel
from master.models import StockItem

DIRECTION_VALUES = ["in", "out"]
SOURCE_VALUES = ["transaction", "manual", "adjustment"]


class StockMovement(SoftDeleteModel):
    stock_item = models.ForeignKey(StockItem, on_delete=models.PROTECT, related_name="movements")
    date = models.DateField()
    direction = models.CharField(max_length=3)
    qty = models.DecimalField(max_digits=18, decimal_places=3)
    source = models.CharField(max_length=12)
    transaction = models.ForeignKey(
        "ledger.Transaction",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="stock_movements",
    )
    reason = models.CharField(max_length=300, null=True, blank=True)
    batch_key = models.UUIDField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        ordering = ["date", "id"]
        base_manager_name = "all_objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["transaction", "stock_item"],
                condition=Q(transaction__isnull=False, deleted_at__isnull=True),
                name="uniq_movement_txn_stock",
            ),
            models.UniqueConstraint(
                fields=["batch_key", "stock_item"],
                condition=Q(batch_key__isnull=False, deleted_at__isnull=True),
                name="uniq_batch_stock",
            ),
            models.CheckConstraint(
                condition=(
                    Q(source="transaction") & Q(transaction__isnull=False)
                    | Q(source__in=["manual", "adjustment"]) & Q(transaction__isnull=True)
                ),
                name="movement_source_transaction",
            ),
            models.CheckConstraint(
                condition=Q(direction__in=DIRECTION_VALUES),
                name="movement_direction_allowed",
            ),
            models.CheckConstraint(
                condition=Q(qty__gt=0) & Q(qty__lte=1_000_000),
                name="movement_qty_range",
            ),
            models.CheckConstraint(
                condition=Q(source__in=SOURCE_VALUES), name="movement_source_allowed"
            ),
            models.CheckConstraint(
                condition=~Q(source="adjustment") | Q(reason__regex=r"^.{10,}$"),
                name="adjustment_reason_min10",
            ),
        ]
        indexes = [
            models.Index(
                fields=["stock_item", "date", "id"],
                condition=Q(deleted_at__isnull=True),
                name="movement_stock_date_idx",
            ),
            models.Index(
                fields=["date"],
                condition=Q(deleted_at__isnull=True),
                name="movement_date_alive_idx",
            ),
            models.Index(fields=["transaction"], name="movement_txn_idx"),
            models.Index(
                fields=["batch_key"],
                condition=Q(batch_key__isnull=False),
                name="movement_batch_key_idx",
            ),
        ]

    def __str__(self):
        return f"{self.date} {self.direction} {self.qty}"
