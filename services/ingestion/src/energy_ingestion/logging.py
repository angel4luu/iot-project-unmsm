"""Structured UTC JSON logging (T023).

Each line is one JSON object with `ts` (UTC, ms, `Z`), `level`, `component`,
`event`, and optional `node_id`, `message_id`, `result`, `reason`, `latency_ms`.
Values whose key looks secret-bearing are replaced by `[redacted]`, and raw
payloads are never logged (log hashes instead).
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any, Final

STANDARD_FIELDS: Final = ("node_id", "message_id", "result", "reason", "latency_ms")
_SECRET_KEY = re.compile(r"(secret|token|password|passwd|key|credential|auth|payload)", re.I)
_RESERVED = frozenset(vars(logging.makeLogRecord({})))
REDACTED: Final = "[redacted]"


def _redact(key: str, value: Any) -> Any:
    if _SECRET_KEY.search(key) and key not in ("payload_sha256",):
        return REDACTED
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, UTC)
        doc: dict[str, Any] = {
            "ts": ts.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "component": record.name.removeprefix("energy."),
            "event": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _RESERVED and not key.startswith("_"):
                doc[key] = _redact(key, value)
        if record.exc_info:
            doc["error_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        return json.dumps(doc, separators=(",", ":"), default=str, ensure_ascii=False)


def configure(level: int = logging.INFO, stream: Any = None) -> None:
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("energy")
    root.handlers[:] = [handler]
    root.setLevel(level)
    root.propagate = False


def get_logger(component: str) -> logging.Logger:
    return logging.getLogger(f"energy.{component}")


def log_event(logger: logging.Logger, event: str, level: int = logging.INFO, **fields: Any) -> None:
    """Log one event; `fields` become top-level JSON members (secrets redacted)."""
    logger.log(level, event, extra=fields)
