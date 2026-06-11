from pathlib import Path

from typer.testing import CliRunner

from autoresearch import __version__
from autoresearch.cli.main import app


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
