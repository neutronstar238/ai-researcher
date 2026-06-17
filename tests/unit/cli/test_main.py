import json
import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import autoresearch.cli.main as cli_main
from autoresearch import __version__
from autoresearch.cli.main import app
from autoresearch.config import ConfigParser, SystemConfig
from autoresearch.inspiration import (
    InspirationFetchRecord,
    InspirationItem,
    InspirationRefreshReport,
)
from autoresearch.knowledge import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    SuccessfulPatternExample,
    extract_reusable_skill_card,
)
from autoresearch.llm import LLMReviewResult, LLMSmokeResult
from autoresearch.schemas import ResearchCandidate, ResearchPlan


def test_version_command_prints_package_version() -> None:
    result = CliRunner().invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_doctor_command_checks_local_scaffold() -> None:
    result = CliRunner().invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "[OK] python >= 3.10" in result.stdout
    assert "[OK] config parser" in result.stdout
    assert "[OK] knowledge vault" in result.stdout


def test_init_demo_creates_readme_and_config(tmp_path: Path) -> None:
    demo_path = tmp_path / "demo"

    result = CliRunner().invoke(app, ["init-demo", "--path", str(demo_path)])

    assert result.exit_code == 0
    assert (demo_path / "README.md").is_file()
    assert (demo_path / "config.yaml").is_file()


def test_obsidian_setup_creates_vault_assets_and_local_snippet(tmp_path: Path) -> None:
    vault_root = tmp_path / "autoresearch-vault"

    result = CliRunner().invoke(
        app,
        [
            "obsidian-setup",
            "--vault",
            str(vault_root),
            "--project-id",
            "project_1",
            "--write-local-snippet",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "[OK] vault_home:" in result.stdout
    assert "[OK] templates: 6" in result.stdout
    assert (vault_root / "Home.md").is_file()
    assert (vault_root / "_system" / "dashboards" / "research-loop.md").is_file()
    assert (vault_root / "_system" / "plugins" / "recommended-plugins.md").is_file()
    assert (vault_root / "_system" / "templates" / "skill-card.md").is_file()
    assert (vault_root / ".obsidian" / "snippets" / "ai-researcher.css").is_file()
    assert "enabledCssSnippets" in (vault_root / ".obsidian" / "appearance.json").read_text(
        encoding="utf-8"
    )


def test_skill_watchlist_writes_external_candidates(tmp_path: Path) -> None:
    vault_root = tmp_path / "autoresearch-vault"

    result = CliRunner().invoke(
        app,
        [
            "skill-watchlist",
            "--vault",
            str(vault_root),
            "--source-note",
            "unit test scouting batch",
        ],
    )

    watchlist_path = (
        vault_root / "exploration" / "skills" / "external-research-skill-watchlist.md"
    )
    markdown = watchlist_path.read_text(encoding="utf-8")

    assert result.exit_code == 0, result.output
    assert "[OK] skill_watchlist: written" in result.stdout
    assert "[OK] candidate_count:" in result.stdout
    assert watchlist_path.is_file()
    assert "unit test scouting batch" in markdown
    assert "CCFA-Skill" in markdown
    assert "SkillClaw" in markdown
    assert "Status: `quarantine`" in markdown


def test_skill_evolve_creates_bounded_candidate_from_issue_ref(tmp_path: Path) -> None:
    vault_root = tmp_path / "autoresearch-vault"
    parent = extract_reusable_skill_card(
        vault_root=vault_root,
        name="Evidence-first demo review",
        examples=(
            SuccessfulPatternExample(
                project_id="project_a",
                experience_ref="projects/project_a/experience/review_a",
                summary="Review passed after adding run record evidence.",
                trigger_conditions=("demo report review",),
                actions=("attach run record evidence",),
                success_metrics=("review_quality_score >= 0.85",),
            ),
            SuccessfulPatternExample(
                project_id="project_b",
                experience_ref="projects/project_b/experience/review_b",
                summary="Unsupported reproduction claims were blocked.",
                trigger_conditions=("demo report review",),
                actions=("attach run record evidence",),
                success_metrics=("unsupported_claims = 0",),
            ),
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "skill-evolve",
            "--vault",
            str(vault_root),
            "--parent-skill-id",
            parent.skill_id,
            "--change-summary",
            "Require run-record evidence before promoting a demo report.",
            "--issue-ref",
            "projects/project_a/issues/llm_review_missing_evidence",
            "--proposed-action",
            "attach run record before live review",
            "--validation-check",
            "real LLM review score >= 0.85",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "[OK] candidate_skill_id:" in result.stdout
    assert "[OK] rejected_edit_buffer:" in result.stdout
    candidate_paths = list((vault_root / "exploration" / "skills" / "candidates").glob("*.md"))
    assert candidate_paths

    audit_output = tmp_path / "runs" / "skill-polish.json"
    audit_result = CliRunner().invoke(
        app,
        [
            "skill-polish-audit",
            "--vault",
            str(vault_root),
            "--skill-id",
            candidate_paths[0].stem,
            "--peer-ref",
            "https://github.com/LearnPrompt/luban-skill",
            "--live-evidence-ref",
            "runs/skill-polish/demo-validation.json",
            "--install-ref",
            ".opencode/skills/ai-researcher-evidence-gate/SKILL.md",
            "--release-ref",
            "autoresearch-vault/exploration/skills/rejected/demo_rejections.md",
            "--output",
            str(audit_output),
        ],
    )

    assert audit_result.exit_code == 0, audit_result.output
    assert "[OK] skill_polish_audit: passed" in audit_result.stdout
    payload = json.loads(audit_output.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert (tmp_path / "runs" / "skill-polish.md").is_file()


def test_inspiration_refresh_command_writes_report(tmp_path: Path, monkeypatch) -> None:
    vault_path = tmp_path / "vault"
    output = tmp_path / "runs" / "inspiration.json"
    summary_path = vault_path / "exploration" / "inspiration" / "summary.md"

    def fake_run_inspiration_refresh(*, vault_root, queries, config):
        assert vault_root == vault_path
        assert config.max_queries == 3
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text("# Summary\n", encoding="utf-8")
        return InspirationRefreshReport(
            queries=tuple(queries),
            fetches=(
                InspirationFetchRecord(
                    source="hacker_news",
                    source_type="forum_signal",
                    query=queries[0],
                    result_count=1,
                    rate_limit_seconds=1.0,
                ),
            ),
            items=(
                InspirationItem(
                    source="hacker_news",
                    source_type="forum_signal",
                    title="Research agent thread",
                    url="https://news.ycombinator.com/item?id=123",
                    query=queries[0],
                    summary="Community signal only.",
                    score=3.0,
                    retrieved_at=datetime.now(timezone.utc),
                ),
            ),
            summary_path=summary_path,
        )

    monkeypatch.setattr(cli_main, "run_inspiration_refresh", fake_run_inspiration_refresh)

    result = CliRunner().invoke(
        app,
        [
            "inspiration-refresh",
            "--vault",
            str(vault_path),
            "--query",
            "research agents",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "[OK] inspiration_items: 1" in result.stdout
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["items"][0]["source_type"] == "forum_signal"
    assert payload["summary_path"] == summary_path.as_posix()


def test_inspiration_refresh_command_can_push_digest(tmp_path: Path, monkeypatch) -> None:
    vault_path = tmp_path / "vault"
    output = tmp_path / "runs" / "inspiration.json"
    summary_path = vault_path / "exploration" / "inspiration" / "summary.md"

    def fake_run_inspiration_refresh(*, vault_root, queries, config):
        assert vault_root == vault_path
        assert config.max_results_per_source == 5
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text("# Summary\n", encoding="utf-8")
        return InspirationRefreshReport(
            queries=tuple(queries),
            fetches=(),
            items=(
                InspirationItem(
                    source="hacker_news",
                    source_type="forum_signal",
                    title="Research agent thread",
                    url="https://news.ycombinator.com/item?id=123",
                    query=queries[0],
                    summary="Community signal only.",
                    score=3.0,
                    retrieved_at=datetime.now(timezone.utc),
                ),
            ),
            summary_path=summary_path,
        )

    def fake_send_inspiration_digest(report, *, channels, timeout_seconds):
        assert len(report.items) == 1
        assert channels == ("feishu",)
        assert timeout_seconds == 2.0
        return (
            cli_main.NotificationSendRecord(
                channel="feishu",
                status="sent",
                detail="webhook accepted",
                status_code=200,
            ),
        )

    monkeypatch.setattr(cli_main, "run_inspiration_refresh", fake_run_inspiration_refresh)
    monkeypatch.setattr(cli_main, "send_inspiration_digest", fake_send_inspiration_digest)

    result = CliRunner().invoke(
        app,
        [
            "inspiration-refresh",
            "--vault",
            str(vault_path),
            "--query",
            "research agents",
            "--output",
            str(output),
            "--push",
            "--push-channel",
            "feishu",
            "--push-timeout-seconds",
            "2",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "[PUSH] channel=feishu status=sent detail=webhook accepted" in result.stdout
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["pushes"][0]["channel"] == "feishu"
    assert payload["pushes"][0]["status_code"] == 200


def test_deploy_setup_writes_provider_config_and_env_without_committing_secret(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    env_example_path = tmp_path / ".env.example"

    result = CliRunner().invoke(
        app,
        [
            "deploy-setup",
            "--config",
            str(config_path),
            "--env-path",
            str(env_path),
            "--provider",
            "openai-compatible",
            "--base-url",
            "https://llm.example.test/v1",
            "--model-name",
            "research-model",
            "--api-key",
            "sk-test",
            "--wechat",
            "--wechat-webhook-url",
            "https://wechat.example.test/hook",
            "--feishu",
            "--feishu-webhook-url",
            "https://feishu.example.test/hook",
            "--non-interactive",
        ],
    )

    assert result.exit_code == 0, result.output
    config = ConfigParser().parse_file(config_path)
    assert isinstance(config, SystemConfig)
    assert config.deployment.llm.base_url == "https://llm.example.test/v1"
    assert config.deployment.llm.model_name == "research-model"
    assert config.deployment.llm.api_key_env == "AUTORESEARCH_LLM_API_KEY"
    assert config.deployment.wechat.enabled is True
    assert config.deployment.feishu.enabled is True

    config_text = config_path.read_text(encoding="utf-8")
    env_text = env_path.read_text(encoding="utf-8")
    env_example_text = env_example_path.read_text(encoding="utf-8")
    assert "sk-test" not in config_text
    assert "AUTORESEARCH_LLM_API_KEY=sk-test" in env_text
    assert "AUTORESEARCH_WECHAT_WEBHOOK_URL=https://wechat.example.test/hook" in env_text
    assert "AUTORESEARCH_FEISHU_WEBHOOK_URL=https://feishu.example.test/hook" in env_text
    assert "env template created" in result.stdout
    assert "AUTORESEARCH_LLM_API_KEY=" in env_example_text
    assert "SEMANTIC_SCHOLAR_API_KEY=" in env_example_text
    assert "SEMANTIC_SCHOLAR_MIN_INTERVAL_SECONDS=" in env_example_text
    assert "SEMANTIC_SCHOLAR_CIRCUIT_RESET_SECONDS=" in env_example_text
    assert "sk-test" not in env_example_text


def test_deploy_setup_configures_qr_wechat_and_feishu_app_gateway(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"

    result = CliRunner().invoke(
        app,
        [
            "deploy-setup",
            "--config",
            str(config_path),
            "--env-path",
            str(env_path),
            "--provider",
            "openai-compatible",
            "--base-url",
            "https://llm.example.test/v1",
            "--model-name",
            "research-model",
            "--api-key",
            "sk-test",
            "--wechat",
            "--wechat-qr",
            "--feishu",
            "--feishu-app-id",
            "cli_a_test",
            "--feishu-app-secret",
            "feishu-secret",
            "--feishu-home-chat-id",
            "oc_test_chat",
            "--non-interactive",
        ],
    )

    assert result.exit_code == 0, result.output
    config = ConfigParser().parse_file(config_path)
    assert isinstance(config, SystemConfig)
    assert config.deployment.wechat.connection_mode == "qr"
    assert config.deployment.wechat.qr_setup_command_env == "AUTORESEARCH_WECHAT_QR_SETUP_COMMAND"
    assert config.deployment.feishu.connection_mode == "websocket"
    assert config.deployment.feishu.app_id_env == "AUTORESEARCH_FEISHU_APP_ID"
    assert config.deployment.feishu.home_chat_id_env == "AUTORESEARCH_FEISHU_HOME_CHAT_ID"

    env_text = env_path.read_text(encoding="utf-8")
    assert "AUTORESEARCH_WECHAT_CONNECTION_MODE=qr" in env_text
    assert "AUTORESEARCH_WECHAT_QR_SETUP_COMMAND=npx -y @tencent-weixin/openclaw-weixin-cli install" in env_text
    assert "AUTORESEARCH_FEISHU_CONNECTION_MODE=websocket" in env_text
    assert "AUTORESEARCH_FEISHU_APP_ID=cli_a_test" in env_text
    assert "AUTORESEARCH_FEISHU_HOME_CHAT_ID=oc_test_chat" in env_text
    assert "[OK] wechat: enabled (qr)" in result.stdout
    assert "[OK] feishu: enabled (websocket)" in result.stdout
    assert "[NEXT] wechat_qr_setup: npx -y @tencent-weixin/openclaw-weixin-cli install" in result.stdout


def test_deploy_setup_keeps_existing_env_example_template(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    env_example_path = tmp_path / ".env.example"
    env_example_path.write_text("CUSTOM_TEMPLATE=1\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "deploy-setup",
            "--config",
            str(config_path),
            "--env-path",
            str(env_path),
            "--provider",
            "openai-compatible",
            "--base-url",
            "https://llm.example.test/v1",
            "--model-name",
            "research-model",
            "--api-key",
            "sk-test",
            "--no-wechat",
            "--no-feishu",
            "--non-interactive",
        ],
    )

    assert result.exit_code == 0, result.output
    assert env_path.is_file()
    assert env_example_path.read_text(encoding="utf-8") == "CUSTOM_TEMPLATE=1\n"
    assert "env template ready" in result.stdout


def test_setup_reuses_existing_env_key_in_non_interactive_mode(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "AUTORESEARCH_LLM_PROVIDER=openai-compatible",
                "AUTORESEARCH_LLM_BASE_URL=https://llm.example.test/v1",
                "AUTORESEARCH_LLM_MODEL_NAME=research-model",
                "AUTORESEARCH_LLM_API_KEY=sk-existing",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        [
            "setup",
            "--config",
            str(tmp_path / "config.yaml"),
            "--env-path",
            str(env_path),
            "--no-wechat",
            "--no-feishu",
            "--vault",
            str(tmp_path / "vault"),
            "--integrations-dir",
            str(tmp_path / "integrations"),
            "--commands-dir",
            str(tmp_path / "commands"),
            "--non-interactive",
        ],
    )

    assert result.exit_code == 0, result.output
    env_text = env_path.read_text(encoding="utf-8")
    assert "AUTORESEARCH_LLM_API_KEY=sk-existing" in env_text
    assert "[OK] model: openai-compatible / research-model" in result.stdout


def test_setup_guided_wizard_collects_provider_and_api_key(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"

    result = CliRunner().invoke(
        app,
        [
            "setup",
            "--config",
            str(config_path),
            "--env-path",
            str(env_path),
            "--vault",
            str(tmp_path / "vault"),
            "--integrations-dir",
            str(tmp_path / "integrations"),
            "--commands-dir",
            str(tmp_path / "commands"),
            "--skip-obsidian",
            "--skip-integrations",
            "--skip-slash",
        ],
        input="\n\nresearch-model\nsk-guided\n\n",
    )

    assert result.exit_code == 0, result.output
    assert "AI-Researcher setup wizard" in result.stdout
    assert "1. DeepSeek" in result.stdout
    config = ConfigParser().parse_file(config_path)
    assert isinstance(config, SystemConfig)
    assert config.deployment.llm.provider == "deepseek"
    assert config.deployment.llm.base_url == "https://api.deepseek.com"
    assert config.deployment.llm.model_name == "research-model"
    env_text = env_path.read_text(encoding="utf-8")
    assert "AUTORESEARCH_LLM_API_KEY=sk-guided" in env_text
    assert "[OK] wechat: disabled" in result.stdout
    assert "[OK] feishu: disabled" in result.stdout


def test_setup_guided_wechat_qr_runs_qr_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(cli_main, "_run_wechat_qr_setup", lambda: calls.append("qr"))
    config_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"

    result = CliRunner().invoke(
        app,
        [
            "setup",
            "--config",
            str(config_path),
            "--env-path",
            str(env_path),
            "--vault",
            str(tmp_path / "vault"),
            "--integrations-dir",
            str(tmp_path / "integrations"),
            "--commands-dir",
            str(tmp_path / "commands"),
            "--skip-obsidian",
            "--skip-integrations",
            "--skip-slash",
        ],
        input="\n\nresearch-model\nsk-guided\n2\n1\n",
    )

    assert result.exit_code == 0, result.output
    assert calls == ["qr"]
    assert "[OK] wechat: enabled (qr)" in result.stdout
    assert "[NEXT] wechat_qr_setup: npx -y @tencent-weixin/openclaw-weixin-cli install" in result.stdout
    config = ConfigParser().parse_file(config_path)
    assert isinstance(config, SystemConfig)
    assert config.deployment.wechat.connection_mode == "qr"


def test_deploy_setup_requires_enabled_channel_credentials(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "deploy-setup",
            "--config",
            str(tmp_path / "config.yaml"),
            "--env-path",
            str(tmp_path / ".env"),
            "--provider",
            "openai-compatible",
            "--base-url",
            "https://llm.example.test/v1",
            "--model-name",
            "research-model",
            "--api-key",
            "sk-test",
            "--wechat",
            "--non-interactive",
        ],
    )

    assert result.exit_code != 0
    assert "WeChat requires" in result.output


def test_setup_bootstraps_env_vault_manifests_and_slash_commands(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    vault = tmp_path / "autoresearch-vault"
    integrations = tmp_path / "integrations"
    commands = tmp_path / "commands"

    result = CliRunner().invoke(
        app,
        [
            "setup",
            "--config",
            str(config_path),
            "--env-path",
            str(env_path),
            "--provider",
            "openai-compatible",
            "--base-url",
            "https://llm.example.test/v1",
            "--model-name",
            "research-model",
            "--api-key",
            "sk-test",
            "--no-wechat",
            "--no-feishu",
            "--vault",
            str(vault),
            "--project-id",
            "project_1",
            "--integrations-dir",
            str(integrations),
            "--commands-dir",
            str(commands),
            "--non-interactive",
        ],
    )

    assert result.exit_code == 0, result.output
    assert config_path.is_file()
    assert env_path.is_file()
    assert (vault / "Home.md").is_file()
    assert (integrations / "channels" / "adapters.json").is_file()
    assert (integrations / "opencode" / "code-agent.json").is_file()
    scansci_manifest = integrations / "scansci-pdf" / "pdf-source.json"
    assert scansci_manifest.is_file()
    scansci_payload = json.loads(scansci_manifest.read_text(encoding="utf-8"))
    assert scansci_payload["default_policy"]["mode"] == "oa_first_legal_only"
    assert (commands / "research" / "autopilot.toml").is_file()
    assert (commands / "research" / "scansci-pdf.toml").is_file()
    assert "[OK] next: airesearcher serve --permission-mode approve-dangerous" in result.stdout


def test_slash_commands_init_and_list_project_templates(tmp_path: Path) -> None:
    commands_dir = tmp_path / "commands"
    runner = CliRunner()

    init_result = runner.invoke(
        app,
        ["slash-commands", "init", "--directory", str(commands_dir)],
    )
    list_result = runner.invoke(
        app,
        ["slash-commands", "list", "--directory", str(commands_dir)],
    )

    assert init_result.exit_code == 0, init_result.output
    autopilot_template = (commands_dir / "research" / "autopilot.toml").read_text(
        encoding="utf-8"
    )
    assert (commands_dir / "research" / "refresh-literature.toml").is_file()
    assert (commands_dir / "research" / "inspiration-refresh.toml").is_file()
    assert (commands_dir / "research" / "similarity-check.toml").is_file()
    assert (commands_dir / "research" / "research-plan.toml").is_file()
    assert (commands_dir / "research" / "run-demo.toml").is_file()
    assert (commands_dir / "research" / "autopilot.toml").is_file()
    assert (commands_dir / "research" / "serve.toml").is_file()
    assert (commands_dir / "research" / "publication-audit.toml").is_file()
    assert (commands_dir / "research" / "publication-stability.toml").is_file()
    assert (commands_dir / "research" / "approve.toml").is_file()
    assert (commands_dir / "research" / "channel-adapters.toml").is_file()
    assert (commands_dir / "research" / "scansci-pdf.toml").is_file()
    assert (commands_dir / "research" / "code-agent-backends.toml").is_file()
    assert (commands_dir / "research" / "obsidian-setup.toml").is_file()
    assert (commands_dir / "research" / "skill-evolve.toml").is_file()
    assert (commands_dir / "research" / "skill-polish-audit.toml").is_file()
    assert (commands_dir / "research" / "skill-watchlist.toml").is_file()
    assert (commands_dir / "research" / "paper-build.toml").is_file()
    assert (commands_dir / "research" / "evidence-gate.toml").is_file()
    assert (commands_dir / "research" / "session-claim.toml").is_file()
    assert (commands_dir / "research" / "issue-followups.toml").is_file()
    assert (commands_dir / "research" / "status.toml").is_file()
    assert list_result.exit_code == 0, list_result.output
    assert "/research:autopilot" in list_result.stdout
    assert "/research:serve" in list_result.stdout
    assert "/research:publication-audit" in list_result.stdout
    assert "/research:publication-stability" in list_result.stdout
    assert "/research:approve" in list_result.stdout
    assert "/research:channel-adapters" in list_result.stdout
    assert "/research:scansci-pdf" in list_result.stdout
    assert "/research:code-agent-backends" in list_result.stdout
    assert "/research:obsidian-setup" in list_result.stdout
    assert "/research:skill-evolve" in list_result.stdout
    assert "/research:skill-polish-audit" in list_result.stdout
    assert "/research:skill-watchlist" in list_result.stdout
    assert "/research:paper-build" in list_result.stdout
    assert "/research:evidence-gate" in list_result.stdout
    assert "/research:session-claim" in list_result.stdout
    assert "/research:refresh-literature" in list_result.stdout
    assert "/research:inspiration-refresh" in list_result.stdout
    assert "/research:research-plan" in list_result.stdout
    assert "/research:issue-followups" in list_result.stdout
    assert "/research:similarity-check" in list_result.stdout
    assert "airesearcher autopilot" in autopilot_template
    assert "autoresearch autopilot" not in autopilot_template
    assert "airesearcher serve" in (
        commands_dir / "research" / "serve.toml"
    ).read_text(encoding="utf-8")
    assert "airesearcher runtime approve" in (
        commands_dir / "research" / "approve.toml"
    ).read_text(encoding="utf-8")
    assert "airesearcher publication-audit" in (
        commands_dir / "research" / "publication-audit.toml"
    ).read_text(encoding="utf-8")
    assert "airesearcher publication-stability" in (
        commands_dir / "research" / "publication-stability.toml"
    ).read_text(encoding="utf-8")
    assert "external conference template" in (
        commands_dir / "research" / "publication-stability.toml"
    ).read_text(encoding="utf-8")
    assert "external journal template" in (
        commands_dir / "research" / "publication-stability.toml"
    ).read_text(encoding="utf-8")
    assert "airesearcher inspiration-refresh" in (
        commands_dir / "research" / "inspiration-refresh.toml"
    ).read_text(encoding="utf-8")
    assert "airesearcher research-plan" in (
        commands_dir / "research" / "research-plan.toml"
    ).read_text(encoding="utf-8")
    assert "airesearcher skill-polish-audit" in (
        commands_dir / "research" / "skill-polish-audit.toml"
    ).read_text(encoding="utf-8")
    assert "airesearcher skill-watchlist" in (
        commands_dir / "research" / "skill-watchlist.toml"
    ).read_text(encoding="utf-8")
    assert "airesearcher channels adapters init" in (
        commands_dir / "research" / "channel-adapters.toml"
    ).read_text(encoding="utf-8")
    assert "airesearcher pdf-sources scansci-pdf init" in (
        commands_dir / "research" / "scansci-pdf.toml"
    ).read_text(encoding="utf-8")
    assert "airesearcher code-agents opencode init" in (
        commands_dir / "research" / "code-agent-backends.toml"
    ).read_text(encoding="utf-8")
    assert "airesearcher code-agents cc-switch init" in (
        commands_dir / "research" / "code-agent-backends.toml"
    ).read_text(encoding="utf-8")
    assert "airesearcher paper-build" in (
        commands_dir / "research" / "paper-build.toml"
    ).read_text(encoding="utf-8")
    assert "airesearcher evidence-gate" in (
        commands_dir / "research" / "evidence-gate.toml"
    ).read_text(encoding="utf-8")
    assert "airesearcher sessions claim" in (
        commands_dir / "research" / "session-claim.toml"
    ).read_text(encoding="utf-8")


def test_publication_audit_command_reports_and_can_fail_gate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    summary_path = tmp_path / "cycle-summary.json"
    summary_path.write_text("{}", encoding="utf-8")
    review_path = tmp_path / "llm-review.json"
    review_path.write_text("{}", encoding="utf-8")
    calls: list[dict[str, object]] = []

    def fake_audit(**kwargs: object) -> SimpleNamespace:
        calls.append(dict(kwargs))
        return SimpleNamespace(
            verdict=SimpleNamespace(value="fail"),
            publishable=False,
            score=0.25,
            markdown_path="audit.md",
            output_path="audit.json",
            review_path=str(kwargs.get("review_path") or ""),
            vault_review_path=None,
            vault_issue_path="vault/issues/publication-audit.md",
        )

    monkeypatch.setattr(cli_main, "audit_publication_quality", fake_audit)

    ok_result = CliRunner().invoke(
        app,
        [
            "publication-audit",
            str(summary_path),
            "--target",
            "ccf-b",
            "--review-json",
            str(review_path),
            "--no-fail-on-not-publishable",
        ],
    )
    fail_result = CliRunner().invoke(app, ["publication-audit", str(summary_path)])

    assert ok_result.exit_code == 0, ok_result.output
    assert "[OK] publication_audit: fail" in ok_result.stdout
    assert f"[OK] review: {review_path}" in ok_result.stdout
    assert "[OK] vault_issue: vault/issues/publication-audit.md" in ok_result.stdout
    assert fail_result.exit_code == 1
    assert calls[0]["cycle_summary_path"] == summary_path
    assert calls[0]["target"] == "ccf-b"
    assert calls[0]["review_path"] == review_path


def test_paper_build_command_reports_compiled_artifact(
    tmp_path: Path,
    monkeypatch,
) -> None:
    report_path = tmp_path / "report.md"
    report_path.write_text("# Demo\n", encoding="utf-8")

    def fake_build_latex_paper_from_markdown(**kwargs: object) -> SimpleNamespace:
        assert kwargs["markdown_path"] == report_path
        assert kwargs["template_id"] == "generic-article-two-column"
        assert kwargs["authors"] == ("Ada", "Grace")
        assert kwargs["vault_root"] == tmp_path / "vault"
        assert kwargs["project_id"] == "demo_project"
        assert kwargs["timeout_seconds"] == 120
        return SimpleNamespace(
            status=cli_main.LatexPaperBuildStatus.COMPILED,
            template=SimpleNamespace(id="generic-article-two-column"),
            tex_path="runs/paper/main.tex",
            pdf_path="runs/paper/main.pdf",
            markdown_path="runs/paper/paper-build.md",
            json_path="runs/paper/paper-build.json",
            vault_markdown_path="vault/projects/demo_project/paper/paper-build.md",
            missing_sections=(),
            dependency_resolution=SimpleNamespace(
                status=SimpleNamespace(value="not_required"),
                class_file="article.cls",
                artifact_path=None,
                message="built-in generic templates do not require external class recovery",
            ),
        )

    monkeypatch.setattr(
        cli_main,
        "build_latex_paper_from_markdown",
        fake_build_latex_paper_from_markdown,
    )

    result = CliRunner().invoke(
        app,
        [
            "paper-build",
            str(report_path),
            "--output-dir",
            str(tmp_path / "paper"),
            "--template-id",
            "generic-article-two-column",
            "--author",
            "Ada",
            "--author",
            "Grace",
            "--timeout-seconds",
            "120",
            "--vault",
            str(tmp_path / "vault"),
            "--project-id",
            "demo_project",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "[OK] paper_build: compiled" in result.stdout
    assert "[OK] pdf: runs/paper/main.pdf" in result.stdout
    assert "[OK] latex_dependency: status=not_required" in result.stdout
    assert "[OK] vault_paper: vault/projects/demo_project/paper/paper-build.md" in result.stdout


def test_evidence_gate_command_reports_blocked_gate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    summary_path = tmp_path / "cycle-summary.json"
    summary_path.write_text("{}", encoding="utf-8")
    publication_audit_path = tmp_path / "publication-audit.json"
    paper_build_path = tmp_path / "paper-build.json"
    calls: list[dict[str, object]] = []

    def fake_run_evidence_gate(**kwargs: object) -> SimpleNamespace:
        calls.append(dict(kwargs))
        return SimpleNamespace(
            verdict=cli_main.EvidenceGateVerdict.BLOCKED,
            release_allowed=False,
            failed_check_count=2,
            markdown_path="gate.md",
            output_path="gate.json",
            vault_review_path="vault/review/evidence-gate.md",
            vault_issue_path="vault/issues/evidence-gate.md",
        )

    monkeypatch.setattr(cli_main, "run_evidence_gate", fake_run_evidence_gate)

    ok_result = CliRunner().invoke(
        app,
        [
            "evidence-gate",
            str(summary_path),
            "--publication-audit",
            str(publication_audit_path),
            "--paper-build-json",
            str(paper_build_path),
            "--no-fail-on-blocked",
        ],
    )
    fail_result = CliRunner().invoke(app, ["evidence-gate", str(summary_path)])

    assert ok_result.exit_code == 0, ok_result.output
    assert "[OK] evidence_gate: blocked" in ok_result.stdout
    assert "[OK] failed_checks: 2" in ok_result.stdout
    assert "[OK] vault_issue: vault/issues/evidence-gate.md" in ok_result.stdout
    assert fail_result.exit_code == 1
    assert calls[0]["cycle_summary_path"] == summary_path
    assert calls[0]["publication_audit_path"] == publication_audit_path
    assert calls[0]["paper_build_path"] == paper_build_path


def test_publication_stability_command_reports_blocked_gate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    summary_path = tmp_path / "cycle-summary.json"
    summary_path.write_text("{}", encoding="utf-8")
    calls: list[dict[str, object]] = []

    def fake_stability(**kwargs: object) -> SimpleNamespace:
        calls.append(dict(kwargs))
        return SimpleNamespace(
            verdict=SimpleNamespace(value="blocked"),
            stable=False,
            score=0.375,
            cycles=(SimpleNamespace(),),
            markdown_path="runs/stability/publication-stability.md",
            output_path="runs/stability/publication-stability.json",
            vault_review_path="vault/review/publication-stability.md",
            vault_issue_path="vault/issues/publication-stability.md",
        )

    monkeypatch.setattr(cli_main, "audit_publication_stability", fake_stability)

    ok_result = CliRunner().invoke(
        app,
        [
            "publication-stability",
            str(summary_path),
            "--no-fail-on-unstable",
            "--vault",
            str(tmp_path / "vault"),
            "--project-id",
            "project_1",
        ],
    )
    fail_result = CliRunner().invoke(app, ["publication-stability", str(summary_path)])

    assert ok_result.exit_code == 0, ok_result.output
    assert "[OK] publication_stability: blocked" in ok_result.stdout
    assert "[OK] stable: false" in ok_result.stdout
    assert "[OK] cycles: 1" in ok_result.stdout
    assert "[OK] vault_issue: vault/issues/publication-stability.md" in ok_result.stdout
    assert fail_result.exit_code == 1
    assert calls[0]["cycle_summary_paths"] == (summary_path,)
    assert calls[0]["vault_root"] == tmp_path / "vault"
    assert calls[0]["project_id"] == "project_1"


def test_literature_refresh_command_reports_source_backed_documents(
    tmp_path: Path,
    monkeypatch,
) -> None:
    summary_path = tmp_path / "vault" / "exploration" / "topics" / "summary.md"
    env_path = tmp_path / ".env"
    env_path.write_text("SEMANTIC_SCHOLAR_API_KEY=semantic-test\n", encoding="utf-8")
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    captured: dict[str, object] = {}

    def fake_refresh(**kwargs):
        captured.update(kwargs)
        assert os.getenv("SEMANTIC_SCHOLAR_API_KEY") == "semantic-test"
        return SimpleNamespace(
            queries=(object(),),
            fetches=(
                SimpleNamespace(
                    source="arxiv",
                    query="machine learning benchmark",
                    paper_count=1,
                    cache_hit=False,
                    error=None,
                ),
            ),
            documents=(object(),),
            summary_path=summary_path,
        )

    monkeypatch.setattr(cli_main, "run_daily_literature_refresh", fake_refresh)

    result = CliRunner().invoke(
        app,
        [
            "literature-refresh",
            "--vault",
            str(tmp_path / "vault"),
            "--cache",
            str(tmp_path / "cache"),
            "--max-queries",
            "1",
            "--max-results-per-source",
            "1",
            "--env-path",
            str(env_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "[FETCH] source=arxiv papers=1" in result.stdout
    assert "[OK] documents: 1" in result.stdout
    assert captured["vault_root"] == tmp_path / "vault"
    assert captured["cache_root"] == tmp_path / "cache"


def test_similarity_check_command_loads_candidate_and_links_project(
    tmp_path: Path,
    monkeypatch,
) -> None:
    candidate = ResearchCandidate(
        id="candidate_cli_similarity",
        title="Machine Learning Benchmark Evidence",
        description="Check adjacent work before project start.",
        research_gap="Benchmark evidence needs source-backed checks.",
        novelty_score=0.6,
        feasibility_score=0.8,
        impact_score=0.6,
        evidence_refs=["seed"],
    )
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(candidate.model_dump_json(), encoding="utf-8")
    summary_path = tmp_path / "vault" / "exploration" / "topics" / "similarity.md"
    project_link = tmp_path / "vault" / "projects" / "project_1" / "knowledge" / "similarity.md"
    captured: dict[str, object] = {}

    def fake_similarity(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            candidate_id=candidate.id,
            queries=(object(),),
            fetches=(
                SimpleNamespace(
                    source="semantic_scholar",
                    query="benchmark evidence",
                    paper_count=1,
                    cache_hit=False,
                    error=None,
                ),
            ),
            findings=(object(),),
            summary_path=summary_path,
        )

    def fake_link(**kwargs):
        captured["link_kwargs"] = kwargs
        return project_link

    monkeypatch.setattr(cli_main, "run_project_similarity_check", fake_similarity)
    monkeypatch.setattr(cli_main, "link_similarity_report_to_project", fake_link)

    result = CliRunner().invoke(
        app,
        [
            "similarity-check",
            "--candidate-file",
            str(candidate_path),
            "--vault",
            str(tmp_path / "vault"),
            "--cache",
            str(tmp_path / "cache"),
            "--max-queries",
            "1",
            "--max-results-per-source",
            "1",
            "--project-id",
            "project_1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "[FETCH] source=semantic_scholar papers=1" in result.stdout
    assert "[OK] candidate: candidate_cli_similarity" in result.stdout
    assert "[OK] project_link:" in result.stdout
    assert captured["candidate"] == candidate
    assert captured["vault_root"] == tmp_path / "vault"
    assert captured["cache_root"] == tmp_path / "cache"
    assert captured["link_kwargs"]["project_id"] == "project_1"


def test_similarity_check_accepts_windows_utf8_bom_candidate_json(
    tmp_path: Path,
    monkeypatch,
) -> None:
    candidate = ResearchCandidate(
        id="candidate_cli_bom",
        title="Machine Learning Benchmark Evidence",
        description="Check adjacent work before project start.",
        research_gap="Benchmark evidence needs source-backed checks.",
        novelty_score=0.6,
        feasibility_score=0.8,
        impact_score=0.6,
        evidence_refs=["seed"],
    )
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(candidate.model_dump_json(), encoding="utf-8-sig")

    def fake_similarity(**kwargs):
        assert kwargs["candidate"] == candidate
        return SimpleNamespace(
            candidate_id=candidate.id,
            queries=(object(),),
            fetches=(
                SimpleNamespace(
                    source="arxiv",
                    query="benchmark evidence",
                    paper_count=1,
                    cache_hit=False,
                    error=None,
                ),
            ),
            findings=(object(),),
            summary_path=tmp_path / "summary.md",
        )

    monkeypatch.setattr(cli_main, "run_project_similarity_check", fake_similarity)

    result = CliRunner().invoke(
        app,
        [
            "similarity-check",
            "--candidate-file",
            str(candidate_path),
            "--vault",
            str(tmp_path / "vault"),
            "--cache",
            str(tmp_path / "cache"),
            "--max-queries",
            "1",
            "--max-results-per-source",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "[OK] candidate: candidate_cli_bom" in result.stdout


def test_research_plan_command_writes_vault_markdown_and_outputs(tmp_path: Path) -> None:
    candidate = ResearchCandidate(
        id="candidate_cli_plan",
        title="AI-Researcher system proposal",
        description="Plan an evidence traceability experiment.",
        research_gap="Metric claims are not tied to concrete execution artifacts.",
        novelty_score=0.7,
        feasibility_score=0.8,
        impact_score=0.6,
        evidence_refs=["https://example.org/source-paper"],
        metadata={
            "method": "evidence trace adapter",
            "dataset": "UCI Pendigits",
            "baseline": "nearest centroid baseline",
            "metric": "macro_f1",
        },
    )
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(candidate.model_dump_json(), encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "research-plan",
            "--candidate-file",
            str(candidate_path),
            "--project-id",
            "project_1",
            "--vault",
            str(tmp_path / "vault"),
            "--output-dir",
            str(tmp_path / "outputs"),
            "--no-compile-pdf",
        ],
    )

    markdown_path = tmp_path / "vault" / "projects" / "project_1" / "plans" / "research-plan.md"
    json_path = tmp_path / "outputs" / "project_1" / "research-plan" / "research-plan.json"
    tex_path = tmp_path / "outputs" / "project_1" / "research-plan" / "research-plan.tex"

    assert result.exit_code == 0, result.output
    assert "[OK] research_plan: passed" in result.stdout
    assert "[OK] compile_status: skipped" in result.stdout
    assert markdown_path.is_file()
    assert json_path.is_file()
    assert tex_path.is_file()
    assert "entry_type: research_plan" in markdown_path.read_text(encoding="utf-8")
    assert "AI-Researcher system proposal" not in tex_path.read_text(encoding="utf-8")


def test_research_plan_audit_blocks_forbidden_title(tmp_path: Path) -> None:
    plan = ResearchPlan(
        project_id="project_1",
        candidate_id="candidate_1",
        title="AI-Researcher system",
        problem_statement="A source-backed gap needs a concrete plan.",
        rationale="XH-202619 参赛方案 should never enter a normal research plan.",
        technical_details="Use a baseline, macro_f1 metric, and source dataset.",
        datasets={"source": "UCI Pendigits", "target": "hold-out split"},
        methods="Compare the method with a baseline using macro_f1 metric.",
        experiments=["Run baseline.", "Run method.", "Run ablation."],
        expected_results="Expected, not yet observed: metric changes require real runs.",
        code_agent_brief="Run python scripts/run_experiment.py and save metrics.json.",
        risks_and_alternatives=["Baseline may fail.", "Dataset license may block use."],
        references=["https://example.org/source-paper"],
        evidence_refs=["https://example.org/source-paper"],
    )
    plan_path = tmp_path / "research-plan.json"
    plan_path.write_text(json.dumps({"plan": plan.model_dump(mode="json")}), encoding="utf-8")

    result = CliRunner().invoke(app, ["research-plan-audit", str(plan_path)])

    assert result.exit_code == 1
    assert "[OK] research_plan_audit: failed" in result.stdout
    assert "title must be a discovered research topic" in result.stdout
    assert "forbidden contest" in result.stdout


def test_run_demo_command_creates_end_to_end_outputs(tmp_path: Path) -> None:
    output_dir = tmp_path / "mvp-demo"

    result = CliRunner().invoke(
        app,
        [
            "run-demo",
            "--demo",
            "tabular_baseline",
            "--output-dir",
            str(output_dir),
            "--timeout-seconds",
            "5",
        ],
    )

    experiment_dir = output_dir / "tabular-baseline"
    evidence_map_path = experiment_dir / "evidence" / "evidence-map.json"
    report_path = experiment_dir / "report" / "report.md"

    assert result.exit_code == 0
    assert "[OK] demo: tabular_baseline" in result.stdout
    assert (experiment_dir / "run.py").is_file()
    assert (experiment_dir / "logs" / "run.log").is_file()
    assert (experiment_dir / "metrics.json").is_file()
    assert (experiment_dir / "validation" / "validation-report.json").is_file()
    assert (experiment_dir / "validation" / "validation-report.md").is_file()
    assert evidence_map_path.is_file()
    assert report_path.is_file()

    evidence_map = json.loads(evidence_map_path.read_text(encoding="utf-8"))
    report = report_path.read_text(encoding="utf-8")
    assert evidence_map["task_id"] == "tabular_baseline"
    assert evidence_map["evidence_edges"]
    assert "## Reproducibility" in report
    assert "## Results" in report


def test_autopilot_pendigits_demo_uses_method_aligned_search_contract() -> None:
    seeds = cli_main._autopilot_literature_seed_queries(
        "pendigits_variance_calibrated_prototypes"
    )
    assert len(seeds) == cli_main.PUBLICATION_SEARCH_QUERIES
    assert any("Pendigits" in seed for seed in seeds)
    assert any("prototype" in seed for seed in seeds)

    seed_document = SimpleNamespace(
        id="doc_seed",
        title="A Source Paper",
        source_uri="https://example.test/source",
    )
    candidate = cli_main._autopilot_candidate_from_literature(
        SimpleNamespace(documents=(seed_document,)),
        project_id="project_1",
        demo="pendigits_variance_calibrated_prototypes",
        now=datetime(2026, 6, 13, 2, 30, tzinfo=timezone.utc),
    )

    assert candidate.title == "Variance-calibrated prototype classifiers for UCI Pendigits"
    assert candidate.metadata["demo"] == "pendigits_variance_calibrated_prototypes"
    assert candidate.metadata["dataset"] == "UCI Pen-Based Recognition of Handwritten Digits"
    assert "variance-calibrated prototypes" in candidate.metadata["method"]
    assert "nearest centroid" in candidate.metadata["baseline"]
    assert "Gaussian" in candidate.metadata["limitation"]


def test_autopilot_skin_demo_uses_method_aligned_search_contract() -> None:
    seeds = cli_main._autopilot_literature_seed_queries(
        "skin_variance_calibrated_prototypes"
    )
    assert len(seeds) == cli_main.PUBLICATION_SEARCH_QUERIES
    assert any("Skin Segmentation" in seed for seed in seeds)
    assert any("Gaussian" in seed for seed in seeds)

    seed_document = SimpleNamespace(
        id="doc_seed",
        title="A Source Paper",
        source_uri="https://example.test/source",
    )
    candidate = cli_main._autopilot_candidate_from_literature(
        SimpleNamespace(documents=(seed_document,)),
        project_id="project_1",
        demo="skin_variance_calibrated_prototypes",
        now=datetime(2026, 6, 13, 2, 30, tzinfo=timezone.utc),
    )

    assert candidate.title == "Variance-calibrated prototype classifiers for UCI Skin Segmentation"
    assert candidate.metadata["demo"] == "skin_variance_calibrated_prototypes"
    assert candidate.metadata["dataset"] == "UCI Skin Segmentation"
    assert "variance-calibrated prototypes" in candidate.metadata["method"]
    assert "RGB color" in candidate.metadata["baseline"]
    assert "skin-color" in candidate.metadata["limitation"]


def test_autopilot_literature_clients_share_persistent_circuit_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTORESEARCH_ENABLE_SEMANTIC_SCHOLAR", "1")
    clients = cli_main._autopilot_literature_clients(tmp_path / "cache")

    semantic = clients["semantic_scholar"]
    openalex = clients["openalex"]

    assert semantic.circuit_breaker.state_path == tmp_path / "cache" / "source-circuit-breakers.json"
    assert semantic.circuit_breaker.state_key == "semantic_scholar"
    assert openalex.circuit_breaker.state_path == tmp_path / "cache" / "source-circuit-breakers.json"
    assert openalex.circuit_breaker.state_key == "openalex"


def test_autopilot_literature_clients_default_to_core_free_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AUTORESEARCH_ENABLE_SEMANTIC_SCHOLAR", raising=False)
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)

    clients = cli_main._autopilot_literature_clients(tmp_path / "cache")

    assert list(clients) == ["arxiv", "openalex"]
    assert clients["openalex"].circuit_breaker.state_path == (
        tmp_path / "cache" / "source-circuit-breakers.json"
    )


def test_autopilot_command_runs_one_non_review_cycle(tmp_path: Path, monkeypatch) -> None:
    literature_summary = tmp_path / "vault" / "exploration" / "literature.md"
    similarity_summary = tmp_path / "vault" / "exploration" / "similarity.md"
    inspiration_summary = tmp_path / "vault" / "exploration" / "inspiration.md"
    project_similarity = tmp_path / "vault" / "projects" / "project_1" / "knowledge" / "similarity.md"
    for path in (literature_summary, similarity_summary, inspiration_summary, project_similarity):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("summary", encoding="utf-8")

    seed_document = SimpleNamespace(
        id="doc_seed",
        title="Evidence Graphs for Autonomous Research",
        source_uri="https://example.test/paper",
        authors=["A. Researcher"],
        abstract="Evidence graphs connect autonomous research claims to local validation artifacts.",
        publication_date=datetime(2026, 6, 13, tzinfo=timezone.utc),
        venue="ExampleConf",
        doi="10.1234/example",
        tags=["evidence-graph", "autonomous-research"],
    )
    fetch = SimpleNamespace(
        source="semantic_scholar",
        query="evidence graph autonomous research",
        paper_count=1,
        cache_hit=False,
        rate_limit_seconds=3.0,
        error=None,
    )
    shared_clients = {
        "arxiv": object(),
        "semantic_scholar": object(),
        "openalex": object(),
    }

    def fake_literature_refresh(**kwargs: object) -> SimpleNamespace:
        config = kwargs["config"]
        assert kwargs["clients"] is shared_clients
        assert config.max_queries == cli_main.PUBLICATION_SEARCH_QUERIES
        assert config.max_results_per_source == cli_main.PUBLICATION_RESULTS_PER_SOURCE
        assert len(config.seed_queries) == cli_main.PUBLICATION_SEARCH_QUERIES
        return SimpleNamespace(
            queries=(SimpleNamespace(text="evidence graph autonomous research"),),
            fetches=(fetch,),
            documents=(seed_document,),
            summary_path=literature_summary,
        )

    def fake_similarity_check(**kwargs: object) -> SimpleNamespace:
        config = kwargs["config"]
        assert kwargs["clients"] is shared_clients
        assert config.max_queries == cli_main.PUBLICATION_SEARCH_QUERIES
        assert config.max_results_per_source == cli_main.PUBLICATION_RESULTS_PER_SOURCE
        return SimpleNamespace(
            fetches=(fetch,),
            findings=(SimpleNamespace(source_uri="https://example.test/paper"),),
            summary_path=similarity_summary,
        )

    def fake_link_similarity_report_to_project(**_kwargs: object) -> Path:
        return project_similarity

    call_order: list[str] = []

    def fake_generate_research_plan(**kwargs: object) -> SimpleNamespace:
        call_order.append("research_plan")
        assert kwargs["project_id"] == "project_1"
        assert kwargs["vault_root"] == tmp_path / "vault"
        assert Path(kwargs["similarity_summary"]) == similarity_summary
        assert Path(kwargs["literature_summary"]) == literature_summary
        plan_dir = Path(kwargs["output_dir"]) / "project_1" / "research-plan"
        plan_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = plan_dir / "research-plan.md"
        json_path = plan_dir / "research-plan.json"
        tex_path = plan_dir / "research-plan.tex"
        pdf_path = plan_dir / "research-plan.pdf"
        markdown_path.write_text("# Plan\n", encoding="utf-8")
        json_path.write_text("{}", encoding="utf-8")
        tex_path.write_text(
            "\\documentclass{article}\\begin{document}Plan\\end{document}\n",
            encoding="utf-8",
        )
        pdf_path.write_text("%PDF-1.4\n", encoding="utf-8")
        payload = {
            "audit": {
                "verdict": "passed",
                "passed": True,
                "score": 1.0,
                "issues": [],
                "warnings": [],
            },
            "markdown_path": markdown_path.as_posix(),
            "json_path": json_path.as_posix(),
            "tex_path": tex_path.as_posix(),
            "pdf_path": pdf_path.as_posix(),
            "compile_status": "compiled",
            "page_count": 2,
        }
        return SimpleNamespace(
            audit=SimpleNamespace(passed=True),
            compile_status="compiled",
            to_dict=lambda: payload,
        )

    def fake_inspiration_refresh(**kwargs: object) -> InspirationRefreshReport:
        assert call_order == ["research_plan"]
        config = kwargs["config"]
        queries = tuple(kwargs["queries"])
        assert config.max_queries == cli_main.PUBLICATION_SEARCH_QUERIES
        assert config.max_results_per_source == cli_main.PUBLICATION_RESULTS_PER_SOURCE
        assert any("Evidence-bound self-evolving research" in query for query in queries)
        return InspirationRefreshReport(
            queries=queries[:1],
            fetches=(
                InspirationFetchRecord(
                    source="huggingface_datasets",
                    source_type="dataset_signal",
                    query=queries[0],
                    result_count=1,
                    rate_limit_seconds=1.0,
                ),
            ),
            items=(
                InspirationItem(
                    source="huggingface_datasets",
                    source_type="dataset_signal",
                    title="example/research-dataset",
                    url="https://huggingface.co/datasets/example/research-dataset",
                    query=queries[0],
                    summary="Dataset signal only.",
                    score=1.0,
                    retrieved_at=datetime.now(timezone.utc),
                ),
            ),
            summary_path=inspiration_summary,
        )

    def fake_demo(**kwargs: object) -> SimpleNamespace:
        assert call_order == ["research_plan"]
        output_dir = Path(kwargs["output_dir"])
        experiment_dir = output_dir / "tabular-baseline"
        report_path = experiment_dir / "report" / "report.md"
        validation_path = experiment_dir / "validation" / "validation-report.json"
        evidence_path = experiment_dir / "evidence" / "evidence-map.json"
        run_record_path = experiment_dir / "run" / "run-record.json"
        for path in (report_path, validation_path, evidence_path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")
        run_record_path.parent.mkdir(parents=True, exist_ok=True)
        run_record_path.write_text(
            json.dumps(
                {
                    "metrics": {
                        "values": {
                            "accuracy": 0.82,
                            "baseline_accuracy": 0.78,
                            "accuracy_delta_vs_baseline": 0.04,
                            "feature_count": 12.0,
                            "variance_shrinkage": 1.0,
                        }
                    },
                    "task_metadata": {
                        "proposed_method": "evidence graph verifier",
                        "dataset": "Example benchmark",
                        "baseline": "local baseline",
                        "split_policy": "deterministic split",
                        "feature_count": 12,
                    },
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(
            demo="tabular_baseline",
            experiment_dir=experiment_dir,
            report_path=report_path,
            evidence_map_path=evidence_path,
            run_record_path=run_record_path,
            validation_json_path=validation_path,
            validation_markdown_path=experiment_dir / "validation" / "validation-report.md",
            run_id="run_autopilot_test",
        )

    def fake_publication_audit(**_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            to_dict=lambda: {
                "verdict": "needs_revision",
                "publishable": False,
                "score": 0.5,
                "output_path": str(output_dir / "cycle-test" / "publication-audit.json"),
            }
        )

    def fake_compose_manuscript(**kwargs: object) -> SimpleNamespace:
        assert Path(kwargs["cycle_summary_path"]).name == "cycle-summary.json"
        output_path = Path(kwargs["output_dir"]) / "manuscript.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        analysis_dir = output_path.parent / "analysis"
        analysis_dir.mkdir()
        metrics_source = analysis_dir / "metrics-source.json"
        figure_png = analysis_dir / "validated-performance-metrics.png"
        figure_metadata = analysis_dir / "validated-performance-metrics.metadata.json"
        data_table = analysis_dir / "data-analysis-summary.md"
        metrics_source.write_text('{"metrics": {"accuracy": 0.9}}', encoding="utf-8")
        figure_png.write_bytes(b"\x89PNG\r\n\x1a\n")
        figure_metadata.write_text('{"figure_type": "metric_bar"}', encoding="utf-8")
        data_table.write_text("| Metric | Value |\n| --- | ---: |\n| Accuracy | 0.9 |\n", encoding="utf-8")
        output_path.write_text(
            "\n".join(
                [
                    "# Manuscript",
                    "",
                    "## Abstract",
                    "",
                    "Evidence.",
                    "",
                    "## References",
                    "",
                    (
                        "- [researcher2026] Evidence graphs for autonomous research. "
                        "DOI/URL evidence: 10.1234/example."
                    ),
                    (
                        "- [Citation package note] 2 additional verified record(s) remain in "
                        "citation metadata but were omitted from formal references because "
                        "their direct method or benchmark support was weaker."
                    ),
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(
            markdown_path=output_path.as_posix(),
            analysis_artifact_paths=(
                metrics_source.as_posix(),
                figure_png.as_posix(),
                figure_metadata.as_posix(),
                data_table.as_posix(),
            ),
            to_dict=lambda: {
                "markdown_path": output_path.as_posix(),
                "word_count": 2600,
                "section_word_counts": {"Abstract": 100},
                "analysis_artifact_paths": [
                    metrics_source.as_posix(),
                    figure_png.as_posix(),
                    figure_metadata.as_posix(),
                    data_table.as_posix(),
                ],
            },
        )

    def fake_paper_build(**kwargs: object) -> SimpleNamespace:
        assert Path(kwargs["markdown_path"]).name == "manuscript.md"
        assert Path(kwargs["output_dir"]).name == "paper-build"
        assert kwargs["template_id"] == "generic-article-two-column"
        output_path = Path(kwargs["output_dir"])
        output_path.mkdir(parents=True, exist_ok=True)
        for name, content in (
            ("paper-build.json", "{}"),
            ("paper-build.md", "# Build\n"),
            ("main.tex", "\\documentclass{article}\\begin{document}x\\end{document}\n"),
            ("main.pdf", "%PDF-1.4\n"),
        ):
            (output_path / name).write_text(content, encoding="utf-8")
        return SimpleNamespace(
            to_dict=lambda: {
                "status": "compiled",
                "json_path": str(output_path / "paper-build.json"),
                "markdown_path": str(output_path / "paper-build.md"),
                "tex_path": str(output_path / "main.tex"),
                "pdf_path": str(output_path / "main.pdf"),
            }
        )

    def fake_reproduction_check(**kwargs: object) -> dict[str, object]:
        assert kwargs["demo"] == "tabular_baseline"
        check_dir = Path(kwargs["cycle_dir"]) / "reproduction-check"
        run_record_path = check_dir / "rerun" / "tabular-baseline" / "run" / "run-record.json"
        validation_path = (
            check_dir
            / "rerun"
            / "tabular-baseline"
            / "validation"
            / "validation-report.json"
        )
        report_path = check_dir / "reproduction-check.json"
        markdown_path = check_dir / "reproduction-check.md"
        for path in (run_record_path, validation_path, report_path, markdown_path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")
        return {
            "status": "passed",
            "exit_code": 0,
            "json_path": report_path.as_posix(),
            "markdown_path": markdown_path.as_posix(),
            "run_record_paths": [run_record_path.as_posix()],
            "validation_json_paths": [validation_path.as_posix()],
        }

    def fake_evidence_gate(**kwargs: object) -> SimpleNamespace:
        assert Path(kwargs["cycle_summary_path"]).name == "cycle-summary.json"
        assert Path(kwargs["output_dir"]).name == "evidence-gate"
        return SimpleNamespace(
            to_dict=lambda: {
                "verdict": "blocked",
                "release_allowed": False,
                "output_path": str(Path(kwargs["output_dir"]) / "evidence-gate.json"),
            }
        )

    review_calls: list[dict[str, object]] = []

    def fake_autopilot_review(**kwargs: object) -> dict[str, object]:
        review_calls.append(dict(kwargs))
        assert kwargs["enabled"] is False
        assert Path(kwargs["report_path"]).name == "manuscript.md"
        evidence_names = {Path(path).name for path in kwargs["evidence_paths"]}
        assert {
            "cycle-summary.json",
            "review-evidence-context.json",
            "formal-reference-evidence.md",
            "report.md",
            "run-record.json",
            "validation-report.json",
            "references.metadata.json",
            "references.bib",
            "related-work-inspection.json",
            "related-work-inspection.md",
            "research-plan.json",
            "research-plan.md",
            "research-plan.tex",
            "paper-build.json",
            "metrics-source.json",
            "validated-performance-metrics.metadata.json",
            "data-analysis-summary.md",
        } <= evidence_names
        assert "validated-performance-metrics.png" not in evidence_names
        return {"status": "skipped"}

    monkeypatch.setattr(cli_main, "run_daily_literature_refresh", fake_literature_refresh)
    monkeypatch.setattr(cli_main, "run_project_similarity_check", fake_similarity_check)
    monkeypatch.setattr(cli_main, "generate_research_plan", fake_generate_research_plan)
    monkeypatch.setattr(cli_main, "run_inspiration_refresh", fake_inspiration_refresh)
    monkeypatch.setattr(cli_main, "_autopilot_literature_clients", lambda _cache: shared_clients)
    monkeypatch.setattr(cli_main, "link_similarity_report_to_project", fake_link_similarity_report_to_project)
    monkeypatch.setattr(cli_main, "run_scientistbench_demo", fake_demo)
    monkeypatch.setattr(cli_main, "compose_publication_manuscript", fake_compose_manuscript)
    monkeypatch.setattr(cli_main, "audit_publication_quality", fake_publication_audit)
    monkeypatch.setattr(cli_main, "build_latex_paper_from_markdown", fake_paper_build)
    monkeypatch.setattr(cli_main, "_run_cycle_reproduction_check", fake_reproduction_check)
    monkeypatch.setattr(cli_main, "run_evidence_gate", fake_evidence_gate)
    monkeypatch.setattr(cli_main, "_run_autopilot_review", fake_autopilot_review)

    output_dir = tmp_path / "runs" / "autopilot"
    deliverables_dir = tmp_path / "outputs"
    state = tmp_path / ".airesearcher" / "scheduler-state.json"
    result = CliRunner().invoke(
        app,
        [
            "autopilot",
            "--vault",
            str(tmp_path / "vault"),
            "--cache",
            str(tmp_path / "cache"),
            "--output-dir",
            str(output_dir),
            "--deliverables-dir",
            str(deliverables_dir),
            "--state",
            str(state),
            "--project-id",
            "project_1",
            "--paper-template-id",
            "generic-article-two-column",
            "--no-review",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "[OK] autopilot_cycle:" in result.stdout
    assert "[OK] research_plan: passed" in result.stdout
    assert "[OK] review_status: skipped" in result.stdout
    assert "[OK] publication_audit: needs_revision" in result.stdout
    assert "[OK] evidence_gate: blocked" in result.stdout
    summaries = list(output_dir.glob("cycle-*/cycle-summary.json"))
    assert len(summaries) == 1
    payload = json.loads(summaries[0].read_text(encoding="utf-8"))
    assert payload["candidate"]["related_document_ids"] == ["doc_seed"]
    assert payload["source_preflight"]["verdict"] == "pass"
    assert payload["literature"]["document_count"] == 1
    assert payload["citations"]["status"] == "generated"
    assert payload["citations"]["verified_count"] == 1
    assert Path(payload["citations"]["metadata_path"]).name == "references.metadata.json"
    assert Path(payload["citations"]["bib_path"]).name == "references.bib"
    assert Path(payload["related_work_inspection"]["json_path"]).name == (
        "related-work-inspection.json"
    )
    assert payload["related_work_inspection"]["inspected_count"] == 1
    assert payload["related_work_inspection"]["source_backed_count"] == 1
    citation_metadata = json.loads(
        Path(payload["citations"]["metadata_path"]).read_text(encoding="utf-8")
    )
    assert citation_metadata["citations"][0]["abstract"].startswith("Evidence graphs")
    assert citation_metadata["citations"][0]["tags"] == [
        "evidence-graph",
        "autonomous-research",
    ]
    assert payload["similarity"]["finding_count"] == 1
    assert payload["research_plan"]["audit"]["passed"] is True
    assert payload["research_plan"]["compile_status"] == "compiled"
    assert payload["research_plan"]["page_count"] == 2
    assert payload["inspiration"]["item_count"] == 1
    assert payload["inspiration"]["pushes"] == []
    assert payload["inspiration"]["evidence_policy"] == (
        "dataset/community/news signals only; not scholarly evidence"
    )
    assert payload["demo"]["run_id"] == "run_autopilot_test"
    assert Path(payload["review_context_path"]).name == "review-evidence-context.json"
    assert Path(payload["formal_reference_evidence_path"]).name == "formal-reference-evidence.md"
    formal_reference_note = Path(payload["formal_reference_evidence_path"]).read_text(
        encoding="utf-8"
    )
    assert "`researcher2026`" in formal_reference_note
    assert "all_displayed_keys_present" in formal_reference_note
    review_context = json.loads(
        Path(payload["review_context_path"]).read_text(encoding="utf-8")
    )
    assert review_context["audit_summary"]["reproduction_check"]["status"] == "passed"
    assert review_context["audit_summary"]["paper_build"]["status"] == "compiled"
    assert review_context["audit_summary"]["research_plan"]["passed"] is True
    assert review_context["audit_summary"]["research_plan"]["compile_status"] == "compiled"
    candidate_summary = review_context["audit_summary"]["candidate"]
    assert candidate_summary["title"].startswith("Evidence-bound self-evolving research loop")
    assert "durable evidence memory" in candidate_summary["research_gap"]
    assert candidate_summary["metadata"]["method"] == "evidence-bound autonomous research loop"
    assert candidate_summary["task_metadata"]["proposed_method"] == "evidence graph verifier"
    assert candidate_summary["recorded_metrics"]["feature_count"] == 12.0
    assert candidate_summary["recorded_metrics"]["variance_shrinkage"] == 1.0
    assert review_context["audit_summary"]["citations"]["additional_verified_record_count"] == 2
    assert review_context["audit_summary"]["related_work_inspection"]["inspected_count"] == 1
    assert review_context["audit_summary"]["related_work_inspection"]["source_backed_count"] == 1
    formal_references = review_context["audit_summary"]["citations"]["formal_references"]
    assert formal_references["displayed_count"] == 1
    assert formal_references["citation_metadata_key_count"] == 1
    assert formal_references["citation_metadata_keys"] == ["researcher2026"]
    assert formal_references["citation_metadata_status"] == "all_displayed_keys_present"
    assert formal_references["omitted_verified_count"] == 2
    assert formal_references["displayed_references"][0]["key"] == "researcher2026"
    assert formal_references["displayed_references"][0]["citation_metadata_status"] == (
        "verified_doi"
    )
    assert (
        "Evidence graphs for autonomous research"
        in formal_references["displayed_references"][0]["title"]
    )
    assert Path(payload["paper_manuscript"]["markdown_path"]).name == "manuscript.md"
    assert payload["publication_audit"]["verdict"] == "needs_revision"
    assert payload["paper_build"]["status"] == "compiled"
    assert payload["deliverables"]["pdf_path"].endswith(".pdf")
    assert Path(payload["deliverables"]["paths"]["paper_pdf"]).is_file()
    assert Path(payload["deliverables"]["manifest_path"]).is_file()
    deliverables_manifest = json.loads(
        Path(payload["deliverables"]["manifest_path"]).read_text(encoding="utf-8")
    )
    assert deliverables_manifest["paths"]["paper_pdf"].endswith(".pdf")
    assert deliverables_manifest["paths"]["research_plan_pdf"].endswith("-research-plan.pdf")
    assert deliverables_manifest["paths"]["research_plan_json"].endswith("-research-plan.json")
    assert payload["reproduction_check"]["status"] == "passed"
    assert payload["evidence_gate"]["verdict"] == "blocked"
    assert json.loads(state.read_text(encoding="utf-8")) == {"tasks": []}
    assert len(review_calls) == 1


def test_autopilot_research_plan_gate_blocks_before_experiment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    literature_summary = tmp_path / "vault" / "exploration" / "literature.md"
    similarity_summary = tmp_path / "vault" / "exploration" / "similarity.md"
    project_similarity = tmp_path / "vault" / "projects" / "project_1" / "knowledge" / "similarity.md"
    for path in (literature_summary, similarity_summary, project_similarity):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("summary", encoding="utf-8")

    seed_document = SimpleNamespace(
        id="doc_seed",
        title="Evidence Graphs for Autonomous Research",
        source_uri="https://example.test/paper",
        authors=["A. Researcher"],
        abstract="Evidence graphs connect claims to validation artifacts.",
        publication_date=datetime(2026, 6, 13, tzinfo=timezone.utc),
        venue="ExampleConf",
        doi="10.1234/example",
        tags=["evidence-graph"],
    )
    fetch = SimpleNamespace(
        source="openalex",
        query="evidence graph autonomous research",
        paper_count=1,
        cache_hit=False,
        error=None,
    )
    shared_clients = {"arxiv": object(), "openalex": object()}

    def fake_literature_refresh(**_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            queries=(SimpleNamespace(text="evidence graph autonomous research"),),
            fetches=(fetch,),
            documents=(seed_document,),
            summary_path=literature_summary,
        )

    def fake_similarity_check(**_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            fetches=(fetch,),
            findings=(SimpleNamespace(source_uri="https://example.test/paper"),),
            summary_path=similarity_summary,
        )

    def fake_generate_research_plan(**kwargs: object) -> SimpleNamespace:
        plan_dir = Path(kwargs["output_dir"]) / "project_1" / "research-plan"
        plan_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = plan_dir / "research-plan.md"
        json_path = plan_dir / "research-plan.json"
        tex_path = plan_dir / "research-plan.tex"
        for path in (markdown_path, json_path, tex_path):
            path.write_text("blocked", encoding="utf-8")
        payload = {
            "audit": {
                "verdict": "failed",
                "passed": False,
                "score": 0.4,
                "issues": ["title must be a discovered research topic"],
                "warnings": [],
            },
            "markdown_path": markdown_path.as_posix(),
            "json_path": json_path.as_posix(),
            "tex_path": tex_path.as_posix(),
            "pdf_path": None,
            "compile_status": "skipped_quality_gate",
            "compile_reason": "research-plan audit did not pass",
            "page_count": None,
        }
        return SimpleNamespace(
            audit=SimpleNamespace(passed=False),
            compile_status="skipped_quality_gate",
            to_dict=lambda: payload,
        )

    def fail_if_called(**_kwargs: object) -> object:
        raise AssertionError("research-plan-blocked cycle should not run later stages")

    monkeypatch.setattr(cli_main, "_autopilot_literature_clients", lambda _cache: shared_clients)
    monkeypatch.setattr(cli_main, "run_daily_literature_refresh", fake_literature_refresh)
    monkeypatch.setattr(cli_main, "run_project_similarity_check", fake_similarity_check)
    monkeypatch.setattr(cli_main, "link_similarity_report_to_project", lambda **_kwargs: project_similarity)
    monkeypatch.setattr(cli_main, "generate_research_plan", fake_generate_research_plan)
    monkeypatch.setattr(cli_main, "run_inspiration_refresh", fail_if_called)
    monkeypatch.setattr(cli_main, "run_scientistbench_demo", fail_if_called)
    monkeypatch.setattr(cli_main, "compose_publication_manuscript", fail_if_called)

    output_dir = tmp_path / "runs" / "autopilot"
    state = tmp_path / ".airesearcher" / "scheduler-state.json"
    result = CliRunner().invoke(
        app,
        [
            "autopilot",
            "--vault",
            str(tmp_path / "vault"),
            "--cache",
            str(tmp_path / "cache"),
            "--output-dir",
            str(output_dir),
            "--state",
            str(state),
            "--project-id",
            "project_1",
            "--no-review",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "[BLOCKED] research_plan: failed" in result.stdout
    assert "[OK] review_status: skipped_research_plan_gate" in result.stdout
    summaries = list(output_dir.glob("cycle-*/cycle-summary.json"))
    assert len(summaries) == 1
    payload = json.loads(summaries[0].read_text(encoding="utf-8"))
    assert payload["status"] == "blocked"
    assert payload["blocked_reason"] == "research_plan_gate"
    assert payload["research_plan"]["audit"]["passed"] is False
    assert payload["research_plan"]["compile_status"] == "skipped_quality_gate"
    assert payload["review"]["status"] == "skipped_research_plan_gate"
    assert "inspiration" not in payload
    assert "demo" not in payload
    assert json.loads(state.read_text(encoding="utf-8")) == {"tasks": []}


def test_autopilot_reference_locator_keeps_full_dotted_doi() -> None:
    _title, locator = cli_main._autopilot_reference_title_and_locator(
        "Metrics and models for handwritten character recognition. "
        "doi:10.1214/ss/1028905973. source URL recorded in artifact."
    )

    assert locator == "doi:10.1214/ss/1028905973"


def test_autopilot_source_preflight_blocks_cooling_source(tmp_path: Path, monkeypatch) -> None:
    cache_root = tmp_path / "cache"
    state_path = cache_root / "source-circuit-breakers.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)

    cooling_breaker = SimpleNamespace(
        remaining_seconds=lambda: 180.0,
        state_path=state_path,
    )
    shared_clients = {
        "arxiv": object(),
        "semantic_scholar": object(),
        "openalex": SimpleNamespace(circuit_breaker=cooling_breaker),
    }

    def fail_if_called(**_kwargs: object) -> SimpleNamespace:
        raise AssertionError("preflight-blocked cycle should not run costly work")

    monkeypatch.setattr(cli_main, "_autopilot_literature_clients", lambda _cache: shared_clients)
    monkeypatch.setattr(cli_main, "run_daily_literature_refresh", fail_if_called)
    monkeypatch.setattr(cli_main, "run_scientistbench_demo", fail_if_called)

    output_dir = tmp_path / "runs" / "autopilot"
    scheduler_state = tmp_path / ".airesearcher" / "scheduler-state.json"
    result = CliRunner().invoke(
        app,
        [
            "autopilot",
            "--vault",
            str(tmp_path / "vault"),
            "--cache",
            str(cache_root),
            "--output-dir",
            str(output_dir),
            "--state",
            str(scheduler_state),
            "--project-id",
            "project_1",
            "--no-review",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "[BLOCKED] source_preflight: blocked" in result.stdout
    assert "[OK] review_status: skipped_source_preflight" in result.stdout

    summaries = list(output_dir.glob("cycle-*/cycle-summary.json"))
    assert len(summaries) == 1
    payload = json.loads(summaries[0].read_text(encoding="utf-8"))
    assert payload["status"] == "blocked"
    assert payload["source_preflight"]["verdict"] == "blocked"
    assert payload["source_preflight"]["blocked_sources"] == ["openalex"]
    assert payload["review"]["status"] == "skipped_source_preflight"
    assert Path(payload["source_preflight"]["output_path"]).exists()
    assert Path(payload["source_preflight"]["markdown_path"]).exists()
    issue_path = Path(payload["source_preflight"]["issue_path"])
    assert issue_path.exists()
    assert "Source Preflight Blocker" in issue_path.read_text(encoding="utf-8")
    scheduler_payload = json.loads(scheduler_state.read_text(encoding="utf-8"))
    assert len(scheduler_payload["tasks"]) == 1
    assert "source-preflight" in scheduler_payload["tasks"][0]["task_id"]


def test_autopilot_source_preflight_blocks_malformed_state_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cache_root = tmp_path / "cache"
    state_path = cache_root / "source-circuit-breakers.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("{not-json", encoding="utf-8")

    breaker = SimpleNamespace(
        remaining_seconds=lambda: 0.0,
        state_path=state_path,
    )
    shared_clients = {
        "arxiv": object(),
        "semantic_scholar": object(),
        "openalex": SimpleNamespace(circuit_breaker=breaker),
    }

    def fail_if_called(**_kwargs: object) -> SimpleNamespace:
        raise AssertionError("state-error cycle should not run costly work")

    monkeypatch.setattr(cli_main, "_autopilot_literature_clients", lambda _cache: shared_clients)
    monkeypatch.setattr(cli_main, "run_daily_literature_refresh", fail_if_called)
    monkeypatch.setattr(cli_main, "run_scientistbench_demo", fail_if_called)

    output_dir = tmp_path / "runs" / "autopilot"
    result = CliRunner().invoke(
        app,
        [
            "autopilot",
            "--vault",
            str(tmp_path / "vault"),
            "--cache",
            str(cache_root),
            "--output-dir",
            str(output_dir),
            "--state",
            str(tmp_path / ".airesearcher" / "scheduler-state.json"),
            "--project-id",
            "project_1",
            "--no-review",
        ],
    )

    assert result.exit_code == 0, result.output
    summaries = list(output_dir.glob("cycle-*/cycle-summary.json"))
    assert len(summaries) == 1
    payload = json.loads(summaries[0].read_text(encoding="utf-8"))
    assert payload["status"] == "blocked"
    assert payload["source_preflight"]["blocked_sources"] == ["openalex"]
    openalex_check = [
        check
        for check in payload["source_preflight"]["checks"]
        if check["source"] == "openalex"
    ][0]
    assert openalex_check["status"] == "state_error"
    assert "unreadable" in openalex_check["message"]
    issue_text = Path(payload["source_preflight"]["issue_path"]).read_text(encoding="utf-8")
    assert "83.1" in issue_text


def test_autopilot_source_preflight_blocks_locked_state_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cache_root = tmp_path / "cache"
    state_path = cache_root / "source-circuit-breakers.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("{}", encoding="utf-8")
    lock_path = state_path.with_name(f"{state_path.name}.lock")
    lock_path.write_text("active lock", encoding="utf-8")

    breaker = SimpleNamespace(
        remaining_seconds=lambda: 0.0,
        state_path=state_path,
        state_stale_lock_seconds=300.0,
    )
    shared_clients = {
        "arxiv": object(),
        "semantic_scholar": object(),
        "openalex": SimpleNamespace(circuit_breaker=breaker),
    }

    def fail_if_called(**_kwargs: object) -> SimpleNamespace:
        raise AssertionError("state-locked cycle should not run costly work")

    monkeypatch.setattr(cli_main, "_autopilot_literature_clients", lambda _cache: shared_clients)
    monkeypatch.setattr(cli_main, "run_daily_literature_refresh", fail_if_called)
    monkeypatch.setattr(cli_main, "run_scientistbench_demo", fail_if_called)

    output_dir = tmp_path / "runs" / "autopilot"
    result = CliRunner().invoke(
        app,
        [
            "autopilot",
            "--vault",
            str(tmp_path / "vault"),
            "--cache",
            str(cache_root),
            "--output-dir",
            str(output_dir),
            "--state",
            str(tmp_path / ".airesearcher" / "scheduler-state.json"),
            "--project-id",
            "project_1",
            "--no-review",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "[BLOCKED] source_preflight: blocked" in result.stdout
    summaries = list(output_dir.glob("cycle-*/cycle-summary.json"))
    assert len(summaries) == 1
    payload = json.loads(summaries[0].read_text(encoding="utf-8"))
    openalex_check = [
        check
        for check in payload["source_preflight"]["checks"]
        if check["source"] == "openalex"
    ][0]
    assert openalex_check["status"] == "state_locked"
    assert "locked" in openalex_check["message"]
    issue_text = Path(payload["source_preflight"]["issue_path"]).read_text(encoding="utf-8")
    assert "85.1" in issue_text


def test_source_preflight_records_optional_semantic_scholar_degradation(
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "cache"
    state_path = cache_root / "source-circuit-breakers.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    cooling_breaker = SimpleNamespace(
        remaining_seconds=lambda: 120.0,
        state_path=state_path,
    )
    cycle_dir = tmp_path / "cycle"
    cycle_dir.mkdir()

    report = cli_main._run_source_preflight_gate(
        clients={
            "arxiv": object(),
            "openalex": object(),
            "semantic_scholar": SimpleNamespace(circuit_breaker=cooling_breaker),
        },
        cycle_dir=cycle_dir,
        vault=tmp_path / "vault",
        project_id="project_1",
        cycle_id="cycle_optional",
    )

    assert report["verdict"] == "pass"
    assert report["blocked_sources"] == []
    assert report["optional_degraded_sources"] == ["semantic_scholar"]
    assert report["issue_path"] is None
    markdown = Path(report["markdown_path"]).read_text(encoding="utf-8")
    assert "Optional enhancement sources" in markdown


def test_autopilot_command_reports_empty_literature_result(tmp_path: Path, monkeypatch) -> None:
    literature_summary = tmp_path / "vault" / "exploration" / "literature.md"
    literature_summary.parent.mkdir(parents=True, exist_ok=True)
    literature_summary.write_text("summary", encoding="utf-8")

    def fake_literature_refresh(**_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            queries=(SimpleNamespace(text="evidence graph autonomous research"),),
            fetches=(),
            documents=(),
            summary_path=literature_summary,
        )

    monkeypatch.setattr(cli_main, "run_daily_literature_refresh", fake_literature_refresh)

    result = CliRunner().invoke(
        app,
        [
            "autopilot",
            "--vault",
            str(tmp_path / "vault"),
            "--cache",
            str(tmp_path / "cache"),
            "--output-dir",
            str(tmp_path / "runs" / "autopilot"),
            "--state",
            str(tmp_path / ".airesearcher" / "scheduler-state.json"),
            "--project-id",
            "project_1",
            "--no-review",
        ],
    )

    assert result.exit_code == 1
    assert "[FAIL] autopilot_cycle: autopilot requires at least one retrieved literature document" in result.output


def test_serve_queues_dangerous_action_until_runtime_approval(
    tmp_path: Path,
    monkeypatch,
) -> None:
    approvals_state = tmp_path / ".airesearcher" / "runtime-approvals.json"
    runner = CliRunner()

    def fail_cycle(**_kwargs: object) -> dict[str, object]:
        raise AssertionError("serve should not run before approval")

    monkeypatch.setattr(cli_main, "_run_autopilot_cycle", fail_cycle)
    pending_result = runner.invoke(
        app,
        [
            "serve",
            "--once",
            "--permission-mode",
            "approve-dangerous",
            "--approvals-state",
            str(approvals_state),
            "--project-id",
            "project_1",
            "--no-review",
        ],
    )

    assert pending_result.exit_code == 2, pending_result.output
    assert "[WAITING] approval_required:" in pending_result.stdout
    payload = json.loads(approvals_state.read_text(encoding="utf-8"))
    request_id = payload["requests"][0]["request_id"]
    assert payload["requests"][0]["status"] == "pending"
    assert payload["requests"][0]["action_id"] == "serve:autopilot-cycle:project_1:tabular_baseline"

    approve_result = runner.invoke(
        app,
        [
            "runtime",
            "approve",
            request_id,
            "--state",
            str(approvals_state),
            "--approved-by",
            "tester",
        ],
    )

    assert approve_result.exit_code == 0, approve_result.output
    assert f"[OK] approved: {request_id}" in approve_result.stdout

    def fake_cycle(**kwargs: object) -> dict[str, object]:
        assert kwargs["project_id"] == "project_1"
        assert kwargs["review"] is False
        return {
            "cycle_id": "cycle-test",
            "summary_path": "runs/autopilot/cycle-test/cycle-summary.json",
            "review": {"status": "skipped"},
            "followups": {"task_count": 0},
        }

    monkeypatch.setattr(cli_main, "_run_autopilot_cycle", fake_cycle)
    allowed_result = runner.invoke(
        app,
        [
            "serve",
            "--once",
            "--permission-mode",
            "approve-dangerous",
            "--approvals-state",
            str(approvals_state),
            "--project-id",
            "project_1",
            "--no-review",
        ],
    )

    assert allowed_result.exit_code == 0, allowed_result.output
    assert "[OK] serve_cycle: cycle-test" in allowed_result.stdout


def test_serve_allow_all_runs_without_approval_state(tmp_path: Path, monkeypatch) -> None:
    approvals_state = tmp_path / ".airesearcher" / "runtime-approvals.json"

    def fake_cycle(**kwargs: object) -> dict[str, object]:
        assert kwargs["project_id"] == "project_1"
        assert kwargs["max_queries"] == cli_main.PUBLICATION_SEARCH_QUERIES
        assert kwargs["max_results_per_source"] == cli_main.PUBLICATION_RESULTS_PER_SOURCE
        return {
            "cycle_id": "cycle-allow-all",
            "summary_path": "runs/autopilot/cycle-allow-all/cycle-summary.json",
            "research_plan": {"audit": {"verdict": "passed"}},
            "review": {"status": "skipped"},
            "followups": {"task_count": 0},
        }

    monkeypatch.setattr(cli_main, "_run_autopilot_cycle", fake_cycle)
    result = CliRunner().invoke(
        app,
        [
            "serve",
            "--once",
            "--permission-mode",
            "allow-all",
            "--approvals-state",
            str(approvals_state),
            "--project-id",
            "project_1",
            "--no-review",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "[OK] runtime_mode: allow-all" in result.stdout
    assert "[OK] serve_cycle: cycle-allow-all" in result.stdout
    assert "[OK] research_plan: passed" in result.stdout
    assert not approvals_state.exists()


def test_runtime_list_defaults_to_pending_requests(tmp_path: Path, monkeypatch) -> None:
    approvals_state = tmp_path / ".airesearcher" / "runtime-approvals.json"
    runner = CliRunner()

    def fail_cycle(**_kwargs: object) -> dict[str, object]:
        raise AssertionError("serve should only queue")

    monkeypatch.setattr(cli_main, "_run_autopilot_cycle", fail_cycle)
    pending_result = runner.invoke(
        app,
        [
            "serve",
            "--once",
            "--permission-mode",
            "approve-dangerous",
            "--approvals-state",
            str(approvals_state),
            "--project-id",
            "project_1",
            "--no-review",
        ],
    )
    list_pending_result = runner.invoke(
        app,
        ["runtime", "list", "--state", str(approvals_state)],
    )
    approve_result = runner.invoke(
        app,
        ["runtime", "approve", "latest", "--state", str(approvals_state)],
    )
    list_after_result = runner.invoke(
        app,
        ["runtime", "list", "--state", str(approvals_state)],
    )
    list_all_result = runner.invoke(
        app,
        ["runtime", "list", "--state", str(approvals_state), "--include-completed"],
    )

    assert pending_result.exit_code == 2, pending_result.output
    assert list_pending_result.exit_code == 0, list_pending_result.output
    assert "[OK] runtime_approval_requests: 1" in list_pending_result.stdout
    assert "[REQUEST] status=pending" in list_pending_result.stdout
    assert approve_result.exit_code == 0, approve_result.output
    assert list_after_result.exit_code == 0, list_after_result.output
    assert "[OK] runtime_approval_requests: 0" in list_after_result.stdout
    assert list_all_result.exit_code == 0, list_all_result.output
    assert "[OK] runtime_approval_requests: 1" in list_all_result.stdout
    assert "[REQUEST] status=approved" in list_all_result.stdout


def test_sessions_cli_blocks_overlapping_claim_until_release(tmp_path: Path) -> None:
    state = tmp_path / ".airesearcher" / "agent-sessions.json"
    runner = CliRunner()

    first = runner.invoke(
        app,
        [
            "sessions",
            "claim",
            "--state",
            str(state),
            "--session-id",
            "session_a",
            "--agent-name",
            "Codex A",
            "--task-id",
            "72.2",
            "--path",
            "src/autoresearch/runtime",
        ],
    )
    blocked = runner.invoke(
        app,
        [
            "sessions",
            "claim",
            "--state",
            str(state),
            "--session-id",
            "session_b",
            "--agent-name",
            "Codex B",
            "--task-id",
            "72.2",
            "--path",
            "src/autoresearch/runtime/sessions.py",
            "--no-fail-on-conflict",
        ],
    )
    list_active = runner.invoke(app, ["sessions", "list", "--state", str(state)])
    release = runner.invoke(
        app,
        ["sessions", "release", "session_a", "--state", str(state)],
    )
    second = runner.invoke(
        app,
        [
            "sessions",
            "claim",
            "--state",
            str(state),
            "--session-id",
            "session_b",
            "--agent-name",
            "Codex B",
            "--task-id",
            "72.2",
            "--path",
            "src/autoresearch/runtime/sessions.py",
        ],
    )

    assert first.exit_code == 0, first.output
    assert "[OK] session_claim: allowed" in first.stdout
    assert blocked.exit_code == 0, blocked.output
    assert "[OK] session_claim: blocked" in blocked.stdout
    assert "[CONFLICT] session_id=session_a" in blocked.stdout
    assert list_active.exit_code == 0, list_active.output
    assert "[OK] agent_sessions: 1" in list_active.stdout
    assert release.exit_code == 0, release.output
    assert "[OK] released: session_a" in release.stdout
    assert second.exit_code == 0, second.output
    assert "[OK] session_claim: allowed" in second.stdout


def test_channel_adapter_manifest_cli_writes_neutral_runbook(tmp_path: Path) -> None:
    output = tmp_path / "integrations" / "channels" / "adapters.json"
    runner = CliRunner()

    init_result = runner.invoke(
        app,
        ["channels", "adapters", "init", "--output", str(output)],
    )
    list_result = runner.invoke(app, ["channels", "adapters", "list"])
    feishu_result = runner.invoke(
        app,
        ["channels", "adapters", "list", "--channel", "openclaw-lark"],
    )

    assert init_result.exit_code == 0, init_result.output
    assert "[OK] channel_adapters: 11" in init_result.stdout
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert "AI-Researcher does not install or execute third-party plugins" in (
        "\n".join(payload["security_notes"])
    )
    channels = {channel["channel_id"]: channel for channel in payload["channels"]}
    assert channels["feishu"]["upstream_role"] == "optional messaging adapter reference"
    assert channels["openclaw-weixin"]["package_name"] == "@tencent-weixin/openclaw-weixin"
    assert list_result.exit_code == 0, list_result.output
    assert "[CHANNEL] channel=feishu upstream_plugin=openclaw-lark" in list_result.stdout
    assert feishu_result.exit_code == 0, feishu_result.output
    assert "[OK] channel_adapters: 1" in feishu_result.stdout


def test_monitor_renders_agent_flow_changes_and_preview(tmp_path: Path) -> None:
    agent_log = tmp_path / "Agent.md"
    agent_log.write_text(
        "\n".join(
            [
                "### 2026-06-14 22:30:00 +08:00 - Codex - Task 117.1",
                "- Request: guided setup and monitor",
                "- Summary:",
                "  - Added operator console.",
                "- Verification:",
                "  - focused tests passed.",
            ]
        ),
        encoding="utf-8",
    )
    sessions = tmp_path / ".airesearcher" / "agent-sessions.json"
    sessions.parent.mkdir(parents=True)
    sessions.write_text(
        json.dumps(
            {
                "sessions": [
                    {
                        "session_id": "session_a",
                        "agent_name": "Codex A",
                        "task_id": "117.1",
                        "claimed_paths": ["src/autoresearch/cli/main.py"],
                        "status": "active",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    approvals = tmp_path / ".airesearcher" / "runtime-approvals.json"
    approvals.write_text(
        json.dumps(
            {
                "requests": [
                    {
                        "request_id": "approval_1",
                        "action_id": "serve:cycle",
                        "status": "pending",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    scheduler = tmp_path / ".airesearcher" / "scheduler-state.json"
    scheduler.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "task_id": "task_open",
                        "name": "open issue follow-up",
                        "status": "open",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    outputs = tmp_path / "outputs" / "project_1"
    outputs.mkdir(parents=True)
    summary = outputs / "project_1-cycle-summary.json"
    summary.write_text(
        json.dumps(
            {
                "source_preflight": {"status": "pass"},
                "review": {"status": "passed"},
                "paper_build": {"status": "compiled"},
                "evidence_gate": {"verdict": "pass"},
            }
        ),
        encoding="utf-8",
    )
    (outputs / "project_1-cycle.pdf").write_bytes(b"%PDF demo")

    result = CliRunner().invoke(
        app,
        [
            "monitor",
            "--agent-log",
            str(agent_log),
            "--sessions-state",
            str(sessions),
            "--runtime-state",
            str(approvals),
            "--scheduler-state",
            str(scheduler),
            "--outputs-dir",
            str(tmp_path / "outputs"),
            "--cycle-summary",
            str(summary),
            "--no-diff",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "AI-Researcher Operator Console" in result.stdout
    assert "Agent Messages" in result.stdout
    assert "Codex A" in result.stdout
    assert "approval_1" in result.stdout
    assert "task_open" in result.stdout
    assert "Research Loop" in result.stdout
    assert "compiled" in result.stdout
    assert "project_1-cycle.pdf" in result.stdout


def test_openclaw_channel_manifest_cli_writes_official_plugin_mounts(tmp_path: Path) -> None:
    output = tmp_path / "integrations" / "openclaw" / "channels.json"
    runner = CliRunner()

    init_result = runner.invoke(
        app,
        ["channels", "openclaw", "init", "--output", str(output)],
    )
    list_result = runner.invoke(app, ["channels", "openclaw", "list"])
    feishu_result = runner.invoke(
        app,
        ["channels", "openclaw", "list", "--channel", "openclaw-lark"],
    )

    assert init_result.exit_code == 0, init_result.output
    assert "[OK] openclaw_channels: 11" in init_result.stdout
    assert "[OK] approval_bridge: airesearcher runtime approve latest" in init_result.stdout
    payload = json.loads(output.read_text(encoding="utf-8"))
    channels = {channel["channel_id"]: channel for channel in payload["channels"]}
    assert channels["feishu"]["package_name"] == "@larksuite/openclaw-lark"
    assert channels["openclaw-weixin"]["package_name"] == "@tencent-weixin/openclaw-weixin"
    assert channels["wecom"]["package_name"] == "@wecom/wecom-openclaw-plugin"
    assert payload["approval_bridge"]["runtime_command"] == (
        "airesearcher serve --permission-mode approve-dangerous"
    )
    assert list_result.exit_code == 0, list_result.output
    assert "[CHANNEL] channel=feishu plugin=openclaw-lark" in list_result.stdout
    assert "[CHANNEL] channel=qqbot plugin=qqbot" in list_result.stdout
    assert feishu_result.exit_code == 0, feishu_result.output
    assert "[OK] openclaw_channels: 1" in feishu_result.stdout
    assert "package=@larksuite/openclaw-lark" in feishu_result.stdout


def test_ccswitch_code_agent_manifest_cli_writes_validation_contract(tmp_path: Path) -> None:
    output = tmp_path / "integrations" / "cc-switch" / "code-agent.json"
    runner = CliRunner()

    init_result = runner.invoke(
        app,
        ["code-agents", "cc-switch", "init", "--output", str(output)],
    )
    list_result = runner.invoke(app, ["code-agents", "cc-switch", "list"])
    backend_result = runner.invoke(
        app,
        [
            "code-agents",
            "cc-switch",
            "list",
            "--backend",
            "claude-code-via-cc-switch",
        ],
    )

    assert init_result.exit_code == 0, init_result.output
    assert "[OK] ccswitch_code_agent_backends: 1" in init_result.stdout
    assert "[OK] validation_owner: AI-Researcher" in init_result.stdout
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["execution_contract"]["validation_owner"] == "AI-Researcher"
    assert payload["approval_bridge"]["approve_command"].startswith(
        "airesearcher runtime approve latest"
    )
    assert payload["backends"][0]["runner_command"] == "claude"
    assert list_result.exit_code == 0, list_result.output
    assert "[BACKEND] backend=claude-code-via-cc-switch" in list_result.stdout
    assert "validator=AI-Researcher" in list_result.stdout
    assert backend_result.exit_code == 0, backend_result.output
    assert "[OK] ccswitch_code_agent_backends: 1" in backend_result.stdout


def test_opencode_code_agent_manifest_cli_writes_validation_contract(tmp_path: Path) -> None:
    output = tmp_path / "integrations" / "opencode" / "code-agent.json"
    runner = CliRunner()

    init_result = runner.invoke(
        app,
        ["code-agents", "opencode", "init", "--output", str(output)],
    )
    list_result = runner.invoke(app, ["code-agents", "opencode", "list"])
    backend_result = runner.invoke(
        app,
        [
            "code-agents",
            "opencode",
            "list",
            "--backend",
            "opencode-direct",
        ],
    )

    assert init_result.exit_code == 0, init_result.output
    assert "[OK] opencode_code_agent_backends: 1" in init_result.stdout
    assert "[OK] validation_owner: AI-Researcher" in init_result.stdout
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["execution_contract"]["generation_owner"] == "OpenCode direct"
    assert payload["execution_contract"]["validation_owner"] == "AI-Researcher"
    assert payload["opencode_project_contract"]["noninteractive_command"].startswith(
        "opencode run"
    )
    assert payload["approval_bridge"]["approve_command"].startswith(
        "airesearcher runtime approve latest"
    )
    assert payload["backends"][0]["runner_command"] == "opencode"
    assert list_result.exit_code == 0, list_result.output
    assert "[BACKEND] backend=opencode-direct" in list_result.stdout
    assert "validator=AI-Researcher" in list_result.stdout
    assert backend_result.exit_code == 0, backend_result.output
    assert "[OK] opencode_code_agent_backends: 1" in backend_result.stdout


def test_scansci_pdf_manifest_cli_writes_oa_first_contract(tmp_path: Path) -> None:
    output = tmp_path / "integrations" / "scansci-pdf" / "pdf-source.json"
    runner = CliRunner()

    init_result = runner.invoke(
        app,
        ["pdf-sources", "scansci-pdf", "init", "--output", str(output)],
    )
    list_result = runner.invoke(app, ["pdf-sources", "scansci-pdf", "list"])
    one_result = runner.invoke(
        app,
        [
            "pdf-sources",
            "scansci-pdf",
            "list",
            "--integration",
            "scansci-pdf-oa-first",
        ],
    )

    assert init_result.exit_code == 0, init_result.output
    assert list_result.exit_code == 0, list_result.output
    assert one_result.exit_code == 0, one_result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    integration = payload["integrations"][0]
    assert payload["default_policy"]["mode"] == "oa_first_legal_only"
    assert "arxiv" in integration["allowed_default_sources"]
    assert "sci-hub" in integration["approval_required_sources"]
    assert "[OK] scansci_pdf_integrations: 1" in init_result.stdout
    assert "[PDF] integration=scansci-pdf-oa-first" in list_result.stdout
    assert "approval_required=sci-hub,libgen" in one_result.stdout


def test_validate_package_command_reports_missing_artifact(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "artifacts": [
                    {
                        "package_path": "code/run.py",
                        "sha256": "missing-hash",
                    }
                ],
                "run_commands": ["python code/run.py"],
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        ["validate-package", "--manifest", str(manifest_path)],
    )

    assert result.exit_code == 1
    assert "[FAIL] package validation failed" in result.stdout
    assert "artifact_exists" in result.stdout
    assert "code/run.py" in result.stdout


def test_llm_smoke_command_writes_quality_report(tmp_path: Path, monkeypatch) -> None:
    quality = LLMSmokeResult.model_validate(
        {
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com",
            "model_name": "deepseek-v4-flash",
            "endpoint": "https://api.deepseek.com/chat/completions",
            "response_text": '{"status":"ok"}',
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            "quality": {
                "score": 1.0,
                "checks": {
                    "non_empty": True,
                    "valid_json": True,
                    "status_ok": True,
                    "summary_present": True,
                    "evidence_policy_present": True,
                    "risks_present": True,
                    "next_steps_present": True,
                    "no_secret_leak": True,
                    "no_fake_urls": True,
                },
                "issues": [],
                "parsed_output": {
                    "status": "ok",
                    "summary": "Unverified research outcomes remain pending verification.",
                    "evidence_policy": "Use source-backed evidence and keep unknowns pending.",
                    "risks": ["missing evidence", "configuration drift"],
                    "next_steps": ["run live literature search", "inspect validation report"],
                },
            },
        }
    )

    def fake_run_llm_smoke_test(**_kwargs: object) -> LLMSmokeResult:
        return quality

    monkeypatch.setattr(cli_main, "run_llm_smoke_test", fake_run_llm_smoke_test)
    output = tmp_path / "llm-smoke.json"

    result = CliRunner().invoke(
        app,
        [
            "llm-smoke",
            "--config",
            str(tmp_path / "config.yaml"),
            "--env-path",
            str(tmp_path / ".env"),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "[OK] model: deepseek-v4-flash" in result.stdout
    assert "[CHECK] valid_json: pass" in result.stdout
    assert output.is_file()


def test_llm_review_command_writes_local_evidence_report(tmp_path: Path, monkeypatch) -> None:
    subject_path = tmp_path / "report.md"
    evidence_path = tmp_path / "validation.json"
    subject_path.write_text("# Report\n\nClaim backed by validation.", encoding="utf-8")
    evidence_path.write_text('{"status":"passed"}', encoding="utf-8")
    review = LLMReviewResult.model_validate(
        {
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com",
            "model_name": "deepseek-v4-flash",
            "endpoint": "https://api.deepseek.com/chat/completions",
            "subject_path": subject_path.as_posix(),
            "subject_sha256": "sha-subject",
            "evidence": [
                {
                    "evidence_id": "evidence_1",
                    "path": evidence_path.as_posix(),
                    "sha256": "sha-evidence",
                    "excerpt": '{"status":"passed"}',
                }
            ],
            "response_text": '{"verdict":"pass"}',
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            "quality": {
                "score": 1.0,
                "checks": {
                    "non_empty": True,
                    "valid_json": True,
                    "verdict_present": True,
                    "summary_present": True,
                    "findings_present": True,
                    "finding_refs_present": True,
                    "finding_refs_known": True,
                    "unsupported_claims_present": True,
                    "next_steps_present": True,
                    "no_secret_leak": True,
                    "no_fake_urls": True,
                },
                "issues": [],
                "parsed_output": {
                    "verdict": "pass",
                    "summary": "The report is grounded in local evidence.",
                    "findings": [
                        {
                            "severity": "info",
                            "claim": "Validation passed.",
                            "evidence_refs": ["evidence_1"],
                        }
                    ],
                    "unsupported_claims": [],
                    "next_steps": ["Keep evidence attached."],
                },
            },
        }
    )

    def fake_review(**_kwargs: object) -> LLMReviewResult:
        return review

    captured_note: dict[str, object] = {}
    vault_note = tmp_path / "vault" / "projects" / "project_1" / "review" / "llm-review.md"

    def fake_write_note(**kwargs: object) -> Path:
        captured_note.update(kwargs)
        return vault_note

    captured_issues: dict[str, object] = {}

    def fake_write_issues(**kwargs: object) -> tuple[Path, ...]:
        captured_issues.update(kwargs)
        return (tmp_path / "vault" / "projects" / "project_1" / "issues" / "issue.md",)

    monkeypatch.setattr(cli_main, "run_llm_evidence_review", fake_review)
    monkeypatch.setattr(cli_main, "write_llm_review_note", fake_write_note)
    monkeypatch.setattr(cli_main, "write_llm_review_issue_notes", fake_write_issues)
    output = tmp_path / "llm-review.json"

    result = CliRunner().invoke(
        app,
        [
            "llm-review",
            "--subject",
            str(subject_path),
            "--evidence",
            str(evidence_path),
            "--config",
            str(tmp_path / "config.yaml"),
            "--env-path",
            str(tmp_path / ".env"),
            "--output",
            str(output),
            "--vault",
            str(tmp_path / "vault"),
            "--project-id",
            "project_1",
            "--source-task-id",
            "44.1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "[OK] review_quality_score: 1.000" in result.stdout
    assert "[CHECK] finding_refs_known: pass" in result.stdout
    assert "[VERDICT] pass" in result.stdout
    assert "[OK] vault_review:" in result.stdout
    assert "[OK] vault_issues: 1" in result.stdout
    assert output.is_file()
    assert captured_note["result"] == review
    assert captured_note["vault_root"] == tmp_path / "vault"
    assert captured_note["project_id"] == "project_1"
    assert captured_note["source_task_id"] == "44.1"
    assert captured_issues["result"] == review
    assert captured_issues["review_note_path"] == vault_note


def test_issue_followups_command_lists_open_project_issue_tasks(tmp_path: Path) -> None:
    vault_root = tmp_path / "autoresearch-vault"
    issue_dir = vault_root / "projects" / "project_1" / "issues"
    issue_dir.mkdir(parents=True)
    open_issue = KnowledgeEntry(
        entry_id="llm_review_issue_project_1_abc",
        entry_type=KnowledgeEntryType.ISSUE_NOTE,
        zone=KnowledgeZone.PROJECT,
        title="LLM review issue: missing evidence",
        project_id="project_1",
        related_task_ids=["48.1"],
        body="\n".join(
            [
                "# LLM Review Follow-Up",
                "",
                "- Status: Open",
                "- Issue fingerprint: `abc123def4567890`",
            ]
        ),
    )
    closed_issue = KnowledgeEntry(
        entry_id="closed_issue",
        entry_type=KnowledgeEntryType.ISSUE_NOTE,
        zone=KnowledgeZone.PROJECT,
        title="Closed issue",
        project_id="project_1",
        body="- Status: Closed\n",
    )
    (issue_dir / "open.md").write_text(open_issue.to_markdown(), encoding="utf-8")
    (issue_dir / "closed.md").write_text(closed_issue.to_markdown(), encoding="utf-8")
    output = tmp_path / "followups.json"
    state = tmp_path / ".airesearcher" / "scheduler-state.json"

    result = CliRunner().invoke(
        app,
        [
            "issue-followups",
            "--vault",
            str(vault_root),
            "--project-id",
            "project_1",
            "--output",
            str(output),
            "--state",
            str(state),
        ],
    )
    second_result = CliRunner().invoke(
        app,
        [
            "issue-followups",
            "--vault",
            str(vault_root),
            "--project-id",
            "project_1",
            "--state",
            str(state),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert second_result.exit_code == 0, second_result.stdout
    assert "[OK] issue_followups: 1" in result.stdout
    assert "[OK] state:" in result.stdout
    assert "[TASK] task_id=issue-follow-up-project_1-abc123def4567890" in result.stdout
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["tasks"][0]["metadata"]["issue_path"] == "projects/project_1/issues/open.md"
    assert payload["tasks"][0]["metadata"]["related_task_ids"] == ["48.1"]
    state_payload = json.loads(state.read_text(encoding="utf-8"))
    assert len(state_payload["tasks"]) == 1
    assert state_payload["tasks"][0]["task_id"] == "issue-follow-up-project_1-abc123def4567890"
    assert state_payload["tasks"][0]["status"] == "open"


def test_scheduler_state_commands_list_complete_and_remove_tasks(tmp_path: Path) -> None:
    state = tmp_path / ".airesearcher" / "scheduler-state.json"
    state.parent.mkdir(parents=True)
    state.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "task_id": "task_open",
                        "name": "open task",
                        "queued_at": "2026-06-12T09:00:00+00:00",
                        "status": "open",
                        "metadata": {"issue_path": "projects/project_1/issues/open.md"},
                    },
                    {
                        "task_id": "task_done",
                        "name": "done task",
                        "queued_at": "2026-06-12T08:00:00+00:00",
                        "status": "completed",
                        "completed_at": "2026-06-12T08:30:00+00:00",
                        "metadata": {"issue_path": "projects/project_1/issues/done.md"},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    runner = CliRunner()

    list_result = runner.invoke(app, ["scheduler-state", "list", "--state", str(state)])
    list_all_result = runner.invoke(
        app,
        ["scheduler-state", "list", "--state", str(state), "--include-completed"],
    )
    complete_result = runner.invoke(
        app,
        ["scheduler-state", "complete", "task_open", "--state", str(state)],
    )
    missing_complete_result = runner.invoke(
        app,
        ["scheduler-state", "complete", "missing", "--state", str(state)],
    )
    remove_result = runner.invoke(
        app,
        ["scheduler-state", "remove", "task_done", "--state", str(state)],
    )

    assert list_result.exit_code == 0, list_result.stdout
    assert "[OK] scheduler_state_tasks: 1" in list_result.stdout
    assert "task_id=task_open" in list_result.stdout
    assert "task_id=task_done" not in list_result.stdout
    assert list_all_result.exit_code == 0, list_all_result.stdout
    assert "[OK] scheduler_state_tasks: 2" in list_all_result.stdout
    assert complete_result.exit_code == 0, complete_result.stdout
    assert missing_complete_result.exit_code == 1
    assert "task not found: missing" in missing_complete_result.output
    assert remove_result.exit_code == 0, remove_result.stdout

    payload = json.loads(state.read_text(encoding="utf-8"))
    assert [task["task_id"] for task in payload["tasks"]] == ["task_open"]
    assert payload["tasks"][0]["status"] == "completed"
    assert "completed_at" in payload["tasks"][0]


def test_issue_followups_state_merge_preserves_completed_tasks(tmp_path: Path) -> None:
    vault_root = tmp_path / "autoresearch-vault"
    issue_dir = vault_root / "projects" / "project_1" / "issues"
    issue_dir.mkdir(parents=True)
    issue = KnowledgeEntry(
        entry_id="llm_review_issue_project_1_abc",
        entry_type=KnowledgeEntryType.ISSUE_NOTE,
        zone=KnowledgeZone.PROJECT,
        title="LLM review issue: missing evidence",
        project_id="project_1",
        body="- Status: Open\n- Issue fingerprint: `abc123def4567890`\n",
    )
    (issue_dir / "open.md").write_text(issue.to_markdown(), encoding="utf-8")
    state = tmp_path / ".airesearcher" / "scheduler-state.json"
    runner = CliRunner()
    args = [
        "issue-followups",
        "--vault",
        str(vault_root),
        "--project-id",
        "project_1",
        "--state",
        str(state),
    ]

    first_result = runner.invoke(app, args)
    complete_result = runner.invoke(
        app,
        [
            "scheduler-state",
            "complete",
            "issue-follow-up-project_1-abc123def4567890",
            "--state",
            str(state),
        ],
    )
    second_result = runner.invoke(app, args)

    assert first_result.exit_code == 0, first_result.stdout
    assert complete_result.exit_code == 0, complete_result.stdout
    assert second_result.exit_code == 0, second_result.stdout
    payload = json.loads(state.read_text(encoding="utf-8"))
    assert len(payload["tasks"]) == 1
    assert payload["tasks"][0]["status"] == "completed"
