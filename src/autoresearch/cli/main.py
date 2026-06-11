"""Minimal Typer CLI for the AutoResearch Phase 0 scaffold."""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path

import typer

from autoresearch import __version__
from autoresearch.config import ConfigFormat, ConfigParser, SystemConfig

app = typer.Typer(
    help="AutoResearch System command line interface.",
    no_args_is_help=True,
)


@app.command()
def version() -> None:
    """Print the installed AutoResearch version."""

    typer.echo(__version__)


@app.command()
def doctor() -> None:
    """Check local scaffold health without contacting external services."""

    config = SystemConfig()
    checks = [
        (
            "python >= 3.10",
            sys.version_info >= (3, 10),
            sys.version.split()[0],
        ),
        (
            "import autoresearch",
            _can_import("autoresearch"),
            "package import",
        ),
        (
            "import autoresearch.config",
            _can_import("autoresearch.config"),
            "config import",
        ),
        (
            "config parser",
            _parser_available(),
            "JSON/YAML/TOML parser",
        ),
        (
            "project root",
            config.project_root.exists(),
            str(config.project_root),
        ),
        (
            "knowledge vault",
            config.knowledge_base.vault_path.exists(),
            str(config.knowledge_base.vault_path),
        ),
    ]

    failed = False
    for name, ok, detail in checks:
        label = "OK" if ok else "FAIL"
        typer.echo(f"[{label}] {name}: {detail}")
        failed = failed or not ok

    if failed:
        raise typer.Exit(code=1)


@app.command("init-demo")
def init_demo(
    path: Path = typer.Option(
        Path("examples/demo"),
        "--path",
        "-p",
        help="Directory where the local demo scaffold should be created.",
    ),
) -> None:
    """Create a local demo scaffold without running a research workflow."""

    path.mkdir(parents=True, exist_ok=True)
    config = SystemConfig(project_root=path)
    parser = ConfigParser()

    readme_path = path / "README.md"
    config_path = path / "config.yaml"

    if not readme_path.exists():
        readme_path.write_text(
            "# AutoResearch Demo\n\n"
            "This scaffold is created by `autoresearch init-demo`.\n"
            "It does not run the research workflow yet.\n",
            encoding="utf-8",
        )
    if not config_path.exists():
        parser.write_file(config, config_path, ConfigFormat.YAML)

    typer.echo(f"Demo scaffold ready at {path}")


def _can_import(module_name: str) -> bool:
    try:
        import_module(module_name)
    except Exception:
        return False
    return True


def _parser_available() -> bool:
    try:
        parser = ConfigParser()
        text = parser.format(SystemConfig(), ConfigFormat.JSON)
        parser.parse_text(text, config_format=ConfigFormat.JSON)
    except Exception:
        return False
    return True


if __name__ == "__main__":
    app()
