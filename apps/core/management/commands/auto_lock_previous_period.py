from __future__ import annotations

import time

from django.core.management.base import BaseCommand

from core.errors import DomainError
from core.services.period_auto_lock import maybe_auto_lock_previous_period


class Command(BaseCommand):
    help = "Check monthly auto-lock schedule and close the previous period when due."

    def handle(self, *args, **options):
        while True:
            try:
                period_lock = maybe_auto_lock_previous_period()
            except DomainError as exc:
                self.stderr.write(self.style.ERROR(f"Penguncian otomatis gagal: {exc.message}"))
                time.sleep(3600)
            else:
                if period_lock is not None:
                    self.stdout.write(
                        self.style.SUCCESS(f"Periode {period_lock.period:%Y-%m} dikunci otomatis.")
                    )
                time.sleep(60)
