"""Form wizard setup. Validasi di server; pesan memakai Bahasa Indonesia."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from core import messages as core_messages
from core.errors import DomainError
from core.utils.dates import today_wib
from core.utils.numbers import parse_id_number
from onboarding.services import messages as setup_messages

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.]+$")
USERNAME_MIN = 3
USERNAME_MAX = 30
PASSWORD_MIN = 10
MONEY_MAX = Decimal("100000000000")
STOCK_MAX = Decimal("1000000")


def _parse_date(raw: str | None) -> date:
    if not raw:
        raise ValidationError(setup_messages.DATE_REQUIRED)
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValidationError(setup_messages.DATE_INVALID) from exc


class AccountSetupForm(forms.Form):
    username = forms.CharField(
        max_length=USERNAME_MAX,
        widget=forms.TextInput(
            attrs={
                "class": "input",
                "autocomplete": "username",
                "autofocus": True,
                "autocapitalize": "none",
                "spellcheck": "false",
            }
        ),
    )
    first_name = forms.CharField(
        max_length=150,
        required=False,
        label="Nama tampilan",
        widget=forms.TextInput(attrs={"class": "input", "autocomplete": "name"}),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={"class": "input", "autocomplete": "new-password"}
        )
    )
    password_confirm = forms.CharField(
        label="Konfirmasi password",
        widget=forms.PasswordInput(
            attrs={"class": "input", "autocomplete": "new-password"}
        ),
    )

    def clean_username(self) -> str:
        username = (self.cleaned_data["username"] or "").strip()
        if not username:
            raise ValidationError(setup_messages.USERNAME_REQUIRED)
        if not (USERNAME_MIN <= len(username) <= USERNAME_MAX) or not USERNAME_RE.match(
            username
        ):
            raise ValidationError(setup_messages.USERNAME_FORMAT)
        if get_user_model().objects.filter(username__iexact=username).exists():
            raise ValidationError(setup_messages.USERNAME_TAKEN)
        return username

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password") or ""
        confirm = cleaned.get("password_confirm") or ""
        username = cleaned.get("username") or ""

        if len(password) < PASSWORD_MIN:
            self.add_error("password", core_messages.PASSWORD_MIN)
        elif username and password.lower() == username.lower():
            self.add_error("password", setup_messages.PASSWORD_SAME_AS_USERNAME)

        if password and confirm and password != confirm:
            self.add_error("password_confirm", setup_messages.PASSWORD_MISMATCH)
        return cleaned


class ProfileSetupForm(forms.Form):
    name = forms.CharField(
        max_length=100,
        required=False,
        label="Nama usaha",
        widget=forms.TextInput(attrs={"class": "input", "autofocus": True}),
    )
    business_start_date = forms.CharField(
        required=False,
        label="Tanggal mulai usaha",
        widget=forms.DateInput(attrs={"class": "input", "type": "date"}),
    )

    def clean_name(self) -> str:
        name = (self.cleaned_data["name"] or "").strip()
        if not name:
            raise ValidationError(setup_messages.BUSINESS_NAME_REQUIRED)
        return name

    def clean_business_start_date(self):
        raw = self.cleaned_data.get("business_start_date")
        if not raw:
            return None
        value = _parse_date(raw)
        if value > today_wib():
            raise ValidationError(setup_messages.BUSINESS_START_AFTER_TODAY)
        return value


class BalanceSetupForm(forms.Form):
    opening_balance = forms.CharField(
        label="Saldo awal",
        widget=forms.TextInput(
            attrs={"class": "input", "inputmode": "decimal", "autofocus": True}
        ),
    )
    opening_balance_date = forms.CharField(
        label="Tanggal saldo awal",
        widget=forms.DateInput(attrs={"class": "input", "type": "date"}),
    )

    def __init__(self, *args, business_start_date: date | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.business_start_date = business_start_date

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
        value = _parse_date(self.cleaned_data["opening_balance_date"])
        if value > today_wib():
            raise ValidationError(core_messages.DATE_AFTER_TODAY)
        if self.business_start_date and value < self.business_start_date:
            raise ValidationError(
                core_messages.date_before_business_start(self.business_start_date)
            )
        return value


class StockSetupForm(forms.Form):
    feed_qty = forms.CharField(
        label="Pakan (kg)",
        widget=forms.TextInput(attrs={"class": "input", "inputmode": "decimal"}),
    )
    feed_min = forms.CharField(
        label="Ambang minimum pakan (kg)",
        required=False,
        widget=forms.TextInput(attrs={"class": "input", "inputmode": "decimal"}),
    )
    egg_qty = forms.CharField(
        label="Telur (kg)",
        widget=forms.TextInput(attrs={"class": "input", "inputmode": "decimal"}),
    )
    egg_min = forms.CharField(
        label="Ambang minimum telur (kg)",
        required=False,
        widget=forms.TextInput(attrs={"class": "input", "inputmode": "decimal"}),
    )
    manure_qty = forms.CharField(
        label="Kotoran (karung)",
        widget=forms.TextInput(attrs={"class": "input", "inputmode": "decimal"}),
    )
    manure_min = forms.CharField(
        label="Ambang minimum kotoran (karung)",
        required=False,
        widget=forms.TextInput(attrs={"class": "input", "inputmode": "decimal"}),
    )

    def _qty(self, field: str, label: str) -> Decimal:
        try:
            return parse_id_number(
                self.cleaned_data[field],
                places=3,
                field=label,
                min_value=Decimal("0"),
                max_value=STOCK_MAX,
            )
        except DomainError as exc:
            raise ValidationError(exc.message) from exc

    def _threshold(self, field: str, label: str) -> Decimal | None:
        raw = self.cleaned_data.get(field)
        if not raw:
            return None
        try:
            return parse_id_number(
                raw,
                places=3,
                field=label,
                min_value=Decimal("0"),
                max_value=STOCK_MAX,
            )
        except DomainError as exc:
            raise ValidationError(exc.message) from exc

    def clean_feed_qty(self):
        return self._qty("feed_qty", "Qty pakan")

    def clean_feed_min(self):
        return self._threshold("feed_min", "Ambang pakan")

    def clean_egg_qty(self):
        return self._qty("egg_qty", "Qty telur")

    def clean_egg_min(self):
        return self._threshold("egg_min", "Ambang telur")

    def clean_manure_qty(self):
        return self._qty("manure_qty", "Qty kotoran")

    def clean_manure_min(self):
        return self._threshold("manure_min", "Ambang kotoran")

    def stock_draft(self) -> dict[str, dict]:
        cleaned = self.cleaned_data
        return {
            code: {
                "qty": str(cleaned[f"{code}_qty"]),
                "min_threshold": (
                    str(cleaned[f"{code}_min"]) if cleaned.get(f"{code}_min") else None
                ),
            }
            for code in ("feed", "egg", "manure")
        }
