from datetime import datetime, timezone
from pathlib import Path

from autoresearch.inspiration import InspirationItem, InspirationRefreshReport
from autoresearch.notifications import render_inspiration_digest, send_inspiration_digest


def _report() -> InspirationRefreshReport:
    return InspirationRefreshReport(
        queries=("research agents",),
        fetches=(),
        items=(
            InspirationItem(
                source="hacker_news",
                source_type="forum_signal",
                title="Show HN: Research agent",
                url="https://news.ycombinator.com/item?id=123",
                query="research agents",
                summary="Community signal only.",
                score=42.0,
                retrieved_at=datetime.now(timezone.utc),
            ),
        ),
        summary_path=Path("autoresearch-vault/exploration/inspiration/demo.md"),
    )


def test_render_inspiration_digest_keeps_policy_and_vault_note() -> None:
    digest = render_inspiration_digest(_report())

    assert "AI-Researcher inspiration digest" in digest
    assert "Show HN: Research agent" in digest
    assert "Vault note: autoresearch-vault/exploration/inspiration/demo.md" in digest
    assert "validate before citing" in digest


def test_send_inspiration_digest_posts_configured_webhooks() -> None:
    calls: list[tuple[str, dict[str, object], float]] = []

    def fake_sender(url: str, payload, timeout_seconds: float) -> int:
        calls.append((url, dict(payload), timeout_seconds))
        return 200

    records = send_inspiration_digest(
        _report(),
        env={
            "AUTORESEARCH_WECHAT_WEBHOOK_URL": "https://wechat.example.test/hook",
            "AUTORESEARCH_FEISHU_WEBHOOK_URL": "https://feishu.example.test/hook",
        },
        sender=fake_sender,
        timeout_seconds=3.0,
    )

    assert [record.status for record in records] == ["sent", "sent"]
    assert calls[0][0] == "https://wechat.example.test/hook"
    assert calls[0][1]["msgtype"] == "markdown"
    assert calls[1][0] == "https://feishu.example.test/hook"
    assert calls[1][1]["msg_type"] == "text"
    assert calls[0][2] == 3.0


def test_send_inspiration_digest_records_missing_webhook_without_network() -> None:
    records = send_inspiration_digest(_report(), env={})

    assert [record.status for record in records] == ["skipped", "skipped"]
    assert "missing AUTORESEARCH_WECHAT_WEBHOOK_URL" in records[0].detail


def test_send_inspiration_digest_uses_feishu_app_credentials_with_home_chat() -> None:
    token_calls: list[tuple[str, str, str, float]] = []
    message_calls: list[tuple[str, str, str, str, float]] = []

    def fake_token_getter(
        base_url: str,
        app_id: str,
        app_secret: str,
        timeout_seconds: float,
    ) -> str:
        token_calls.append((base_url, app_id, app_secret, timeout_seconds))
        return "tenant-token"

    def fake_message_sender(
        base_url: str,
        token: str,
        home_chat_id: str,
        text: str,
        timeout_seconds: float,
    ) -> int:
        message_calls.append((base_url, token, home_chat_id, text, timeout_seconds))
        return 200

    records = send_inspiration_digest(
        _report(),
        channels=("feishu",),
        env={
            "AUTORESEARCH_FEISHU_CONNECTION_MODE": "websocket",
            "AUTORESEARCH_FEISHU_BASE_URL": "https://open.feishu.example.test",
            "AUTORESEARCH_FEISHU_APP_ID": "cli_a_test",
            "AUTORESEARCH_FEISHU_APP_SECRET": "secret",
            "AUTORESEARCH_FEISHU_HOME_CHAT_ID": "oc_test",
        },
        feishu_token_getter=fake_token_getter,
        feishu_message_sender=fake_message_sender,
        timeout_seconds=4.0,
    )

    assert [record.status for record in records] == ["sent"]
    assert records[0].detail == "feishu app API accepted"
    assert token_calls == [("https://open.feishu.example.test", "cli_a_test", "secret", 4.0)]
    assert message_calls[0][0:3] == ("https://open.feishu.example.test", "tenant-token", "oc_test")
    assert "Show HN: Research agent" in message_calls[0][3]


def test_send_inspiration_digest_reports_feishu_app_missing_home_chat() -> None:
    records = send_inspiration_digest(
        _report(),
        channels=("feishu",),
        env={
            "AUTORESEARCH_FEISHU_CONNECTION_MODE": "websocket",
            "AUTORESEARCH_FEISHU_APP_ID": "cli_a_test",
            "AUTORESEARCH_FEISHU_APP_SECRET": "secret",
        },
    )

    assert records[0].status == "skipped"
    assert "missing AUTORESEARCH_FEISHU_HOME_CHAT_ID" in records[0].detail


def test_send_inspiration_digest_reports_wechat_qr_gateway_without_webhook() -> None:
    records = send_inspiration_digest(
        _report(),
        channels=("wechat",),
        env={
            "AUTORESEARCH_WECHAT_CONNECTION_MODE": "qr",
            "AUTORESEARCH_WECHAT_QR_SETUP_COMMAND": "npx -y @tencent-weixin/openclaw-weixin-cli install",
        },
    )

    assert records[0].status == "skipped"
    assert "wechat QR gateway configured" in records[0].detail
    assert "@tencent-weixin/openclaw-weixin-cli" in records[0].detail
