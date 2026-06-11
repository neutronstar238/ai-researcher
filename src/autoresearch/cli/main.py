"""Minimal Typer CLI for the AutoResearch Phase 0 scaffold."""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path

import typer

from autoresearch import __version__
from autoresearch.config import ConfigFormat, ConfigParser, SystemConfig
from autoresearch.experiments import run_scientistbench_demo
from autoresearch.reports import validate_reproducibility_package
from autoresearch.schemas import ValidationStatus

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


@app.command("run-demo")
def run_demo(
    demo: str = typer.Option(
        "tabular_baseline",
        "--demo",
        "-d",
        help="ScientistBench-Lite demo task to run.",
    ),
    output_dir: Path = typer.Option(
        Path("runs/demo"),
        "--output-dir",
        "-o",
        help="Directory where demo outputs should be persisted.",
    ),
    timeout_seconds: int = typer.Option(
        30,
        "--timeout-seconds",
        help="Local execution timeout for the generated demo runner.",
    ),
) -> None:
    """Run one local MVP demo from generated code to evidence-backed report."""

    try:
        result = run_scientistbench_demo(
            demo,
            output_dir=output_dir,
            timeout_seconds=timeout_seconds,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    except Exception as exc:
        typer.echo(f"[FAIL] demo run failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"[OK] demo: {result.demo}")
    typer.echo(f"[OK] experiment_dir: {result.experiment_dir}")
    typer.echo(f"[OK] run_id: {result.run_id}")
    typer.echo(f"[OK] validation: {result.validation_json_path}")
    typer.echo(f"[OK] evidence_map: {result.evidence_map_path}")
    typer.echo(f"[OK] report: {result.report_path}")


@app.command("validate-package")
def validate_package(
    manifest: Path = typer.Option(
        Path("manifest.json"),
        "--manifest",
        "-m",
        help="Path to a reproducibility package manifest.json file.",
    ),
) -> None:
    """Validate a reproducibility package manifest and included artifacts."""

    report = validate_reproducibility_package(manifest)
    if report.status is ValidationStatus.PASSED:
        typer.echo(f"[OK] package validation passed: {report.checked_artifacts} artifacts")
        return

    typer.echo(f"[FAIL] package validation failed: {report.checked_artifacts} artifacts")
    for issue in report.issues:
        target = f" ({issue.package_path})" if issue.package_path else ""
        typer.echo(f"[{issue.severity.value.upper()}] {issue.check}{target}: {issue.message}")
    raise typer.Exit(code=1)


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
