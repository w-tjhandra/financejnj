"""Service master kategori (FR-04).

Semua penulisan kategori lewat modul ini. Aturan yang dijaga:

- kode unik tanpa membedakan huruf besar/kecil;
- kedalaman maksimal satu tingkat (induk wajib kategori tanpa induk);
- kategori sistem tidak boleh dihapus, dinonaktifkan, atau diubah kodenya;
- kategori yang sudah dipakai tidak boleh dihapus;
- nonaktif ditolak bila kategori dipakai pada periode terkunci (BR-12).
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
from master.models import Category

AUDIT_FIELDS = ("code", "name", "parent", "sort_order", "is_system", "is_active")


def _normalize_code(code: object) -> str:
    return str(code or "").strip().upper()


def _normalize_name(name: object) -> str:
    return str(name or "").strip()


def _transactions_for(category: Category):
    """Semua transaksi (termasuk soft-delete) milik kategori.

    Reverse manager memakai default manager yang menyembunyikan baris
    soft-delete. Guard hapus butuh semua baris agar FK PROTECT tidak meledak
    setelah guard lolos.
    """
    model = category.transactions.model
    return model._base_manager.filter(category=category)


def _clean_instance(category: Category) -> None:
    try:
        category.full_clean(validate_unique=False, validate_constraints=False)
    except ValidationError as exc:
        message = " ".join(exc.messages)
        raise DomainError(message, fields={"code": message}) from exc


def _assert_code_available(code: str, *, exclude_id: int | None = None) -> None:
    queryset = Category.objects.filter(code__iexact=code)
    if exclude_id is not None:
        queryset = queryset.exclude(pk=exclude_id)
    if queryset.exists():
        raise DomainError(
            messages.CATEGORY_CODE_TAKEN, fields={"code": messages.CATEGORY_CODE_TAKEN}
        )


def _validate_parent(parent: Category | None, *, category: Category | None = None) -> None:
    if parent is None:
        return
    if category is not None and category.pk is not None:
        if parent.pk == category.pk:
            raise DomainError(messages.CATEGORY_DEPTH, fields={"parent": messages.CATEGORY_DEPTH})
        if Category.objects.filter(parent=category).exists():
            # Menjadikan kategori ber-anak sebagai anak akan membuat dua tingkat.
            raise DomainError(messages.CATEGORY_DEPTH, fields={"parent": messages.CATEGORY_DEPTH})
    if parent.parent_id is not None:
        raise DomainError(messages.CATEGORY_DEPTH, fields={"parent": messages.CATEGORY_DEPTH})
    if not parent.is_active:
        raise DomainError(
            messages.CATEGORY_PARENT_INACTIVE, fields={"parent": messages.CATEGORY_PARENT_INACTIVE}
        )


def _assert_not_used_in_locked_period(category: Category) -> None:
    max_locked = max_locked_period()
    if max_locked is None:
        return
    cutoff = add_months(max_locked, 1)
    if _transactions_for(category).filter(date__lt=cutoff).exists():
        raise DomainError(
            messages.category_used_locked(max_locked),
            code="period_locked",
            http_status=403,
            fields={"is_active": messages.category_used_locked(max_locked)},
        )


@transaction.atomic
def create_category(
    *,
    code: object,
    name: object,
    parent: Category | None = None,
    sort_order: int = 0,
    actor=None,
    meta=None,
) -> Category:
    code = _normalize_code(code)
    name = _normalize_name(name)
    if not code or not name:
        raise DomainError(messages.CATEGORY_REQUIRED, fields={"code": messages.CATEGORY_REQUIRED})
    _assert_code_available(code)
    _validate_parent(parent)

    category = Category(code=code, name=name, parent=parent, sort_order=sort_order or 0)
    _clean_instance(category)
    try:
        category.save()
    except IntegrityError as exc:
        raise DomainError(
            messages.CATEGORY_CODE_TAKEN, fields={"code": messages.CATEGORY_CODE_TAKEN}
        ) from exc

    log_audit(
        entity="category",
        entity_id=category.pk,
        action="create",
        actor=actor,
        after=snapshot(category, AUDIT_FIELDS),
        meta=meta,
    )
    return category


@transaction.atomic
def update_category(
    *,
    category_id: int,
    code: object,
    name: object,
    parent: Category | None = None,
    sort_order: int = 0,
    actor=None,
    meta=None,
) -> Category:
    category = Category.objects.select_for_update().get(pk=category_id)
    code = _normalize_code(code)
    name = _normalize_name(name)
    if not code or not name:
        raise DomainError(messages.CATEGORY_REQUIRED, fields={"name": messages.CATEGORY_REQUIRED})

    if category.is_system and code != category.code:
        raise DomainError(messages.CATEGORY_SYSTEM, fields={"code": messages.CATEGORY_SYSTEM})
    _assert_code_available(code, exclude_id=category.pk)
    _validate_parent(parent, category=category)

    before = snapshot(category, AUDIT_FIELDS)
    category.code = code
    category.name = name
    category.parent = parent
    category.sort_order = sort_order or 0
    _clean_instance(category)
    try:
        category.save()
    except IntegrityError as exc:
        raise DomainError(
            messages.CATEGORY_CODE_TAKEN, fields={"code": messages.CATEGORY_CODE_TAKEN}
        ) from exc

    changed_before, changed_after = diff(before, snapshot(category, AUDIT_FIELDS))
    if changed_before:
        log_audit(
            entity="category",
            entity_id=category.pk,
            action="update",
            actor=actor,
            before=changed_before,
            after=changed_after,
            meta=meta,
        )
    return category


@transaction.atomic
def deactivate_category(*, category_id: int, actor=None, meta=None) -> Category:
    category = Category.objects.select_for_update().get(pk=category_id)
    if category.is_system:
        raise DomainError(messages.CATEGORY_SYSTEM)
    if not category.is_active:
        return category
    _assert_not_used_in_locked_period(category)

    before = snapshot(category, AUDIT_FIELDS)
    category.is_active = False
    category.save(update_fields=["is_active", "updated_at"])
    log_audit(
        entity="category",
        entity_id=category.pk,
        action="update",
        actor=actor,
        before=before,
        after=snapshot(category, AUDIT_FIELDS),
        meta=meta,
    )
    return category


@transaction.atomic
def activate_category(*, category_id: int, actor=None, meta=None) -> Category:
    category = Category.objects.select_for_update().get(pk=category_id)
    if category.is_active:
        return category

    before = snapshot(category, AUDIT_FIELDS)
    category.is_active = True
    category.save(update_fields=["is_active", "updated_at"])
    log_audit(
        entity="category",
        entity_id=category.pk,
        action="update",
        actor=actor,
        before=before,
        after=snapshot(category, AUDIT_FIELDS),
        meta=meta,
    )
    return category


@transaction.atomic
def delete_category(*, category_id: int, actor=None, meta=None) -> None:
    category = Category.objects.select_for_update().get(pk=category_id)
    if category.is_system:
        raise DomainError(messages.CATEGORY_SYSTEM)
    if Category.objects.filter(parent=category).exists():
        raise DomainError(messages.CATEGORY_HAS_CHILDREN)

    used = _transactions_for(category).count()
    if used:
        raise DomainError(messages.CATEGORY_IN_USE.format(count=used))

    before = snapshot(category, AUDIT_FIELDS)
    category.delete()
    log_audit(
        entity="category",
        entity_id=category_id,
        action="delete",
        actor=actor,
        before=before,
        meta=meta,
    )


def category_usage_count(category: Category) -> int:
    return _transactions_for(category).count()


def categories_with_usage():
    return (
        Category.objects.select_related("parent")
        .annotate(transaction_count=Count("transactions"))
        .order_by("sort_order", "id")
    )


def active_categories():
    return Category.objects.filter(is_active=True).order_by("sort_order", "id")


def parent_options(*, exclude_id: int | None = None):
    queryset = Category.objects.filter(parent__isnull=True, is_active=True).order_by(
        "sort_order", "id"
    )
    if exclude_id is not None:
        queryset = queryset.exclude(pk=exclude_id)
    return queryset


def category_choices(*, include_inactive: bool = False) -> list[tuple[int, str]]:
    """Pilihan kategori dari master data, bukan daftar hard-coded (AC-04.6)."""
    queryset = Category.objects.order_by("sort_order", "id")
    if not include_inactive:
        queryset = queryset.filter(is_active=True)
    choices: list[tuple[int, str]] = []
    for category in queryset:
        label = category.name
        if not category.is_active:
            label = f"{label} (nonaktif)"
        choices.append((category.pk, label))
    return choices
