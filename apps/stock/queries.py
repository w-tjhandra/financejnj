"""Query baca stok: stok saat ini, status kunci awal, dan kartu S-16."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db.models import Q, Sum

from core import messages
from core.utils.numbers import format_id_number
from master.models import StockItem
from stock.models import StockMovement


def _locked_since(stock_item_id: int) -> date | None:
    """Tanggal movement pertama, termasuk baris yang sudah di-soft-delete (BR-01)."""
    return (
        StockMovement.all_objects.filter(stock_item_id=stock_item_id)
        .order_by("date", "id")
        .values_list("date", flat=True)
        .first()
    )


def stock_is_locked(stock_item_id: int) -> bool:
    return StockMovement.all_objects.filter(stock_item_id=stock_item_id).exists()


def stock_locked_since(stock_item_id: int) -> date | None:
    return _locked_since(stock_item_id)


def current_qty(stock_item: StockItem) -> Decimal:
    """`opening + in − out` hanya dari movement aktif (BR-03, AC-06.2)."""
    totals = StockMovement.objects.filter(stock_item=stock_item).aggregate(
        total_in=Sum("qty", filter=Q(direction="in")),
        total_out=Sum("qty", filter=Q(direction="out")),
    )
    total_in = totals["total_in"] or Decimal("0")
    total_out = totals["total_out"] or Decimal("0")
    return stock_item.opening_qty + total_in - total_out


@dataclass(frozen=True)
class StockCard:
    stock_item: StockItem
    current_qty: Decimal
    locked_since: date | None
    is_low: bool

    @property
    def opening_qty(self) -> Decimal:
        return self.stock_item.opening_qty

    @property
    def min_threshold(self) -> Decimal | None:
        return self.stock_item.min_threshold

    @property
    def unit(self) -> str:
        return self.stock_item.unit

    @property
    def is_locked(self) -> bool:
        return self.locked_since is not None

    @property
    def locked_message(self) -> str:
        if self.locked_since is None:
            return ""
        return messages.stock_opening_locked(self.locked_since)

    @property
    def opening_display(self) -> str:
        return format_id_number(self.opening_qty, 3, trim=True)

    @property
    def current_display(self) -> str:
        return format_id_number(self.current_qty, 3, trim=True)

    @property
    def min_display(self) -> str:
        if self.min_threshold is None:
            return "—"
        return format_id_number(self.min_threshold, 3, trim=True)


def stock_overview() -> list[StockCard]:
    """Tepat tiga jenis stok; angka dihitung di service, bukan template."""
    cards: list[StockCard] = []
    for stock_item in StockItem.objects.order_by("id"):
        locked_since = _locked_since(stock_item.pk)
        on_hand = current_qty(stock_item)
        threshold = stock_item.min_threshold
        cards.append(
            StockCard(
                stock_item=stock_item,
                current_qty=on_hand,
                locked_since=locked_since,
                is_low=threshold is not None and on_hand < threshold,
            )
        )
    return cards
