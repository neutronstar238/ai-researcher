import json
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

import autoresearch.cli.main as cli_main
from autoresearch import __version__
from autoresearch.cli.main import app
from autoresearch.config import ConfigParser, SystemConfig
from autoresearch.llm import LLMSmokeResult
from autoresearch.schemas import ResearchCandidate


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
    assert "sk-test" not in env_example_text


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
    assert (commands_dir / "research" / "refresh-literature.toml").is_file()
    assert (commands_dir / "research" / "similarity-check.toml").is_file()
    assert (commands_dir / "research" / "run-demo.toml").is_file()
    assert (commands_dir / "research" / "status.toml").is_file()
    assert list_result.exit_code == 0, list_result.output
    assert "/research:refresh-literature" in list_result.stdout
    assert "/research:similarity-check" in list_result.stdout


def test_literature_refresh_command_reports_source_backed_documents(
    tmp_path: Path,
    monkeypatch,
) -> None:
    summary_path = tmp_path / "vault" / "exploration" / "topics" / "summary.md"
    captured: dict[str, object] = {}

    def fake_refresh(**kwargs):
        captured.update(kwargs)
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
