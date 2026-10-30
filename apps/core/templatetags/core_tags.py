"""Template tags kustom untuk core."""

from django import template

from core.utils.numbers import format_money, format_qty

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Ambil nilai dari dict dengan key dinamis."""
    if isinstance(dictionary, dict):
        return dictionary.get(key)
    return None


@register.filter
def get_range(value, arg):
    """Generate range dari value sampai arg (inclusive). Digunakan untuk pagination."""
    try:
        start = int(value)
        end = int(arg)
    except (ValueError, TypeError):
        return []
    if start > end:
        return []
    return range(start, end + 1)


@register.filter
def money_id(value):
    return format_money(value)


@register.filter
def qty_id(value):
    return format_qty(value)
