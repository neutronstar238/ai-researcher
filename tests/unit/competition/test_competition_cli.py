from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from autoresearch.cli.main import app


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
    assert "sentinel-identifiability-erratum" in mdbench_result.stdout
    assert "execute" in mdbench_result.stdout
    assert "evaluate" in mdbench_result.stdout


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
