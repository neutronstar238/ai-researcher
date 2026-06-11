"""Structured logging helpers for local AutoResearch runs."""

from __future__ import annotations

import logging
from collections.abc import MutableMapping
from typing import Any

LOG_FORMAT = (
    "%(asctime)s %(levelname)s %(name)s "
    "run_id=%(run_id)s component=%(component)s "
    "project_id=%(project_id)s task_id=%(task_id)s %(message)s"
)


class ContextLoggerAdapter(logging.LoggerAdapter[logging.Logger]):
    """Logger adapter that keeps AutoResearch context on every record."""

    def process(
        self,
        msg: Any,
        kwargs: MutableMapping[str, Any],
    ) -> tuple[Any, MutableMapping[str, Any]]:
        extra = dict(kwargs.get("extra", {}))
        adapter_extra = self.extra or {}
        for key, value in adapter_extra.items():
            extra.setdefault(key, value)
        kwargs = dict(kwargs)
        kwargs["extra"] = extra
        return msg, kwargs


def configure_logging(level: str | int = logging.INFO) -> None:
    """Configure a human-readable formatter that still carries structured fields."""

    logging.basicConfig(level=level, format=LOG_FORMAT)


def get_logger(
    component: str,
    *,
    run_id: str | None = None,
    project_id: str | None = None,
    task_id: str | None = None,
) -> ContextLoggerAdapter:
    """Return a logger adapter with AutoResearch run context."""

    logger = logging.getLogger(f"autoresearch.{component}")
    return ContextLoggerAdapter(
        logger,
        {
            "run_id": run_id or "-",
            "component": component,
            "project_id": project_id or "-",
            "task_id": task_id or "-",
        },
    )
