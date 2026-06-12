import json
from pathlib import Path

from typer.testing import CliRunner

from autoresearch import __version__
from autoresearch.cli.main import app
from autoresearch.config import ConfigParser, SystemConfig


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
    assert "sk-test" not in config_text
    assert "AUTORESEARCH_LLM_API_KEY=sk-test" in env_text
    assert "AUTORESEARCH_WECHAT_WEBHOOK_URL=https://wechat.example.test/hook" in env_text
    assert "AUTORESEARCH_FEISHU_WEBHOOK_URL=https://feishu.example.test/hook" in env_text


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
