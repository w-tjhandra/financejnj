"""Form pengaturan stok S-16."""

from __future__ import annotations

from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError

from core import messages
from core.errors import DomainError
from core.utils.numbers import format_id_number, parse_id_number
from master.models import StockItem

QTY_MAX = Decimal("1000000")


class StockSettingsForm(forms.Form):
    min_threshold = forms.CharField(
        required=False,
        label="Ambang minimum",
        widget=forms.TextInput(
            attrs={"class": "input", "inputmode": "decimal", "autocomplete": "off"}
        ),
    )
    opening_qty = forms.CharField(
        label="Stok awal",
        error_messages={"required": "Stok awal wajib diisi."},
        widget=forms.TextInput(
            attrs={"class": "input", "inputmode": "decimal", "autocomplete": "off"}
        ),
    )

    def __init__(
        self,
        *args,
        stock_item: StockItem,
        locked_since=None,
        **kwargs,
    ) -> None:
        self.stock_item = stock_item
        super().__init__(*args, **kwargs)
        self.fields["min_threshold"].label = f"Ambang minimum ({stock_item.unit})"
        self.fields["opening_qty"].label = f"Stok awal ({stock_item.unit})"
        self.initial.update(
            {
                "min_threshold": (
                    format_id_number(stock_item.min_threshold, 3, trim=True)
                    if stock_item.min_threshold is not None
                    else ""
                ),
                "opening_qty": format_id_number(stock_item.opening_qty, 3, trim=True),
            }
        )
        if locked_since is not None:
            self.fields["opening_qty"].disabled = True
            self.fields["opening_qty"].help_text = messages.stock_opening_locked(locked_since)

    def _parse(self, field: str, label: str, *, required: bool) -> Decimal | None:
        raw = self.cleaned_data.get(field)
        if not raw:
            if required:
                raise ValidationError(messages.NUMBER_INVALID.format(field=label))
            return None
        try:
            return parse_id_number(
                raw,
                places=3,
                field=label,
                min_value=Decimal("0"),
                max_value=QTY_MAX,
            )
        except DomainError as exc:
            raise ValidationError(exc.message) from exc

    def clean_min_threshold(self) -> Decimal | None:
        return self._parse("min_threshold", "Ambang minimum", required=False)

    def clean_opening_qty(self) -> Decimal:
        parsed = self._parse("opening_qty", "Stok awal", required=True)
        assert parsed is not None  # required=True selalu mengembalikan Decimal
        return parsed
