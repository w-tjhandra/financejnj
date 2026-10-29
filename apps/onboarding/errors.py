"""Error khusus wizard setup."""

from __future__ import annotations

from core.errors import DomainError


class SetupIncomplete(DomainError):
    """Langkah sebelumnya belum lengkap; arahkan kembali ke langkah itu."""

    code = "setup_incomplete"
    http_status = 409

    def __init__(self, message: str, *, step) -> None:
        super().__init__(message)
        self.step = step
