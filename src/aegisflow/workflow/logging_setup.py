"""Run-scoped JSON logs for workflow nodes."""

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

from aegisflow.security_tools import redact_sensitive

RUN_ID: ContextVar[str] = ContextVar("aegisflow_run_id", default="-")
LOGGER_NAME = "aegisflow.workflow"


class JsonRunFormatter(logging.Formatter):
    """Serialize records without logging question or evidence contents."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "run_id": getattr(record, "run_id", RUN_ID.get()),
            "message": redact_sensitive(record.getMessage()),
        }
        for key in (
            "node",
            "duration_ms",
            "prompt_tokens",
            "completion_tokens",
            "cache_hit",
            "status",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def configure_json_logging() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if not any(
        isinstance(handler.formatter, JsonRunFormatter) for handler in logger.handlers
    ):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonRunFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


@contextmanager
def bind_run_id(run_id: str) -> Iterator[None]:
    token = RUN_ID.set(run_id)
    try:
        yield
    finally:
        RUN_ID.reset(token)
