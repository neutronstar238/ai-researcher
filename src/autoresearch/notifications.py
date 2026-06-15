"""Operator notification helpers for AI-Researcher."""

from __future__ import annotations

import json
import os
import ssl
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import certifi


class InspirationReportLike(Protocol):
    """Minimal shape needed to render an inspiration digest."""

    @property
    def queries(self) -> tuple[str, ...]:
        """Queries used for the refresh."""
        ...

    @property
    def items(self) -> tuple[Any, ...]:
        """Returned inspiration items."""
        ...

    @property
    def summary_path(self) -> Any:
        """Optional vault summary path."""
        ...


WebhookSender = Callable[[str, Mapping[str, object], float], int]


@dataclass(frozen=True)
class NotificationSendRecord:
    """Result of one outbound notification attempt."""

    channel: str
    status: str
    detail: str
    status_code: int | None = None

    def to_json_dict(self) -> dict[str, object]:
        """Return a stable JSON-serialisable representation."""

        return {
            "channel": self.channel,
            "status": self.status,
            "detail": self.detail,
            "status_code": self.status_code,
        }


def send_inspiration_digest(
    report: InspirationReportLike,
    *,
    channels: tuple[str, ...] = ("wechat", "feishu"),
    env: Mapping[str, str] | None = None,
    sender: WebhookSender | None = None,
    timeout_seconds: float = 10.0,
) -> tuple[NotificationSendRecord, ...]:
    """Send a compact inspiration digest to configured operator webhooks."""

    environment = env or os.environ
    post_json = sender or _post_json
    digest = render_inspiration_digest(report)
    records: list[NotificationSendRecord] = []
    for channel in channels:
        normalized = channel.casefold().strip()
        url_env = _webhook_env_name(normalized)
        if url_env is None:
            records.append(
                NotificationSendRecord(
                    channel=channel,
                    status="skipped",
                    detail="unsupported channel",
                )
            )
            continue
        webhook_url = str(environment.get(url_env, "")).strip()
        if not webhook_url:
            records.append(
                NotificationSendRecord(
                    channel=normalized,
                    status="skipped",
                    detail=f"missing {url_env}",
                )
            )
            continue
        try:
            status_code = post_json(
                webhook_url,
                _webhook_payload(normalized, digest),
                timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001 - outbound notification must not hide failures.
            records.append(
                NotificationSendRecord(
                    channel=normalized,
                    status="failed",
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )
            continue
        status = "sent" if 200 <= status_code < 300 else "failed"
        records.append(
            NotificationSendRecord(
                channel=normalized,
                status=status,
                detail="webhook accepted" if status == "sent" else "webhook returned non-2xx",
                status_code=status_code,
            )
        )
    return tuple(records)


def render_inspiration_digest(report: InspirationReportLike, *, max_items: int = 5) -> str:
    """Render a short human-readable inspiration digest."""

    lines = [
        "AI-Researcher inspiration digest",
        "",
        "Queries:",
        *[f"- {query}" for query in report.queries],
        "",
        "Top signals:",
    ]
    items = sorted(
        report.items,
        key=lambda item: (
            -float(getattr(item, "score", 0.0)),
            str(getattr(item, "source", "")),
            str(getattr(item, "title", "")).casefold(),
        ),
    )
    if not items:
        lines.append("- No source-backed inspiration items were found.")
    for index, item in enumerate(items[:max_items], start=1):
        title = str(getattr(item, "title", "untitled"))
        source = str(getattr(item, "source", "unknown"))
        source_type = str(getattr(item, "source_type", "unknown"))
        score = float(getattr(item, "score", 0.0))
        url = str(getattr(item, "url", ""))
        lines.append(f"{index}. {title} ({source}/{source_type}, score={score:.1f})")
        if url:
            lines.append(f"   {url}")
    summary_path = getattr(report, "summary_path", None)
    if summary_path is not None:
        lines.extend(["", f"Vault note: {_path_text(summary_path)}"])
    lines.extend(
        [
            "",
            "Policy: these are dataset/community/news signals only; validate before citing.",
        ]
    )
    return _truncate("\n".join(lines), limit=3500)


def _webhook_env_name(channel: str) -> str | None:
    if channel in {"wechat", "weixin", "wecom"}:
        return "AUTORESEARCH_WECHAT_WEBHOOK_URL"
    if channel in {"feishu", "lark"}:
        return "AUTORESEARCH_FEISHU_WEBHOOK_URL"
    return None


def _path_text(path: Any) -> str:
    as_posix = getattr(path, "as_posix", None)
    if callable(as_posix):
        return str(as_posix())
    return str(path)


def _webhook_payload(channel: str, text: str) -> dict[str, object]:
    if channel in {"feishu", "lark"}:
        return {"msg_type": "text", "content": {"text": text}}
    return {"msgtype": "markdown", "markdown": {"content": text}}


def _post_json(url: str, payload: Mapping[str, object], timeout_seconds: float) -> int:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "ai-researcher/0.1",
        },
        method="POST",
    )
    context = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(request, timeout=timeout_seconds, context=context) as response:
        return int(response.status)


def _truncate(text: str, *, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20].rstrip() + "\n...[truncated]"
