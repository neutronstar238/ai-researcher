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
