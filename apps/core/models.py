"""Model dasar dan model milik app core.

Semua model bisnis memakai `TimeStampedModel`; model transaksional memakai
`SoftDeleteModel` sehingga baris terhapus tetap bisa dirujuk relasi lama.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SoftDeleteQuerySet(models.QuerySet):
    def alive(self):
        return self.filter(deleted_at__isnull=True)

    def dead(self):
        return self.filter(deleted_at__isnull=False)


class SoftDeleteManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    """Manager default: hanya baris aktif."""

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class AllObjectsManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    """Semua baris, termasuk yang sudah di-soft-delete."""


class SoftDeleteModel(TimeStampedModel):
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    objects = SoftDeleteManager()
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True
        base_manager_name = "all_objects"  # relasi ke baris terhapus tetap resolve
        default_manager_name = "objects"

    def soft_delete(self, *, actor=None):
        """Tandai terhapus tanpa menghapus baris fisik."""
        self.deleted_at = timezone.now()
        self.deleted_by = actor
        self.save(update_fields=["deleted_at", "deleted_by", "updated_at"])

    def restore(self):
        self.deleted_at = None
        self.deleted_by = None
        self.save(update_fields=["deleted_at", "deleted_by", "updated_at"])


class CompanyProfile(TimeStampedModel):
    """Profil usaha; invarian "maksimal satu baris" dijaga aplikasi."""

    name = models.CharField(max_length=100)
    address = models.CharField(max_length=300, blank=True, default="")
    phone = models.CharField(max_length=30, blank=True, default="")
    email = models.EmailField(max_length=254, blank=True, default="")
    logo = models.CharField(max_length=255, null=True, blank=True)
    business_start_date = models.DateField(null=True, blank=True)
    application_start_date = models.DateField(default=timezone.localdate)
    setup_completed = models.BooleanField(default=False)

    class Meta:
        verbose_name = "profil usaha"
        verbose_name_plural = "profil usaha"

    def __str__(self):
        return self.name

    @classmethod
    def get_solo(cls, *, for_update: bool = False):
        qs = cls.objects.order_by("pk")
        if for_update:
            qs = qs.select_for_update()
        return qs.first()


class PeriodLock(TimeStampedModel):
    """Status kunci satu bulan; riwayat lengkap ada di audit log."""

    period = models.DateField(help_text="Selalu hari pertama bulan.")
    is_locked = models.BooleanField(default=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    unlocked_at = models.DateTimeField(null=True, blank=True)
    unlocked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    unlock_reason = models.CharField(max_length=300, null=True, blank=True)
    unlock_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["-period"]
        constraints = [
            models.UniqueConstraint(fields=["period"], name="uniq_period_lock_period"),
            models.CheckConstraint(condition=Q(period__day=1), name="period_lock_first_of_month"),
            models.CheckConstraint(
                condition=Q(unlock_count__gte=0), name="period_lock_unlock_count_gte0"
            ),
        ]
        indexes = [models.Index(fields=["is_locked"], name="period_lock_is_locked_idx")]

    def __str__(self):
        return f"{self.period:%Y-%m} ({'terkunci' if self.is_locked else 'terbuka'})"
