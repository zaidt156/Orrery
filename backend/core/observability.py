"""Request IDs + structured logging (architecture plan #14, #15).

Every API request gets a short id stored in a contextvar so all log lines emitted while handling
it (including inside the streaming generators) carry the same `[id]`, making a single chat request
easy to trace. `log_event` emits consistent `event key=value` lines for the points that matter.
"""

from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar

from backend.security import secrets

_request_id: ContextVar[str] = ContextVar("request_id", default="-")


def new_request_id() -> str:
    rid = uuid.uuid4().hex[:12]
    _request_id.set(rid)
    return rid


def get_request_id() -> str:
    return _request_id.get()


class RequestIdFilter(logging.Filter):
    """Inject the current request id into every record so the formatter can show it."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        return True


def install(level: int = logging.INFO) -> None:
    """Configure root logging with the request-id field. Call once at startup."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(name)-18s %(levelname)-7s [%(request_id)s] %(message)s",
    )
    f = RequestIdFilter()
    for handler in logging.getLogger().handlers:
        handler.addFilter(f)


def log_event(log: logging.Logger, event: str, **fields) -> None:
    """Structured one-liner: `event key=value ...`, with secret-shaped values scrubbed."""
    parts = [event]
    for key, value in fields.items():
        parts.append(f"{key}={secrets.redact_secrets(str(value))}")
    log.info(" ".join(parts))
