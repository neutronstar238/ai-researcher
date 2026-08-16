"""Structured logging and request context (spec §21.1).

Log records must never carry full paper text, prompts, tokens, cookies, secrets
or signed URLs. The ``SanitizingFilter`` strips obvious secret keys defensively.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

_SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "api_key",
    "token",
    "password",
    "secret",
    "presigned_url",
    "signature",
    "refresh_token",
    "access_token",
}

_SENSITIVE_FIELDS = {
    "user_prompt",
    "prompt",
    "paper_full_text",
    "full_text",
    "content",
}


class SanitizingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, dict):
            record.args = {k: _redact(k, v) for k, v in record.args.items()}
        return True


def _redact(key: Any, value: Any) -> Any:
    if isinstance(key, str) and key.casefold() in _SENSITIVE_KEYS:
        return "[REDACTED]"
    if isinstance(key, str) and key.casefold() in _SENSITIVE_FIELDS:
        return "[REDACTED]"
    return value


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(SanitizingFilter())
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [handler]
