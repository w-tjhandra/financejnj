"""Audit log append-only (BR-14, AC-32.x)."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q

from audit.constants import ACTION_VALUES, ENTITY_VALUES


class AppendOnlyError(RuntimeError):
    """Dilempar bila ada upaya mengubah/menghapus audit log lewat ORM."""


class AuditLogQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise AppendOnlyError("Audit log append-only: update tidak diizinkan.")

    def delete(self):
        raise AppendOnlyError("Audit log append-only: delete tidak diizinkan.")


class AuditLogManager(models.Manager.from_queryset(AuditLogQuerySet)):
    pass


class AuditLog(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    entity = models.CharField(max_length=40)
    entity_id = models.BigIntegerField(null=True, blank=True)
    action = models.CharField(max_length=20)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    extra = models.JSONField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=200, null=True, blank=True)

    objects = AuditLogManager()

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(entity__in=ENTITY_VALUES), name="audit_entity_allowed"
            ),
            models.CheckConstraint(
                condition=Q(action__in=ACTION_VALUES), name="audit_action_allowed"
            ),
        ]
        indexes = [
            models.Index(
                fields=["entity", "entity_id", "-created_at"],
                name="audit_entity_created_idx",
            ),
            models.Index(fields=["-created_at"], name="audit_created_idx"),
            models.Index(fields=["action", "-created_at"], name="audit_action_created_idx"),
            models.Index(
                fields=["-created_at"],
                condition=Q(entity_id__isnull=True),
                name="audit_null_entity_idx",
            ),
        ]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.entity}:{self.action}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AppendOnlyError("Audit log append-only: baris tidak boleh diubah.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("Audit log append-only: baris tidak boleh dihapus.")
