"""Template tags kustom untuk core."""

from django import template

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
