"""Formatter log JSON tanpa dependensi eksternal (NFR-15).

Tidak pernah mencatat password, token, atau isi lampiran: formatter hanya
mengeluarkan field standar ditambah field konteks yang dipasang pemanggil.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

CONTEXT_FIELDS = ("request_id", "user_id", "path", "status", "duration_ms")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for field in CONTEXT_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)
