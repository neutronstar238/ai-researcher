from typer.testing import CliRunner

from autoresearch.cli.main import app


def test_cli_doctor_smoke() -> None:
    result = CliRunner().invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "[OK] import autoresearch" in result.stdout
    assert "[OK] config parser" in result.stdout
