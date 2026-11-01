"""Form saldo awal S-17, koreksi saldo awal, dan form transaksi S-05."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError

from core import messages
from core.errors import DomainError
from core.utils.dates import month_start, today_wib
from core.utils.numbers import format_id_number, format_money, parse_id_number
from ledger.models import ACCOUNT_CHOICES, TRANSFER_BANK_CHOICES, Account
from ledger.services.opening import MONEY_MAX, REASON_MAX, REASON_MIN
from ledger.services.transactions import QTY_MAX
from master.models import FLOW_CHOICES, PAYMENT_METHOD_CHOICES, Category, Item
from master.services.items import active_items

DATE_INPUT_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
PAYMENT_METHOD_FORM_CHOICES = [("", "— Pilih —"), *PAYMENT_METHOD_CHOICES]
FLOW_CHOICES_FORM = [("income", "Pemasukan"), ("expense", "Pengeluaran")]


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


class MultiAccountOpeningBalanceForm(forms.Form):
    opening_balance_date = forms.CharField(
        label="Tanggal saldo awal",
        widget=forms.DateInput(attrs={"class": "input", "type": "date"}),
    )

    def __init__(self, *args, business_start_date: date | None = None, **kwargs) -> None:
        self.business_start_date = business_start_date
        super().__init__(*args, **kwargs)
        for code, label in ACCOUNT_CHOICES:
            self.fields[f"opening_balance_{code}"] = forms.CharField(
                label=f"Saldo awal {label} (Rp)",
                widget=forms.TextInput(
                    attrs={"class": "input", "inputmode": "decimal", "autocomplete": "off"}
                ),
            )

    def clean(self):
        cleaned = super().clean()
        for code, label in ACCOUNT_CHOICES:
            field = f"opening_balance_{code}"
            if field not in cleaned:
                continue
            try:
                cleaned[field] = parse_id_number(
                    cleaned[field],
                    places=2,
                    field=f"Saldo awal {label}",
                    min_value=Decimal("0"),
                    max_value=MONEY_MAX,
                )
            except DomainError as exc:
                self.add_error(field, exc.message)
        raw_date = cleaned.get("opening_balance_date")
        if raw_date:
            try:
                value_date = date.fromisoformat(raw_date)
            except (TypeError, ValueError):
                self.add_error("opening_balance_date", messages.DATE_INVALID)
            else:
                if value_date > today_wib():
                    self.add_error("opening_balance_date", messages.DATE_AFTER_TODAY)
                elif (
                    self.business_start_date is not None
                    and value_date < self.business_start_date
                ):
                    self.add_error(
                        "opening_balance_date",
                        messages.date_before_business_start(self.business_start_date),
                    )
                else:
                    cleaned["opening_balance_date"] = value_date
        return cleaned


class AccountTransferForm(forms.Form):
    date = forms.DateField(
        label="Tanggal",
        widget=forms.DateInput(attrs={"class": "input", "type": "date"}),
    )
    from_account = forms.ModelChoiceField(
        label="Dari sumber",
        queryset=Account.objects.none(),
        widget=forms.Select(attrs={"class": "input"}),
    )
    to_account = forms.ModelChoiceField(
        label="Ke sumber",
        queryset=Account.objects.none(),
        widget=forms.Select(attrs={"class": "input"}),
    )
    amount = forms.CharField(
        label="Nominal (Rp)",
        widget=forms.TextInput(
            attrs={"class": "input", "inputmode": "decimal", "autocomplete": "off"}
        ),
    )
    notes = forms.CharField(
        label="Keterangan",
        required=False,
        max_length=500,
        widget=forms.TextInput(attrs={"class": "input", "autocomplete": "off"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        accounts = Account.objects.filter(is_active=True, code__isnull=False).order_by("id")
        self.fields["from_account"].queryset = accounts
        self.fields["to_account"].queryset = accounts

    def clean_amount(self) -> Decimal:
        try:
            return parse_id_number(
                self.cleaned_data["amount"],
                places=2,
                field="Nominal",
                min_value=Decimal("0.01"),
                max_value=MONEY_MAX,
            )
        except DomainError as exc:
            raise ValidationError(exc.message) from exc

    def clean_notes(self) -> str:
        return (self.cleaned_data.get("notes") or "").strip()

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("from_account") == cleaned.get("to_account"):
            self.add_error("to_account", "Pilih sumber uang yang berbeda.")
        return cleaned


class TransactionForm(forms.Form):
    """Form transaksi S-05 (baru/edit).

    Form hanya memvalidasi bentuk dan menormalisasi input id-ID. Invariant
    lintas tabel (stok, kunci periode, unik gaji) tetap milik service.
    """

    date = forms.CharField(
        label="Tanggal",
        widget=forms.TextInput(attrs={"class": "input", "type": "date"}),
        error_messages={"required": "Tanggal wajib diisi."},
    )
    flow = forms.ChoiceField(
        choices=FLOW_CHOICES,
        label="Arus",
        widget=forms.Select(attrs={"class": "input"}),
    )
    item = forms.ModelChoiceField(
        queryset=Item.objects.none(),
        label="Item",
        empty_label="— Pilih item —",
        widget=forms.Select(
            attrs={
                "class": "input",
                "hx-get": "/transaksi/field-item",
                "hx-trigger": "change",
                "hx-target": "#item-fields",
                "hx-include": "#id_item, #id_date, #id_flow, #id_payment_method, #id_transfer_bank",
                "hx-swap": "innerHTML",
            }
        ),
        error_messages={
            "required": "Item wajib dipilih.",
            "invalid_choice": messages.ITEM_FLOW_INVALID,
        },
    )
    category = forms.ModelChoiceField(
        queryset=Category.objects.none(),
        label="Kategori",
        empty_label="— Pilih kategori —",
        widget=forms.Select(attrs={"class": "input"}),
        error_messages={
            "required": "Kategori wajib dipilih.",
            "invalid_choice": "Kategori tidak valid.",
        },
    )
    amount = forms.CharField(
        label="Nominal",
        widget=forms.TextInput(
            attrs={
                "class": "input",
                "inputmode": "decimal",
                "autocomplete": "off",
                "placeholder": "mis. 520.000",
            }
        ),
        error_messages={"required": messages.NUMBER_INVALID.format(field="Nominal")},
    )
    qty = forms.CharField(
        required=False,
        label="Qty",
        widget=forms.TextInput(
            attrs={
                "class": "input",
                "inputmode": "decimal",
                "autocomplete": "off",
                "placeholder": "mis. 20",
            }
        ),
    )
    unit = forms.CharField(
        required=False,
        max_length=10,
        label="Satuan",
        widget=forms.TextInput(
            attrs={
                "class": "input",
                "autocomplete": "off",
                "placeholder": "mis. kg, ekor",
            }
        ),
    )
    payment_method = forms.ChoiceField(
        required=False,
        choices=PAYMENT_METHOD_FORM_CHOICES,
        label="Metode bayar",
        widget=forms.Select(attrs={"class": "input"}),
    )
    transfer_bank = forms.ChoiceField(
        required=False,
        choices=[("", "— Pilih bank —"), *TRANSFER_BANK_CHOICES],
        label="Bank transfer",
        widget=forms.Select(attrs={"class": "input"}),
    )
    notes = forms.CharField(
        required=False,
        max_length=500,
        label="Keterangan",
        widget=forms.Textarea(
            attrs={
                "class": "input min-h-[5rem]",
                "rows": 3,
                "placeholder": "Opsional, maksimum 500 karakter.",
            }
        ),
        error_messages={"max_length": "Keterangan maksimum 500 karakter."},
    )
    period_month = forms.CharField(
        required=False,
        label="Bulan gaji",
        widget=forms.TextInput(attrs={"class": "input", "type": "month"}),
    )

    def __init__(
        self,
        *args,
        instance=None,
        read_only: bool = False,
        **kwargs,
    ) -> None:
        self.instance = instance
        self.read_only = read_only
        initial = dict(kwargs.pop("initial", None) or {})
        data = kwargs.get("data")
        if data is None and args:
            data = args[0]
        flow = self._raw_value(data, initial, "flow")
        if not flow:
            flow = instance.flow if instance is not None else "expense"
            initial.setdefault("flow", flow)
        item_value = self._raw_value(data, initial, "item")
        item = self._resolve_item(item_value)

        if item is not None:
            initial.setdefault("item", item.pk)
            if not self._raw_value(data, initial, "category") and item.default_category_id:
                initial.setdefault("category", item.default_category_id)
            if data is None and not self._raw_value(data, initial, "payment_method"):
                initial["payment_method"] = item.default_payment_method or ""
            if item.frequency == "monthly" and not self._raw_value(data, initial, "period_month"):
                period = self._default_period(initial, data).strftime("%Y-%m")
                initial.setdefault("period_month", period)
        initial.setdefault("date", today_wib().isoformat())

        super().__init__(*args, initial=initial, **kwargs)

        self.fields["date"].widget.attrs["max"] = today_wib().isoformat()
        self.fields["flow"].widget.attrs.update(
            {
                "hx-get": "/transaksi/opsi-item",
                "hx-trigger": "change",
                "hx-target": "#id_item",
                "hx-include": "this",
                "hx-swap": "innerHTML",
            }
        )

        category_queryset = Category.objects.filter(is_active=True).order_by("sort_order", "id")
        if instance is not None and instance.category_id is not None:
            category_queryset = category_queryset | Category.objects.filter(pk=instance.category_id)
        self.fields["category"].queryset = category_queryset.order_by("sort_order", "id")

        item_queryset = active_items(flow=flow)
        if instance is not None and instance.item_id is not None:
            item_queryset = item_queryset | Item.objects.filter(pk=instance.item_id)
        self.fields["item"].queryset = item_queryset.order_by("sort_order", "id")

        if item is not None and item.stock_item_id is not None:
            self.fields["unit"].widget.attrs["readonly"] = True
            self.fields["unit"].help_text = f"Mengikuti satuan stok ({item.stock_item.unit})."
        if read_only:
            self.disable_all()

    @staticmethod
    def _raw_value(data, initial: dict, name: str):
        if data is not None:
            return data.get(name)
        value = initial.get(name)
        if isinstance(value, Item) or isinstance(value, Category):
            return value.pk
        return value

    @staticmethod
    def _resolve_item(value) -> Item | None:
        if value in (None, ""):
            return None
        if isinstance(value, Item):
            return value
        try:
            return Item.objects.select_related("stock_item").filter(pk=int(value)).first()
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _default_period(initial: dict, data) -> date:
        raw = (data.get("date") if data is not None else None) or initial.get("date")
        for value in (raw, today_wib()):
            if isinstance(value, date):
                return month_start(value)
            try:
                return month_start(date.fromisoformat(str(value)))
            except (TypeError, ValueError):
                continue
        return month_start(today_wib())

    @property
    def selected_item(self) -> Item | None:
        value = self.data.get("item") if self.is_bound else self.initial.get("item")
        return self._resolve_item(value)

    def disable_all(self) -> None:
        for field in self.fields.values():
            field.disabled = True

    def clean_date(self) -> date:
        raw = (self.cleaned_data.get("date") or "").strip()
        for fmt in DATE_INPUT_FORMATS:
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                continue
        raise ValidationError(messages.DATE_INVALID)

    def clean_amount(self) -> Decimal:
        try:
            return parse_id_number(
                self.cleaned_data["amount"],
                places=2,
                field="Nominal",
                min_value=Decimal("0.01"),
                max_value=MONEY_MAX,
            )
        except DomainError as exc:
            raise ValidationError(exc.message) from exc

    def clean_qty(self) -> Decimal | None:
        raw = (self.cleaned_data.get("qty") or "").strip()
        if not raw:
            return None
        try:
            return parse_id_number(
                raw,
                places=3,
                field="Qty",
                min_value=Decimal("0.001"),
                max_value=QTY_MAX,
            )
        except DomainError as exc:
            raise ValidationError(exc.message) from exc

    def clean_unit(self) -> str | None:
        text = (self.cleaned_data.get("unit") or "").strip()
        return text or None

    def clean_period_month(self) -> date | None:
        raw = (self.cleaned_data.get("period_month") or "").strip()
        if not raw:
            return None
        try:
            if MONTH_RE.match(raw):
                year, month = (int(part) for part in raw.split("-"))
                return date(year, month, 1)
            return month_start(date.fromisoformat(raw))
        except ValueError as exc:
            raise ValidationError(messages.PERIOD_INVALID) from exc

    def clean_notes(self) -> str:
        return (self.cleaned_data.get("notes") or "").strip()

    def clean(self):
        cleaned = super().clean()
        flow = cleaned.get("flow")
        item = cleaned.get("item")
        if flow and item is not None and item.flow != flow:
            self.add_error("item", messages.ITEM_FLOW_INVALID)
        if item is not None and item.stock_item_id is not None:
            cleaned["unit"] = item.stock_item.unit
        if item is not None and not cleaned.get("payment_method"):
            cleaned["payment_method"] = item.default_payment_method or None
        if cleaned.get("payment_method") == "transfer":
            if not cleaned.get("transfer_bank"):
                self.add_error("transfer_bank", "Pilih bank untuk transaksi transfer.")
        else:
            cleaned["transfer_bank"] = None
        return cleaned


def transaction_initial(txn) -> dict:
    """Nilai awal form edit dari transaksi tersimpan (angka gaya id-ID)."""
    return {
        "date": txn.date.isoformat(),
        "flow": txn.flow,
        "category": txn.category_id,
        "item": txn.item_id,
        "amount": format_money(txn.amount),
        "qty": format_id_number(txn.qty, 3, trim=True) if txn.qty is not None else "",
        "unit": txn.unit or "",
        "payment_method": txn.payment_method or "",
        "transfer_bank": txn.transfer_bank or "",
        "notes": txn.notes,
        "period_month": txn.period_month.strftime("%Y-%m") if txn.period_month else "",
    }


class OpeningCorrectionForm(forms.Form):
    """Form koreksi saldo awal (S-17).

    - Tanggal: read-only, mengikuti opening_balance_date
    - Arus: Pemasukan/Pengeluaran
    - Nominal: 0.01 – 1e11
    - Keterangan: wajib ≥10 karakter
    - Item & kategori: sistem (hidden, tidak ditampilkan)
    """

    date = forms.DateField(
        label="Tanggal",
        widget=forms.DateInput(attrs={"class": "input", "type": "date", "readonly": True}),
    )
    account_code = forms.ChoiceField(
        required=False,
        choices=ACCOUNT_CHOICES,
        label="Sumber uang",
        widget=forms.Select(attrs={"class": "input"}),
    )
    flow = forms.ChoiceField(
        choices=FLOW_CHOICES_FORM,
        label="Arus",
        widget=forms.Select(attrs={"class": "input"}),
    )
    amount = forms.CharField(
        label="Nominal (Rp)",
        widget=forms.TextInput(
            attrs={
                "class": "input",
                "inputmode": "decimal",
                "autocomplete": "off",
                "placeholder": "mis. 1.000.000",
            }
        ),
        error_messages={"required": messages.NUMBER_INVALID.format(field="Nominal")},
    )
    reason = forms.CharField(
        label="Keterangan",
        min_length=REASON_MIN,
        max_length=REASON_MAX,
        widget=forms.Textarea(
            attrs={
                "class": "input min-h-[5rem]",
                "rows": 3,
                "placeholder": f"Minimal {REASON_MIN} karakter, maksimum {REASON_MAX}.",
            }
        ),
        error_messages={
            "required": messages.REASON_MIN_10,
            "min_length": messages.REASON_MIN_10,
            "max_length": f"Keterangan maksimum {REASON_MAX} karakter.",
        },
    )

    def __init__(
        self,
        *args,
        opening_balance_date: date | None = None,
        account_code: str = "cash",
        **kwargs,
    ) -> None:
        self.opening_balance_date = opening_balance_date
        initial = dict(kwargs.pop("initial", None) or {})
        initial.setdefault("account_code", account_code)
        if opening_balance_date is not None:
            initial.setdefault("date", opening_balance_date.isoformat())
        super().__init__(*args, initial=initial, **kwargs)
        if opening_balance_date is not None:
            self.fields["date"].initial = opening_balance_date.isoformat()
            self.fields["date"].widget.attrs["value"] = opening_balance_date.isoformat()

    def clean_amount(self) -> Decimal:
        try:
            return parse_id_number(
                self.cleaned_data["amount"],
                places=2,
                field="Nominal",
                min_value=Decimal("0.01"),
                max_value=MONEY_MAX,
            )
        except DomainError as exc:
            raise ValidationError(exc.message) from exc

    def clean_date(self) -> date:
        """Tanggal harus sama dengan opening_balance_date (server-side validation)."""
        value = self.cleaned_data.get("date")
        if self.opening_balance_date is not None and value != self.opening_balance_date:
            raise ValidationError("Tanggal koreksi harus sama dengan tanggal saldo awal.")
        return value

    def clean_reason(self) -> str:
        return (self.cleaned_data.get("reason") or "").strip()

    def clean_account_code(self) -> str:
        return self.cleaned_data.get("account_code") or "cash"
