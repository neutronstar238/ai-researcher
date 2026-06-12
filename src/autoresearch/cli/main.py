"""Minimal Typer CLI for the AI-Researcher Phase 0 scaffold."""

import sys
from importlib import import_module
from pathlib import Path
from typing import Annotated

import typer

from autoresearch import __version__
from autoresearch.config import (
    ConfigFormat,
    ConfigParser,
    DeploymentConfig,
    MessagingChannelConfig,
    ModelProviderConfig,
    SystemConfig,
)
from autoresearch.experiments import run_scientistbench_demo
from autoresearch.reports import validate_reproducibility_package
from autoresearch.schemas import ValidationStatus

app = typer.Typer(
    help="AI-Researcher command line interface.",
    no_args_is_help=True,
)
slash_app = typer.Typer(help="Manage project slash command templates.")
app.add_typer(slash_app, name="slash-commands")

DEFAULT_SLASH_COMMANDS = {
    "research/refresh-literature.toml": (
        "Fetch real literature sources and write a guarded Obsidian summary.",
        "Run `autoresearch literature-refresh --live --vault autoresearch-vault --cache .cache/literature` "
        "and summarize source-backed new papers only. Do not infer paper results, code "
        "availability, or benchmark scores unless the fetched source explicitly provides them.",
    ),
    "research/similarity-check.toml": (
        "Cross-check a candidate against adjacent online work before project approval.",
        "Run `autoresearch similarity-check --candidate-file <candidate.json> --live` for {{args}}. "
        "Use source URLs and DOI evidence only; unsupported outcomes must remain pending verification.",
    ),
    "research/run-demo.toml": (
        "Run a local ScientistBench-Lite demo and inspect evidence outputs.",
        "Run `autoresearch run-demo --demo {{args}}` or default to tabular_baseline. "
        "Review the validation report, evidence map, and Markdown report before making claims.",
    ),
    "research/status.toml": (
        "Check local installation and release-readiness gates.",
        "Run `autoresearch doctor`, then inspect `Problem.md`, `Agent.md`, and the latest git status. "
        "Report blockers before proposing more automation.",
    ),
}


@app.command()
def version() -> None:
    """Print the installed AI-Researcher version."""

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
            "# AI-Researcher Demo\n\n"
            "This scaffold is created by `autoresearch init-demo`.\n"
            "It does not run the research workflow yet.\n",
            encoding="utf-8",
        )
    if not config_path.exists():
        parser.write_file(config, config_path, ConfigFormat.YAML)

    typer.echo(f"Demo scaffold ready at {path}")


@app.command("deploy-setup")
def deploy_setup(
    config_path: Annotated[
        Path,
        typer.Option(
            "--config",
            "-c",
            help="Configuration file to create or update.",
        ),
    ] = Path("config.yaml"),
    env_path: Annotated[
        Path,
        typer.Option(
            "--env-path",
            help="Local .env file for secrets and channel credentials.",
        ),
    ] = Path(".env"),
    provider: Annotated[
        str | None,
        typer.Option("--provider", help="LLM provider label, for example openai-compatible."),
    ] = None,
    base_url: Annotated[
        str | None,
        typer.Option("--base-url", help="OpenAI-compatible API base URL."),
    ] = None,
    model_name: Annotated[
        str | None,
        typer.Option("--model-name", help="Model name to use for first deployment."),
    ] = None,
    api_key: Annotated[
        str | None,
        typer.Option("--api-key", help="LLM API key. Stored only in .env."),
    ] = None,
    wechat: Annotated[
        bool | None,
        typer.Option("--wechat/--no-wechat", help="Configure the WeChat channel."),
    ] = None,
    wechat_webhook_url: Annotated[
        str | None,
        typer.Option("--wechat-webhook-url", help="WeChat webhook URL stored in .env."),
    ] = None,
    wechat_app_id: Annotated[
        str | None,
        typer.Option("--wechat-app-id", help="WeChat app ID stored in .env."),
    ] = None,
    wechat_app_secret: Annotated[
        str | None,
        typer.Option("--wechat-app-secret", help="WeChat app secret stored in .env."),
    ] = None,
    feishu: Annotated[
        bool | None,
        typer.Option("--feishu/--no-feishu", help="Configure the Feishu channel."),
    ] = None,
    feishu_webhook_url: Annotated[
        str | None,
        typer.Option("--feishu-webhook-url", help="Feishu webhook URL stored in .env."),
    ] = None,
    feishu_app_id: Annotated[
        str | None,
        typer.Option("--feishu-app-id", help="Feishu app ID stored in .env."),
    ] = None,
    feishu_app_secret: Annotated[
        str | None,
        typer.Option("--feishu-app-secret", help="Feishu app secret stored in .env."),
    ] = None,
    non_interactive: Annotated[
        bool,
        typer.Option("--non-interactive", help="Fail on missing required inputs instead of prompting."),
    ] = False,
) -> None:
    """Run first-deploy setup for model API credentials and chat channels."""

    provider_value = _required_value(
        provider,
        prompt="LLM provider label",
        default="openai-compatible",
        non_interactive=non_interactive,
    )
    base_url_value = _required_value(
        base_url,
        prompt="LLM API base URL",
        default="https://api.openai.com/v1",
        non_interactive=non_interactive,
    )
    model_name_value = _required_value(
        model_name,
        prompt="LLM model name",
        default="gpt-4o-mini",
        non_interactive=non_interactive,
    )
    api_key_value = _required_value(
        api_key,
        prompt="LLM API key",
        default=None,
        hide_input=True,
        non_interactive=non_interactive,
    )

    wechat_enabled = _confirm_if_missing(
        wechat,
        prompt="Configure WeChat channel?",
        non_interactive=non_interactive,
    )
    feishu_enabled = _confirm_if_missing(
        feishu,
        prompt="Configure Feishu channel?",
        non_interactive=non_interactive,
    )

    wechat_values = _channel_values(
        enabled=wechat_enabled,
        channel_name="WeChat",
        webhook_url=wechat_webhook_url,
        app_id=wechat_app_id,
        app_secret=wechat_app_secret,
        non_interactive=non_interactive,
    )
    feishu_values = _channel_values(
        enabled=feishu_enabled,
        channel_name="Feishu",
        webhook_url=feishu_webhook_url,
        app_id=feishu_app_id,
        app_secret=feishu_app_secret,
        non_interactive=non_interactive,
    )

    config = _load_or_default_config(config_path)
    config = config.model_copy(
        update={
            "deployment": DeploymentConfig(
                llm=ModelProviderConfig(
                    provider=provider_value,
                    base_url=base_url_value,
                    model_name=model_name_value,
                    api_key_env="AUTORESEARCH_LLM_API_KEY",
                ),
                wechat=MessagingChannelConfig(
                    enabled=wechat_enabled,
                    webhook_url_env="AUTORESEARCH_WECHAT_WEBHOOK_URL"
                    if wechat_values["webhook_url"]
                    else None,
                    app_id_env="AUTORESEARCH_WECHAT_APP_ID" if wechat_values["app_id"] else None,
                    app_secret_env=(
                        "AUTORESEARCH_WECHAT_APP_SECRET"
                        if wechat_values["app_secret"]
                        else None
                    ),
                ),
                feishu=MessagingChannelConfig(
                    enabled=feishu_enabled,
                    webhook_url_env="AUTORESEARCH_FEISHU_WEBHOOK_URL"
                    if feishu_values["webhook_url"]
                    else None,
                    app_id_env="AUTORESEARCH_FEISHU_APP_ID" if feishu_values["app_id"] else None,
                    app_secret_env=(
                        "AUTORESEARCH_FEISHU_APP_SECRET"
                        if feishu_values["app_secret"]
                        else None
                    ),
                ),
            )
        }
    )

    parser = ConfigParser()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    parser.write_file(config, config_path)

    env_values = {
        "AUTORESEARCH_LLM_PROVIDER": provider_value,
        "AUTORESEARCH_LLM_BASE_URL": base_url_value,
        "AUTORESEARCH_LLM_MODEL_NAME": model_name_value,
        "AUTORESEARCH_LLM_API_KEY": api_key_value,
        "AUTORESEARCH_WECHAT_WEBHOOK_URL": wechat_values["webhook_url"],
        "AUTORESEARCH_WECHAT_APP_ID": wechat_values["app_id"],
        "AUTORESEARCH_WECHAT_APP_SECRET": wechat_values["app_secret"],
        "AUTORESEARCH_FEISHU_WEBHOOK_URL": feishu_values["webhook_url"],
        "AUTORESEARCH_FEISHU_APP_ID": feishu_values["app_id"],
        "AUTORESEARCH_FEISHU_APP_SECRET": feishu_values["app_secret"],
    }
    _merge_env_file(env_path, env_values)

    typer.echo(f"[OK] config written: {config_path}")
    typer.echo(f"[OK] env written: {env_path}")
    typer.echo(f"[OK] model: {provider_value} / {model_name_value}")
    typer.echo(f"[OK] wechat: {'enabled' if wechat_enabled else 'disabled'}")
    typer.echo(f"[OK] feishu: {'enabled' if feishu_enabled else 'disabled'}")


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


@slash_app.command("init")
def init_slash_commands(
    directory: Annotated[
        Path,
        typer.Option(
            "--directory",
            "-d",
            help="Project slash command directory to create.",
        ),
    ] = Path(".autoresearch/commands"),
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite existing command definitions."),
    ] = False,
) -> None:
    """Create project-scoped slash command templates."""

    written = 0
    skipped = 0
    for relative_path, (description, prompt) in DEFAULT_SLASH_COMMANDS.items():
        target = directory / relative_path
        if target.exists() and not force:
            skipped += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_slash_command_toml(description, prompt), encoding="utf-8")
        written += 1

    typer.echo(f"[OK] slash commands written: {written}")
    typer.echo(f"[OK] slash commands skipped: {skipped}")
    typer.echo(f"[OK] directory: {directory}")


@slash_app.command("list")
def list_slash_commands(
    directory: Annotated[
        Path,
        typer.Option(
            "--directory",
            "-d",
            help="Project slash command directory to inspect.",
        ),
    ] = Path(".autoresearch/commands"),
) -> None:
    """List project-scoped slash command templates."""

    if not directory.exists():
        typer.echo(f"[FAIL] slash command directory does not exist: {directory}", err=True)
        raise typer.Exit(code=1)
    commands = sorted(directory.rglob("*.toml"))
    for command in commands:
        name = command.relative_to(directory).with_suffix("").as_posix().replace("/", ":")
        typer.echo(f"/{name}")


def _can_import(module_name: str) -> bool:
    try:
        import_module(module_name)
    except Exception:
        return False
    return True


def _load_or_default_config(config_path: Path) -> SystemConfig:
    if not config_path.exists():
        return SystemConfig()
    parser = ConfigParser()
    config = parser.parse_file(config_path)
    if not isinstance(config, SystemConfig):
        msg = f"{config_path} did not parse as SystemConfig"
        raise typer.BadParameter(msg)
    return config


def _required_value(
    value: str | None,
    *,
    prompt: str,
    default: str | None,
    non_interactive: bool,
    hide_input: bool = False,
) -> str:
    if value:
        return value
    if non_interactive:
        msg = f"{prompt} is required in --non-interactive mode"
        raise typer.BadParameter(msg)
    prompted = typer.prompt(prompt, default=default, hide_input=hide_input)
    if not isinstance(prompted, str) or not prompted.strip():
        msg = f"{prompt} is required"
        raise typer.BadParameter(msg)
    return prompted.strip()


def _confirm_if_missing(
    value: bool | None,
    *,
    prompt: str,
    non_interactive: bool,
) -> bool:
    if value is not None:
        return value
    if non_interactive:
        return False
    return typer.confirm(prompt, default=False)


def _channel_values(
    *,
    enabled: bool,
    channel_name: str,
    webhook_url: str | None,
    app_id: str | None,
    app_secret: str | None,
    non_interactive: bool,
) -> dict[str, str | None]:
    if not enabled:
        return {"webhook_url": None, "app_id": None, "app_secret": None}
    values = {
        "webhook_url": webhook_url,
        "app_id": app_id,
        "app_secret": app_secret,
    }
    if non_interactive:
        if not values["webhook_url"] and not (values["app_id"] and values["app_secret"]):
            msg = (
                f"{channel_name} requires --{channel_name.lower()}-webhook-url or both "
                f"--{channel_name.lower()}-app-id and --{channel_name.lower()}-app-secret"
            )
            raise typer.BadParameter(msg)
        return values

    if values["webhook_url"] is None:
        values["webhook_url"] = typer.prompt(
            f"{channel_name} webhook URL (optional)",
            default="",
        ).strip() or None
    if values["app_id"] is None:
        values["app_id"] = typer.prompt(f"{channel_name} app ID (optional)", default="").strip() or None
    if values["app_secret"] is None:
        values["app_secret"] = (
            typer.prompt(f"{channel_name} app secret (optional)", default="", hide_input=True).strip()
            or None
        )
    if not values["webhook_url"] and not (values["app_id"] and values["app_secret"]):
        msg = f"{channel_name} channel needs a webhook URL or app ID plus app secret"
        raise typer.BadParameter(msg)
    return values


def _merge_env_file(env_path: Path, values: dict[str, str | None]) -> None:
    existing = _read_env_file(env_path)
    for key, value in values.items():
        if value is not None:
            existing[key] = value
    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Generated by autoresearch deploy-setup"]
    lines.extend(f"{key}={value}" for key, value in sorted(existing.items()))
    env_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _read_env_file(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _slash_command_toml(description: str, prompt: str) -> str:
    escaped_description = description.replace("\\", "\\\\").replace('"', '\\"')
    escaped_prompt = prompt.replace('"""', '\\"\\"\\"')
    return f'description="{escaped_description}"\nprompt = """\n{escaped_prompt}\n"""\n'


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
