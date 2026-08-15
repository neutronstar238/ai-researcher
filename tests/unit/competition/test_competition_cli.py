from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import autoresearch.competition.cli as competition_cli_module
from autoresearch.cli.main import app
from autoresearch.competition.cli import _terminal_safe_text
from autoresearch.competition.official_lineage import LineageStageReport


def test_competition_cli_is_registered() -> None:
    result = CliRunner().invoke(app, ["competition", "--help"])

    assert result.exit_code == 0, result.output
    assert "run" in result.stdout
    assert "resume" in result.stdout
    assert "status" in result.stdout
    assert "export" in result.stdout
    assert "access" in result.stdout
    assert "mdbench" in result.stdout

    mdbench_result = CliRunner().invoke(app, ["competition", "mdbench", "--help"])
    assert mdbench_result.exit_code == 0, mdbench_result.output
    assert "preflight" in mdbench_result.stdout
    assert "prepare" in mdbench_result.stdout
    assert "preregister" in mdbench_result.stdout
    assert "recover-preregister" in mdbench_result.stdout
    assert "autonomous-plan" in mdbench_result.stdout
    assert "autonomous-generate" in mdbench_result.stdout
    assert "autonomous-search" in mdbench_result.stdout
    assert "scientific-contract-plan" in mdbench_result.stdout
    assert "scientific-contract-harness" in mdbench_result.stdout
    assert "sentinel-identifiability-erratum" in mdbench_result.stdout
    assert "final-report" in mdbench_result.stdout
    assert "submission-audit" in mdbench_result.stdout
    assert "publication-authorization-request" in mdbench_result.stdout
    assert "publication-authorize" in mdbench_result.stdout
    assert "lineage-preregister-plan" in mdbench_result.stdout
    assert "lineage-resume-plan" in mdbench_result.stdout
    assert "execute" in mdbench_result.stdout
    assert "evaluate" in mdbench_result.stdout


def test_terminal_diagnostic_is_bounded_and_gbk_safe() -> None:
    rendered = _terminal_safe_text("中文∇" + "甲" * 20, encoding="gbk", max_chars=8)

    rendered.encode("gbk")
    assert "中文\\u2207" in rendered
    assert "exact evidence remains on disk" in rendered


def test_lineage_outcome_stage_is_callable_from_the_production_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: dict[str, object] = {}

    def fake_run_lineage_stage(config: object, **kwargs: object) -> LineageStageReport:
        observed.update(config=config, **kwargs)
        return LineageStageReport(
            lineage_id="cli-outcome",
            stage="outcome",
            lines=("=== 阶段 outcome：系统自主中文结果解释",),
            outcome_path=(tmp_path / "system-authored-outcome.json").as_posix(),
            outcome_hash="a" * 64,
            outcome_accepted=True,
        )

    monkeypatch.setattr(
        competition_cli_module, "run_lineage_stage", fake_run_lineage_stage
    )
    model_config = tmp_path / "qwen.yaml"
    env_file = tmp_path / ".env"
    result = CliRunner().invoke(
        app,
        [
            "competition",
            "mdbench",
            "lineage-stage",
            "--lineage-id",
            "cli-outcome",
            "--stage",
            "outcome",
            "--work-dir",
            str(tmp_path),
            "--config",
            str(model_config),
            "--env",
            str(env_file),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "[OK] lineage_stage: outcome" in result.stdout
    assert "[OK] system_authored_chinese_outcome:" in result.stdout
    assert "[OK] outcome_hash: " + "a" * 64 in result.stdout
    assert "[OK] outcome_accepted: true" in result.stdout
    assert "[BLOCKED] publication_ready: false" in result.stdout
    assert observed["stage"] == "outcome"
    assert observed["outcome_config_path"] == model_config
    assert observed["outcome_env_path"] == env_file


def test_lineage_routing_resume_is_callable_from_the_production_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: dict[str, object] = {}

    def fake_resume(config: object, **kwargs: object) -> LineageStageReport:
        observed.update(config=config, **kwargs)
        return LineageStageReport(
            lineage_id="cli-resume",
            stage="plan",
            lines=("=== 中文计划续跑完成",),
        )

    monkeypatch.setattr(
        competition_cli_module, "resume_plan_from_retained_routing", fake_resume
    )
    work_dir = tmp_path / "lineage"
    resume_dir = work_dir / "resume-01"
    model_config = tmp_path / "qwen.yaml"
    env_file = tmp_path / ".env"
    result = CliRunner().invoke(
        app,
        [
            "competition",
            "mdbench",
            "lineage-resume-plan",
            "--lineage-id",
            "cli-resume",
            "--work-dir",
            str(work_dir),
            "--resume-dir",
            str(resume_dir),
            "--config",
            str(model_config),
            "--env",
            str(env_file),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "=== 中文计划续跑完成" in result.stdout
    assert "[OK] system_authored_chinese_plan: true" in result.stdout
    assert "[BLOCKED] execution_authorized: false" in result.stdout
    assert observed["output_dir"] == resume_dir
    assert observed["config_path"] == model_config
    assert observed["env_path"] == env_file


def test_competition_access_grant_writes_names_not_secrets(tmp_path: Path) -> None:
    output = tmp_path / "grant.json"
    result = CliRunner().invoke(
        app,
        [
            "competition",
            "access",
            "grant",
            "--output",
            str(output),
            "--api-env-var",
            "DASHSCOPE_API_KEY",
            "--network-domain",
            "dashscope.aliyuncs.com",
            "--dataset-license",
            "MIT",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["api_env_vars"] == ["DASHSCOPE_API_KEY"]
    assert payload["network_domains"] == ["dashscope.aliyuncs.com"]
    assert payload["allow_external_submission"] is False
    assert "sk-" not in output.read_text(encoding="utf-8")


def test_final_report_cli_fails_closed_before_writing(tmp_path: Path) -> None:
    lineage = tmp_path / "incomplete-lineage"
    lineage.mkdir()

    result = CliRunner().invoke(
        app,
        [
            "competition",
            "mdbench",
            "final-report",
            "--lineage-dir",
            str(lineage),
            "--no-compile-pdf",
        ],
    )

    assert result.exit_code == 2
    assert "[BLOCKED] final_research_report" in result.stdout
    assert not (lineage / "final-report").exists()


def test_submission_audit_cli_writes_truthful_blocked_bundle(tmp_path: Path) -> None:
    lineage = tmp_path / "incomplete-lineage"
    lineage.mkdir()

    result = CliRunner().invoke(
        app,
        [
            "competition",
            "mdbench",
            "submission-audit",
            "--lineage-dir",
            str(lineage),
            "--config",
            str(Path("config.yaml").resolve()),
            "--repository-root",
            str(Path(".").resolve()),
            "--reuse-quality-gates",
        ],
    )

    assert result.exit_code == 2, result.output
    assert "[INFO] submission_ready: false" in result.stdout
    bundle = lineage / "submission-evidence" / "submission-evidence-bundle.json"
    assert bundle.is_file()
    payload = json.loads(bundle.read_text(encoding="utf-8"))
    assert payload["submission_ready"] is False
    assert payload["publication_ready"] is False


def test_publication_authorization_request_cli_fails_closed_on_incomplete_lineage(
    tmp_path: Path,
) -> None:
    lineage = tmp_path / "incomplete-lineage"
    lineage.mkdir()
    output = lineage / "authorization-request.json"

    result = CliRunner().invoke(
        app,
        [
            "competition",
            "mdbench",
            "publication-authorization-request",
            "--lineage-dir",
            str(lineage),
            "--authorized-by",
            "human-reviewer",
            "--notes",
            "已人工核对完整客观门禁。",
            "--repository-root",
            str(Path(".").resolve()),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 2, result.output
    assert "[BLOCKED] publication_authorization_request" in result.stdout
    assert not output.exists()
