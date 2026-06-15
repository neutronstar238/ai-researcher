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
