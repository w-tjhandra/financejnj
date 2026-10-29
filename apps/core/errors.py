"""Error domain yang dipetakan view ke status HTTP dan pesan pengguna."""

from __future__ import annotations


class DomainError(Exception):
    """Kesalahan aturan bisnis yang aman ditampilkan ke pengguna."""

    code = "domain_error"
    http_status = 400

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        http_status: int | None = None,
        fields: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if http_status is not None:
            self.http_status = http_status
        self.fields = fields or {}

    def __str__(self) -> str:
        return self.message


class PeriodLocked(DomainError):
    code = "period_locked"
    http_status = 403

    def __init__(self, message: str, *, period=None) -> None:
        super().__init__(message)
        self.period = period


class StockInsufficient(DomainError):
    code = "stock_insufficient"
    http_status = 409


class StockConflict(DomainError):
    code = "stock_conflict"
    http_status = 409


class DuplicateSalary(DomainError):
    code = "salary_exists"
    http_status = 302

    def __init__(self, message: str, *, existing_id=None) -> None:
        super().__init__(message)
        self.existing_id = existing_id


class NotFound(DomainError):
    code = "not_found"
    http_status = 404


class Gone(DomainError):
    code = "not_found"
    http_status = 404


class AlreadyLocked(DomainError):
    code = "lock_state"
    http_status = 409


class AlreadyUnlocked(DomainError):
    code = "lock_state"
    http_status = 409
