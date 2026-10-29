"""Form saldo awal S-17 (hanya saat kas belum terkunci)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError

from core import messages
from core.errors import DomainError
from core.utils.dates import today_wib
from core.utils.numbers import parse_id_number
from ledger.services.opening import MONEY_MAX


class OpeningBalanceForm(forms.Form):
    opening_balance = forms.CharField(
        label="Saldo awal",
        widget=forms.TextInput(
            attrs={
                "class": "input",
                "inputmode": "decimal",
                "autocomplete": "off",
                "autofocus": True,
            }
        ),
    )
    opening_balance_date = forms.CharField(
        label="Tanggal saldo awal",
        widget=forms.DateInput(attrs={"class": "input", "type": "date"}),
    )

    def __init__(
        self,
        *args,
        business_start_date: date | None = None,
        **kwargs,
    ) -> None:
        self.business_start_date = business_start_date
        super().__init__(*args, **kwargs)

    def clean_opening_balance(self) -> Decimal:
        try:
            return parse_id_number(
                self.cleaned_data["opening_balance"],
                places=2,
                field="Saldo awal",
                min_value=Decimal("0"),
                max_value=MONEY_MAX,
            )
        except DomainError as exc:
            raise ValidationError(exc.message) from exc

    def clean_opening_balance_date(self) -> date:
        raw = self.cleaned_data["opening_balance_date"]
        try:
            value = date.fromisoformat(raw)
        except (TypeError, ValueError) as exc:
            raise ValidationError(messages.DATE_INVALID) from exc
        if value > today_wib():
            raise ValidationError(messages.DATE_AFTER_TODAY)
        if self.business_start_date is not None and value < self.business_start_date:
            raise ValidationError(messages.date_before_business_start(self.business_start_date))
        return value
