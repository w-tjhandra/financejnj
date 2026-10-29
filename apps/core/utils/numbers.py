"""Parser & formatter angka id-ID (BR-11, AC-24.3…24.8).

Satu implementasi dipakai form, service, dan test. Uang memakai 2 desimal,
qty memakai 3 desimal; keduanya `Decimal` (tidak pernah `float`).
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from core import messages
from core.errors import DomainError

_THOUSANDS_RE = re.compile(r"^\d{1,3}(\.\d{3})+$")


def _min_message(field: str) -> str:
    if field.lower().startswith("nominal"):
        return messages.AMOUNT_MIN
    return f"{field} harus lebih dari 0."


def _max_message(field: str, max_value: Decimal, places: int) -> str:
    lowered = field.lower()
    if lowered.startswith("nominal"):
        return messages.AMOUNT_MAX
    if lowered.startswith(("qty", "jumlah")):
        return messages.QTY_MAX
    return f"{field} maksimum {format_id_number(max_value, places)}."


def _normalize(raw: object) -> tuple[str, bool]:
    """Bersihkan input menjadi digit + satu titik desimal. Kembalikan (teks, negatif)."""
    text = "" if raw is None else str(raw)
    text = text.strip()
    text = re.sub(r"(?i)\brp\b", "", text)
    # Buang semua karakter selain digit dan pemisah; spasi ikut hilang.
    text = re.sub(r"[^0-9.,\-]", "", text)

    negative = text.startswith("-")
    if negative:
        text = text[1:]
    text = text.replace("-", "")  # tanda minus di tengah tidak bermakna

    if not text or not any(char.isdigit() for char in text):
        raise ValueError("tidak ada digit")

    last_dot = text.rfind(".")
    last_comma = text.rfind(",")

    if last_dot != -1 and last_comma != -1:
        decimal_at = max(last_dot, last_comma)
        integer_part = re.sub(r"[.,]", "", text[:decimal_at])
        decimal_part = re.sub(r"[.,]", "", text[decimal_at + 1 :])
        normalized = f"{integer_part}.{decimal_part}"
    elif last_comma != -1:
        # Hanya koma: koma adalah desimal.
        head, _, tail = text.rpartition(",")
        normalized = f"{re.sub(r'[.,]', '', head)}.{tail}"
    elif last_dot != -1:
        if _THOUSANDS_RE.match(text):
            normalized = text.replace(".", "")
        else:
            if text.count(".") > 1:
                raise ValueError("pemisah desimal ganda")
            normalized = text
    else:
        normalized = text

    return normalized, negative


def parse_id_number(
    raw: object,
    places: int = 2,
    *,
    field: str = "Nilai",
    min_value: Decimal | None = None,
    max_value: Decimal | None = None,
    allow_negative: bool = False,
) -> Decimal:
    """Parse angka id-ID menjadi Decimal ter-quantize (HALF_UP).

    Contoh: ``1.234.567,89`` → ``1234567.89``; ``12,345`` → ``12.35`` (2 desimal).
    """
    if places < 0:
        raise ValueError("places tidak boleh negatif")

    try:
        normalized, negative = _normalize(raw)
        value = Decimal(normalized)
    except (InvalidOperation, ArithmeticError, ValueError) as exc:
        raise DomainError(messages.NUMBER_INVALID.format(field=field)) from exc

    if negative:
        value = -value
    quantum = Decimal(1).scaleb(-places)
    try:
        value = value.quantize(quantum, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise DomainError(messages.NUMBER_INVALID.format(field=field)) from exc

    if not allow_negative and value < 0:
        raise DomainError(_min_message(field))
    if min_value is not None and value < min_value:
        raise DomainError(_min_message(field))
    if max_value is not None and value > max_value:
        raise DomainError(_max_message(field, max_value, places))
    return value


def parse_decimal(raw: object, places: int, **kwargs) -> Decimal:
    """Alias kompatibilitas untuk rancangan (§7.1)."""
    return parse_id_number(raw, places, **kwargs)


def _as_decimal(value: object) -> Decimal:
    if isinstance(value, float):
        raise TypeError("Uang/qty tidak boleh float; gunakan Decimal atau string.")
    if isinstance(value, Decimal):
        return value
    return Decimal(value)


def format_id_number(value: object, places: int = 2, *, trim: bool = False) -> str:
    """Format Decimal ke gaya id-ID: ``1.234.567,89``."""
    number = _as_decimal(value)
    quantum = Decimal(1).scaleb(-places)
    number = number.quantize(quantum, rounding=ROUND_HALF_UP)
    if number == 0:
        number = abs(number)
    text = f"{number:,.{places}f}"
    text = text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    if trim and "," in text:
        text = text.rstrip("0").rstrip(",")
    return text


def format_money(value: object) -> str:
    return format_id_number(value, 2)


def format_qty(value: object) -> str:
    return format_id_number(value, 3, trim=True)
