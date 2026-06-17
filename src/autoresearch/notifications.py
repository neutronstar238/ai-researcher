"""Operator notification helpers for AI-Researcher."""

from __future__ import annotations

import json
import os
import shlex
import ssl
import subprocess
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
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
FeishuTokenGetter = Callable[[str, str, str, float], str]
FeishuMessageSender = Callable[[str, str, str, str, float], int]
CommandRunner = Callable[[list[str], float], int]


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
    feishu_token_getter: FeishuTokenGetter | None = None,
    feishu_message_sender: FeishuMessageSender | None = None,
    command_runner: CommandRunner | None = None,
    timeout_seconds: float = 10.0,
) -> tuple[NotificationSendRecord, ...]:
    """Send a compact inspiration digest to configured operator channels."""

    environment = env or os.environ
    post_json = sender or _post_json
    get_feishu_token = feishu_token_getter or _feishu_tenant_access_token
    send_feishu_message = feishu_message_sender or _post_feishu_text_message
    run_command = command_runner or _run_command
    digest = render_inspiration_digest(report)
    records: list[NotificationSendRecord] = []
    for channel in channels:
        normalized = channel.casefold().strip()
        if normalized in {"feishu", "lark"}:
            records.append(
                _send_feishu_digest(
                    environment=environment,
                    digest=digest,
                    post_json=post_json,
                    get_feishu_token=get_feishu_token,
                    send_feishu_message=send_feishu_message,
                    timeout_seconds=timeout_seconds,
                )
            )
            continue
        if normalized in {"wechat", "weixin", "wecom"}:
            records.append(
                _send_wechat_digest(
                    channel=normalized,
                    environment=environment,
                    digest=digest,
                    post_json=post_json,
                    run_command=run_command,
                    timeout_seconds=timeout_seconds,
                )
            )
            continue
        records.append(
            NotificationSendRecord(
                channel=channel,
                status="skipped",
                detail="unsupported channel",
            )
        )
    return tuple(records)


def _send_wechat_digest(
    *,
    channel: str,
    environment: Mapping[str, str],
    digest: str,
    post_json: WebhookSender,
    run_command: CommandRunner,
    timeout_seconds: float,
) -> NotificationSendRecord:
    mode = str(environment.get("AUTORESEARCH_WECHAT_CONNECTION_MODE", "")).strip().casefold()
    if mode == "qr":
        command = str(
            environment.get(
                "AUTORESEARCH_WECHAT_QR_SETUP_COMMAND",
                "npx -y @tencent-weixin/openclaw-weixin-cli install",
            )
        ).strip()
        login_command = str(
            environment.get(
                "AUTORESEARCH_WECHAT_QR_LOGIN_COMMAND",
                "openclaw channels login --channel openclaw-weixin",
            )
        ).strip()
        status_path = str(
            environment.get(
                "AUTORESEARCH_WECHAT_SETUP_STATUS_PATH",
                ".airesearcher/channels/wechat/setup-status.json",
            )
        ).strip()
        status_detail = _wechat_qr_status_detail(status_path)
        if not status_detail.startswith("setup status completed"):
            return NotificationSendRecord(
                channel=channel,
                status="skipped",
                detail=(
                    "wechat QR gateway configured but QR login is not completed; "
                    f"{status_detail}; run `{command}` or `{login_command}`"
                ),
            )
        openclaw_target = str(environment.get("AUTORESEARCH_WECHAT_OPENCLAW_TARGET", "")).strip()
        if not openclaw_target:
            return NotificationSendRecord(
                channel=channel,
                status="skipped",
                detail=(
                    "wechat QR gateway configured but missing "
                    "AUTORESEARCH_WECHAT_OPENCLAW_TARGET for outbound delivery; "
                    f"{status_detail}; run or verify `{login_command}` and bind the target"
                ),
            )
        openclaw_channel = str(
            environment.get("AUTORESEARCH_WECHAT_OPENCLAW_CHANNEL", "openclaw-weixin")
        ).strip()
        message_command = str(
            environment.get("AUTORESEARCH_WECHAT_OPENCLAW_MESSAGE_COMMAND", "openclaw message send")
        ).strip()
        args = shlex.split(message_command) + [
            "--channel",
            openclaw_channel,
            "--target",
            openclaw_target,
            "--message",
            digest,
        ]
        try:
            return_code = run_command(args, timeout_seconds)
        except Exception as exc:  # noqa: BLE001 - outbound notification must report failures.
            return NotificationSendRecord(
                channel=channel,
                status="failed",
                detail=f"openclaw message send failed: {type(exc).__name__}: {exc}",
            )
        status = "sent" if return_code == 0 else "failed"
        return NotificationSendRecord(
            channel=channel,
            status=status,
            detail=(
                "openclaw message send accepted"
                if status == "sent"
                else f"openclaw message send exited {return_code}"
            ),
            status_code=return_code,
        )
    return _send_webhook_digest(
        channel=channel,
        url_env="AUTORESEARCH_WECHAT_WEBHOOK_URL",
        environment=environment,
        digest=digest,
        post_json=post_json,
        timeout_seconds=timeout_seconds,
    )


def _send_feishu_digest(
    *,
    environment: Mapping[str, str],
    digest: str,
    post_json: WebhookSender,
    get_feishu_token: FeishuTokenGetter,
    send_feishu_message: FeishuMessageSender,
    timeout_seconds: float,
) -> NotificationSendRecord:
    mode = str(environment.get("AUTORESEARCH_FEISHU_CONNECTION_MODE", "")).strip().casefold()
    app_id = str(environment.get("AUTORESEARCH_FEISHU_APP_ID", "")).strip()
    app_secret = str(environment.get("AUTORESEARCH_FEISHU_APP_SECRET", "")).strip()
    home_chat_id = str(environment.get("AUTORESEARCH_FEISHU_HOME_CHAT_ID", "")).strip()
    if mode != "webhook" and app_id and app_secret:
        if not home_chat_id:
            return NotificationSendRecord(
                channel="feishu",
                status="skipped",
                detail=(
                    "feishu app credentials configured; missing "
                    "AUTORESEARCH_FEISHU_HOME_CHAT_ID or gateway home channel"
                ),
            )
        try:
            base_url = str(
                environment.get("AUTORESEARCH_FEISHU_BASE_URL", "https://open.feishu.cn")
            ).strip()
            token = get_feishu_token(base_url, app_id, app_secret, timeout_seconds)
            status_code = send_feishu_message(
                base_url,
                token,
                home_chat_id,
                digest,
                timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001 - outbound notification must not hide failures.
            return NotificationSendRecord(
                channel="feishu",
                status="failed",
                detail=f"{type(exc).__name__}: {exc}",
            )
        status = "sent" if 200 <= status_code < 300 else "failed"
        return NotificationSendRecord(
            channel="feishu",
            status=status,
            detail="feishu app API accepted" if status == "sent" else "feishu app API non-2xx",
            status_code=status_code,
        )
    return _send_webhook_digest(
        channel="feishu",
        url_env="AUTORESEARCH_FEISHU_WEBHOOK_URL",
        environment=environment,
        digest=digest,
        post_json=post_json,
        timeout_seconds=timeout_seconds,
    )


def _send_webhook_digest(
    *,
    channel: str,
    url_env: str,
    environment: Mapping[str, str],
    digest: str,
    post_json: WebhookSender,
    timeout_seconds: float,
) -> NotificationSendRecord:
    webhook_url = str(environment.get(url_env, "")).strip()
    if not webhook_url:
        return NotificationSendRecord(
            channel=channel,
            status="skipped",
            detail=f"missing {url_env}",
        )
    try:
        status_code = post_json(
            webhook_url,
            _webhook_payload(channel, digest),
            timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001 - outbound notification must not hide failures.
        return NotificationSendRecord(
            channel=channel,
            status="failed",
            detail=f"{type(exc).__name__}: {exc}",
        )
    status = "sent" if 200 <= status_code < 300 else "failed"
    return NotificationSendRecord(
        channel=channel,
        status=status,
        detail="webhook accepted" if status == "sent" else "webhook returned non-2xx",
        status_code=status_code,
    )


def _run_command(args: list[str], timeout_seconds: float) -> int:
    completed = subprocess.run(args, check=False, timeout=timeout_seconds)
    return completed.returncode


def _wechat_qr_status_detail(status_path: str) -> str:
    if not status_path:
        return "setup status path not configured"
    path = Path(status_path)
    if not path.exists():
        return f"setup status missing at {status_path}"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"setup status unreadable at {status_path}: {type(exc).__name__}"
    if not isinstance(payload, Mapping):
        return f"setup status unreadable at {status_path}: invalid payload"
    status = str(payload.get("status", "unknown"))
    completed_at = payload.get("completed_at")
    if completed_at:
        return f"setup status {status} at {status_path} ({completed_at})"
    return f"setup status {status} at {status_path}"


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


def _path_text(path: Any) -> str:
    as_posix = getattr(path, "as_posix", None)
    if callable(as_posix):
        return str(as_posix())
    return str(path)


def _webhook_payload(channel: str, text: str) -> dict[str, object]:
    if channel in {"feishu", "lark"}:
        return {"msg_type": "text", "content": {"text": text}}
    return {"msgtype": "markdown", "markdown": {"content": text}}


def _feishu_tenant_access_token(
    base_url: str,
    app_id: str,
    app_secret: str,
    timeout_seconds: float,
) -> str:
    payload = {"app_id": app_id, "app_secret": app_secret}
    status_code, response = _post_json_response(
        _join_url(base_url, "/open-apis/auth/v3/tenant_access_token/internal"),
        payload,
        timeout_seconds,
    )
    if not 200 <= status_code < 300:
        msg = f"Feishu token endpoint returned HTTP {status_code}"
        raise RuntimeError(msg)
    code = response.get("code")
    if code not in {0, "0", None}:
        msg = f"Feishu token endpoint rejected request: {response.get('msg') or code}"
        raise RuntimeError(msg)
    token = response.get("tenant_access_token")
    if not isinstance(token, str) or not token.strip():
        msg = "Feishu token endpoint returned no tenant_access_token"
        raise RuntimeError(msg)
    return token.strip()


def _post_feishu_text_message(
    base_url: str,
    tenant_access_token: str,
    home_chat_id: str,
    text: str,
    timeout_seconds: float,
) -> int:
    payload = {
        "receive_id": home_chat_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}),
    }
    status_code, _ = _post_json_response(
        _join_url(base_url, "/open-apis/im/v1/messages?receive_id_type=chat_id"),
        payload,
        timeout_seconds,
        headers={"Authorization": f"Bearer {tenant_access_token}"},
    )
    return status_code


def _post_json(url: str, payload: Mapping[str, object], timeout_seconds: float) -> int:
    status_code, _ = _post_json_raw(url, payload, timeout_seconds)
    return status_code


def _post_json_response(
    url: str,
    payload: Mapping[str, object],
    timeout_seconds: float,
    *,
    headers: Mapping[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    status_code, body = _post_json_raw(url, payload, timeout_seconds, headers=headers)
    if not body:
        return status_code, {}
    parsed = json.loads(body.decode("utf-8"))
    if not isinstance(parsed, dict):
        msg = "JSON response is not an object"
        raise RuntimeError(msg)
    return status_code, parsed


def _post_json_raw(
    url: str,
    payload: Mapping[str, object],
    timeout_seconds: float,
    *,
    headers: Mapping[str, str] | None = None,
) -> tuple[int, bytes]:
    data = json.dumps(payload).encode("utf-8")
    request_headers = {
        "Content-Type": "application/json",
        "User-Agent": "ai-researcher/1.0",
    }
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(
        url,
        data=data,
        headers=request_headers,
        method="POST",
    )
    context = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(request, timeout=timeout_seconds, context=context) as response:
        body = response.read()
        status_code = int(response.status)
    return status_code, body


def _join_url(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + "/" + path.lstrip("/")



def _truncate(text: str, *, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20].rstrip() + "\n...[truncated]"
