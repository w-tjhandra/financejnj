"""Parser & format angka id-ID sesuai BR-11 / AC-24.3…24.8."""

from decimal import Decimal

import pytest

from core import messages
from core.errors import DomainError
from core.utils.numbers import (
    format_id_number,
    format_money,
    format_qty,
    parse_decimal,
    parse_id_number,
)


@pytest.mark.parametrize(
    ("raw", "places", "expected"),
    [
        ("1.234.567,89", 2, "1234567.89"),
        ("1234567.89", 2, "1234567.89"),
        ("1.500", 2, "1500.00"),
        ("1.500,25", 2, "1500.25"),
        ("1,5", 2, "1.50"),
        ("12,345", 2, "12.35"),
        ("0,005", 2, "0.01"),
        ("0,004", 2, "0.00"),
        ("1.000,1255", 3, "1000.126"),
        ("1,234,567.89", 2, "1234567.89"),
        ("  1.234,50  ", 2, "1234.50"),
        ("Rp 1.500,50", 2, "1500.50"),
        ("1234.567", 3, "1234.567"),
        ("1000000", 2, "1000000.00"),
    ],
)
def test_parse_contoh_br11(raw, places, expected):
    assert parse_id_number(raw, places) == Decimal(expected)


@pytest.mark.parametrize("raw", ["", "   ", "-", "abc", "1.2.3"])
def test_parse_menolak_input_bukan_angka(raw):
    with pytest.raises(DomainError) as exc:
        parse_id_number(raw, 2, field="Nominal")

    assert str(exc.value) == messages.NUMBER_INVALID.format(field="Nominal")


@pytest.mark.parametrize("raw", ["-1.500", "-5.000", "-0,005"])
def test_parse_menolak_negatif_untuk_nominal(raw):
    with pytest.raises(DomainError) as exc:
        parse_id_number(raw, 2, field="Nominal")

    assert str(exc.value) == messages.AMOUNT_MIN


def test_parse_allow_negative_untuk_penyesuaian():
    assert parse_id_number("-5.000", 2, allow_negative=True) == Decimal("-5000.00")


@pytest.mark.parametrize(("raw", "expected"), [("2,675", "2.68"), ("2,665", "2.67")])
def test_parse_memakai_half_up(raw, expected):
    assert parse_id_number(raw, 2) == Decimal(expected)


def test_parse_menolak_nominal_nol_dan_di_atas_maksimum():
    with pytest.raises(DomainError) as zero:
        parse_id_number("0", 2, field="Nominal", min_value=Decimal("0.01"))
    assert str(zero.value) == messages.AMOUNT_MIN

    with pytest.raises(DomainError) as maks:
        parse_id_number("100000000001", 2, field="Nominal", max_value=Decimal("100000000000"))
    assert str(maks.value) == messages.AMOUNT_MAX


def test_parse_menolak_qty_nol_dan_di_atas_maksimum():
    with pytest.raises(DomainError) as zero:
        parse_id_number("0", 3, field="Qty", min_value=Decimal("0.001"))
    assert str(zero.value) == messages.QTY_MIN

    with pytest.raises(DomainError) as maks:
        parse_id_number("1000000,001", 3, field="Qty", max_value=Decimal("1000000"))
    assert str(maks.value) == messages.QTY_MAX


def test_parse_decimal_alias_kompatibel():
    assert parse_decimal("1.500", 2) == Decimal("1500.00")


def test_format_money_dan_qty_id_id():
    assert format_money(Decimal("1234567.5")) == "1.234.567,50"
    assert format_money(Decimal("-1234")) == "-1.234,00"
    assert format_qty(Decimal("1250.5")) == "1.250,5"
    assert format_qty(Decimal("1000.000")) == "1.000"


def test_format_round_trip_parse():
    for raw in ("1.234.567,89", "12.345", "0,01"):
        value = parse_id_number(raw, 2)
        assert parse_id_number(format_money(value), 2) == value


def test_format_menolak_float():
    with pytest.raises(TypeError):
        format_id_number(1234.5)


def test_format_nol_tidak_menghasilkan_minus_nol():
    assert format_money(Decimal("-0.00")) == "0,00"
