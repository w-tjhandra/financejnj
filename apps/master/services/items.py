"""Service master item transaksi (FR-05, FR-06).

Aturan penting:

- nama unik per arus;
- arah efek stok hanya ``income -> out`` dan ``expense -> in``;
- item ber-stok wajib memilih jenis stok dan satuannya mengikuti jenis stok;
- item yang sudah dipakai tidak boleh mengubah arus, jenis stok, atau frekuensi;
- item sistem tidak boleh dihapus dan tersembunyi dari pilihan normal;
- nonaktif ditolak bila item dipakai pada periode terkunci (BR-12).
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count

from audit.service import diff, log_audit, snapshot
from core import messages
from core.errors import DomainError
from core.services.locks import max_locked_period
from core.utils.dates import add_months
from master.models import (
    FLOW_CHOICES,
    FREQUENCY_CHOICES,
    PAYMENT_METHOD_CHOICES,
    Category,
    Item,
    StockItem,
)

AUDIT_FIELDS = (
    "name",
    "flow",
    "frequency",
    "default_category",
    "stock_item",
    "unit",
    "default_payment_method",
    "is_system",
    "is_active",
    "sort_order",
)
FLOW_VALUES = {value for value, _ in FLOW_CHOICES}
FREQUENCY_VALUES = {value for value, _ in FREQUENCY_CHOICES}
PAYMENT_METHOD_VALUES = {value for value, _ in PAYMENT_METHOD_CHOICES}
STOCK_DIRECTION_BY_FLOW = {"income": "out", "expense": "in"}


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


def _normalize_unit(value: object) -> str | None:
    text = _normalize_text(value)
    return text or None


def _transactions_for(item: Item):
    """Semua transaksi (termasuk soft-delete) yang memakai item."""
    model = item.transactions.model
    return model._base_manager.filter(item=item)


def _clean_instance(item: Item) -> None:
    try:
        item.full_clean(validate_unique=False, validate_constraints=False)
    except ValidationError as exc:
        message = " ".join(exc.messages)
        raise DomainError(message, fields={"name": message}) from exc


def _validate_flow(flow: str) -> str:
    if flow not in FLOW_VALUES:
        raise DomainError(messages.ITEM_FLOW_INVALID, fields={"flow": messages.ITEM_FLOW_INVALID})
    return flow


def _validate_frequency(frequency: str) -> str:
    if frequency not in FREQUENCY_VALUES:
        raise DomainError(
            messages.ITEM_FREQUENCY_INVALID, fields={"frequency": messages.ITEM_FREQUENCY_INVALID}
        )
    return frequency


def _validate_payment_method(method: str | None) -> str | None:
    if method in (None, ""):
        return None
    if method not in PAYMENT_METHOD_VALUES:
        raise DomainError(
            "Metode pembayaran tidak valid.",
            fields={"default_payment_method": "Metode tidak valid."},
        )
    return method


def _validate_name_available(name: str, *, flow: str, exclude_id: int | None = None) -> None:
    queryset = Item.objects.filter(name__iexact=name, flow=flow)
    if exclude_id is not None:
        queryset = queryset.exclude(pk=exclude_id)
    if queryset.exists():
        raise DomainError(messages.ITEM_NAME_TAKEN, fields={"name": messages.ITEM_NAME_TAKEN})


def _validate_default_category(
    category: Category | None, *, current: Category | None = None
) -> None:
    if category is None:
        return
    if not category.is_active and (current is None or current.pk != category.pk):
        raise DomainError(
            messages.ITEM_CATEGORY_INACTIVE,
            fields={"default_category": messages.ITEM_CATEGORY_INACTIVE},
        )


def stock_direction_for(flow: str) -> str:
    """Arah movement yang sah untuk arus item (AC-05.3)."""
    try:
        return STOCK_DIRECTION_BY_FLOW[flow]
    except KeyError as exc:
        raise DomainError(
            messages.ITEM_FLOW_INVALID, fields={"flow": messages.ITEM_FLOW_INVALID}
        ) from exc


def assert_stock_direction(*, flow: str, direction: str) -> str:
    """Tolak kombinasi arus/arah selain income→out dan expense→in."""
    expected = stock_direction_for(flow)
    if direction != expected:
        raise DomainError(
            messages.ITEM_STOCK_DIRECTION, fields={"flow": messages.ITEM_STOCK_DIRECTION}
        )
    return expected


def _resolve_stock(
    *, has_stock: bool, stock_item: StockItem | None, unit: str | None
) -> tuple[StockItem | None, str | None]:
    if stock_item is not None:
        has_stock = True
    if has_stock:
        if stock_item is None:
            raise DomainError(
                messages.ITEM_STOCK_UNIT, fields={"stock_item": messages.ITEM_STOCK_UNIT}
            )
        # Satuan item ber-stok selalu mengikuti satuan jenis stok.
        return stock_item, stock_item.unit
    return None, _normalize_unit(unit)


def _assert_not_used_in_locked_period(item: Item) -> None:
    max_locked = max_locked_period()
    if max_locked is None:
        return
    cutoff = add_months(max_locked, 1)
    if _transactions_for(item).filter(date__lt=cutoff).exists():
        raise DomainError(
            messages.item_used_locked(max_locked),
            code="period_locked",
            http_status=403,
            fields={"is_active": messages.item_used_locked(max_locked)},
        )


@transaction.atomic
def create_item(
    *,
    name: object,
    flow: str,
    frequency: str = "daily",
    default_category: Category | None = None,
    has_stock: bool = False,
    stock_item: StockItem | None = None,
    unit: object = None,
    default_payment_method: str | None = None,
    sort_order: int = 0,
    actor=None,
    meta=None,
) -> Item:
    name = _normalize_text(name)
    if not name:
        raise DomainError("Nama item wajib diisi.", fields={"name": "Nama item wajib diisi."})
    flow = _validate_flow(flow)
    frequency = _validate_frequency(frequency)
    _validate_name_available(name, flow=flow)
    _validate_default_category(default_category)
    stock_item, unit = _resolve_stock(has_stock=has_stock, stock_item=stock_item, unit=unit)

    item = Item(
        name=name,
        flow=flow,
        frequency=frequency,
        default_category=default_category,
        stock_item=stock_item,
        unit=unit,
        default_payment_method=_validate_payment_method(default_payment_method),
        sort_order=sort_order or 0,
    )
    _clean_instance(item)
    try:
        item.save()
    except IntegrityError as exc:
        raise DomainError(
            messages.ITEM_NAME_TAKEN, fields={"name": messages.ITEM_NAME_TAKEN}
        ) from exc

    log_audit(
        entity="item",
        entity_id=item.pk,
        action="create",
        actor=actor,
        after=snapshot(item, AUDIT_FIELDS),
        meta=meta,
    )
    return item


@transaction.atomic
def update_item(
    *,
    item_id: int,
    name: object,
    flow: str,
    frequency: str,
    default_category: Category | None = None,
    has_stock: bool = False,
    stock_item: StockItem | None = None,
    unit: object = None,
    default_payment_method: str | None = None,
    sort_order: int = 0,
    actor=None,
    meta=None,
) -> Item:
    item = Item.objects.select_for_update().get(pk=item_id)
    name = _normalize_text(name)
    if not name:
        raise DomainError("Nama item wajib diisi.", fields={"name": "Nama item wajib diisi."})
    flow = _validate_flow(flow)
    frequency = _validate_frequency(frequency)
    _validate_name_available(name, flow=flow, exclude_id=item.pk)
    _validate_default_category(default_category, current=item.default_category)
    stock_item, unit = _resolve_stock(has_stock=has_stock, stock_item=stock_item, unit=unit)

    used = _transactions_for(item).count()
    if used:
        locked_fields = (
            ("flow", "Arus", flow, item.flow),
            ("frequency", "Frekuensi", frequency, item.frequency),
            (
                "stock_item",
                "Jenis stok",
                stock_item.pk if stock_item else None,
                item.stock_item_id,
            ),
        )
        for field, label, new_value, old_value in locked_fields:
            if new_value != old_value:
                message = messages.ITEM_USED_FIELD_LOCKED.format(count=used, field=label)
                raise DomainError(message, fields={field: message})
        if item.stock_item_id is not None:
            unit = item.unit

    before = snapshot(item, AUDIT_FIELDS)
    item.name = name
    item.flow = flow
    item.frequency = frequency
    item.default_category = default_category
    item.stock_item = stock_item
    item.unit = unit
    item.default_payment_method = _validate_payment_method(default_payment_method)
    item.sort_order = sort_order or 0
    _clean_instance(item)
    try:
        item.save()
    except IntegrityError as exc:
        raise DomainError(
            messages.ITEM_NAME_TAKEN, fields={"name": messages.ITEM_NAME_TAKEN}
        ) from exc

    changed_before, changed_after = diff(before, snapshot(item, AUDIT_FIELDS))
    if changed_before:
        log_audit(
            entity="item",
            entity_id=item.pk,
            action="update",
            actor=actor,
            before=changed_before,
            after=changed_after,
            meta=meta,
        )
    return item


@transaction.atomic
def deactivate_item(*, item_id: int, actor=None, meta=None) -> Item:
    item = Item.objects.select_for_update().get(pk=item_id)
    if not item.is_active:
        return item
    _assert_not_used_in_locked_period(item)

    before = snapshot(item, AUDIT_FIELDS)
    item.is_active = False
    item.save(update_fields=["is_active", "updated_at"])
    log_audit(
        entity="item",
        entity_id=item.pk,
        action="update",
        actor=actor,
        before=before,
        after=snapshot(item, AUDIT_FIELDS),
        meta=meta,
    )
    return item


@transaction.atomic
def activate_item(*, item_id: int, actor=None, meta=None) -> Item:
    item = Item.objects.select_for_update().get(pk=item_id)
    if item.is_active:
        return item

    before = snapshot(item, AUDIT_FIELDS)
    item.is_active = True
    item.save(update_fields=["is_active", "updated_at"])
    log_audit(
        entity="item",
        entity_id=item.pk,
        action="update",
        actor=actor,
        before=before,
        after=snapshot(item, AUDIT_FIELDS),
        meta=meta,
    )
    return item


@transaction.atomic
def delete_item(*, item_id: int, actor=None, meta=None) -> None:
    item = Item.objects.select_for_update().get(pk=item_id)
    if item.is_system:
        raise DomainError(messages.ITEM_SYSTEM)
    used = _transactions_for(item).count()
    if used:
        raise DomainError(messages.ITEM_IN_USE.format(count=used))

    before = snapshot(item, AUDIT_FIELDS)
    item_id = item.pk
    item.delete()
    log_audit(
        entity="item",
        entity_id=item_id,
        action="delete",
        actor=actor,
        before=before,
        meta=meta,
    )


def item_usage_count(item: Item) -> int:
    return _transactions_for(item).count()


def items_with_usage():
    return (
        Item.objects.select_related("default_category", "stock_item")
        .annotate(transaction_count=Count("transactions"))
        .order_by("flow", "sort_order", "id")
    )


def active_items(*, flow: str | None = None):
    """Item yang boleh muncul di form transaksi normal (AC-05.1/05.5)."""
    queryset = Item.objects.filter(is_active=True, is_system=False).select_related(
        "default_category", "stock_item"
    )
    if flow is not None:
        queryset = queryset.filter(flow=_validate_flow(flow))
    return queryset.order_by("sort_order", "id")
