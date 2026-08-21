"""Typer commands for persistent autonomous research campaigns."""

from __future__ import annotations

import json
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from autoresearch.campaign.development import DevelopmentFixtureCampaignAdapter
from autoresearch.campaign.mdbench import (
    MDBenchAdapterConfig,
    MDBenchCampaignAdapter,
    audit_mdbench_holdout,
)
from autoresearch.campaign.mechanism_confirmatory import (
    MechanismConfirmatoryManifest,
    MechanismConfirmatoryStatus,
    freeze_task2612_confirmatory,
    load_mechanism_confirmatory,
    load_mechanism_confirmatory_preregistration,
    run_task2612_confirmatory,
)
from autoresearch.campaign.mechanism_development import (
    MechanismDevelopmentManifest,
    MechanismDevelopmentStatus,
    load_mechanism_development,
    run_task2612_mechanism_development,
)
from autoresearch.campaign.mechanism_paper import (
    MechanismPaperBuildResult,
    build_task2612_child_paper,
    load_task2612_child_paper,
)
from autoresearch.campaign.models import (
    CampaignPolicy,
    CampaignRoundDesign,
    CampaignSpec,
    CampaignTrack,
)
from autoresearch.campaign.paper import (
    build_task260_paper_package,
    validate_task260_paper_package,
)
from autoresearch.campaign.reporting import CampaignExporter
from autoresearch.campaign.service import AutonomousResearchCampaign
from autoresearch.campaign.sprint import (
    AutonomousResearchSprint,
    SprintOutcome,
    build_sprint_spec,
)
from autoresearch.campaign.systems import (
    build_task260_systems_preregistration,
    run_systems_benchmark,
    systems_benchmark_status,
)
from autoresearch.schemas import data_hash, file_hash

campaign_app = typer.Typer(
    help="Run, resume, inspect, and export recursive evidence-first research campaigns.",
    no_args_is_help=True,
)
_SHANGHAI_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")


@campaign_app.command("start")
def campaign_start(
    spec_path: Annotated[
        Path | None,
        typer.Option("--spec", help="Optional complete CampaignSpec JSON."),
    ] = None,
    campaign_id: Annotated[
        str,
        typer.Option("--campaign-id", help="Stable path-safe campaign ID."),
    ] = "fast-ccfb-campaign",
    project_id: Annotated[
        str,
        typer.Option("--project-id", help="Obsidian project ID."),
    ] = "autoresearch-ccfb",
    policy: Annotated[
        str,
        typer.Option("--policy", help="Campaign policy; currently fast-ccfb."),
    ] = CampaignPolicy.FAST_CCFB.value,
    deadline: Annotated[
        str,
        typer.Option("--deadline", help="ISO date or timezone-aware datetime."),
    ] = "2026-08-15",
    adapter_id: Annotated[
        str,
        typer.Option(
            "--adapter",
            help=(
                "Scientific adapter ID. The default uses local Qwen and the real "
                "hash-bound MDBench runner; development-fixture-v1 is lifecycle-only."
            ),
        ),
    ] = MDBenchCampaignAdapter.adapter_id,
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Campaign run root."),
    ] = Path("runs/campaigns"),
    vault: Annotated[
        Path,
        typer.Option("--vault", help="Obsidian vault root."),
    ] = Path("autoresearch-vault"),
) -> None:
    """Start a campaign and drive it until a terminal or access boundary."""

    try:
        if spec_path is not None:
            spec = CampaignSpec.model_validate_json(
                spec_path.read_text(encoding="utf-8")
            )
        else:
            if policy != CampaignPolicy.FAST_CCFB.value:
                raise ValueError("campaign policy must be fast-ccfb")
            parsed_deadline = _parse_deadline(deadline)
            if adapter_id == DevelopmentFixtureCampaignAdapter.adapter_id:
                spec = _development_campaign_spec(
                    campaign_id=campaign_id,
                    project_id=project_id,
                    deadline=parsed_deadline,
                    adapter_id=adapter_id,
                )
            elif adapter_id == MDBenchCampaignAdapter.adapter_id:
                spec = _mdbench_campaign_spec(
                    campaign_id=campaign_id,
                    project_id=project_id,
                    deadline=parsed_deadline,
                    output_dir=output_dir,
                )
            else:
                raise ValueError(f"campaign adapter is not installed: {adapter_id}")
        adapter = _resolve_adapter(
            spec,
            Path(output_dir) / spec.campaign_id / "adapter-evidence",
        )
        service = AutonomousResearchCampaign(
            adapter=adapter,
            output_root=output_dir,
            vault_root=vault,
        )
        result = service.run(spec)
    except (OSError, RuntimeError, ValidationError, ValueError) as exc:
        typer.echo(f"[BLOCKED] campaign_start: {exc}")
        raise typer.Exit(code=2) from exc
    _echo_result(result)
    if spec.adapter_id == DevelopmentFixtureCampaignAdapter.adapter_id:
        typer.echo(
            "[BOUNDARY] development fixture only; no scientific contribution or "
            "publication claim is authorized"
        )


@campaign_app.command("resume")
def campaign_resume(
    campaign_dir: Annotated[
        Path,
        typer.Argument(help="Existing campaign directory."),
    ],
    vault: Annotated[
        Path,
        typer.Option("--vault", help="Obsidian vault root."),
    ] = Path("autoresearch-vault"),
) -> None:
    """Resume a verified campaign without rerunning completed stages."""

    try:
        spec = CampaignSpec.model_validate_json(
            (campaign_dir / "campaign-spec.json").read_text(encoding="utf-8")
        )
        adapter = _resolve_adapter(
            spec,
            campaign_dir / "adapter-evidence",
        )
        result = AutonomousResearchCampaign(
            adapter=adapter,
            output_root=campaign_dir.parent,
            vault_root=vault,
        ).resume(campaign_dir)
    except (OSError, RuntimeError, ValidationError, ValueError) as exc:
        typer.echo(f"[BLOCKED] campaign_resume: {exc}")
        raise typer.Exit(code=2) from exc
    _echo_result(result)


@campaign_app.command("status")
def campaign_status(
    campaign_dir: Annotated[
        Path,
        typer.Argument(help="Existing campaign directory."),
    ],
) -> None:
    """Validate and print persisted status without advancing scientific work."""

    try:
        spec = CampaignSpec.model_validate_json(
            (campaign_dir / "campaign-spec.json").read_text(encoding="utf-8")
        )
        adapter = _resolve_adapter(
            spec,
            campaign_dir / "adapter-evidence",
        )
        result = AutonomousResearchCampaign(
            adapter=adapter,
            output_root=campaign_dir.parent,
        ).status(campaign_dir)
    except (OSError, RuntimeError, ValidationError, ValueError) as exc:
        typer.echo(f"[BLOCKED] campaign_status: {exc}")
        raise typer.Exit(code=2) from exc
    _echo_result(result)


@campaign_app.command("export")
def campaign_export(
    campaign_dir: Annotated[
        Path,
        typer.Argument(help="Verified campaign directory."),
    ],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Local dossier root."),
    ] = Path("outputs/campaigns"),
) -> None:
    """Export a complete indexed dossier without external submission permission."""

    try:
        result = CampaignExporter().export(campaign_dir, output_dir)
    except (OSError, ValidationError, ValueError) as exc:
        typer.echo(f"[BLOCKED] campaign_export: {exc}")
        raise typer.Exit(code=2) from exc
    typer.echo(f"[OK] deliverables: {result.deliverables_dir}")
    typer.echo(f"[OK] index: {result.index_path}")
    typer.echo(f"[OK] manifest: {result.manifest_path}")
    typer.echo(f"[OK] file_count: {result.file_count}")
    typer.echo("[BLOCKED] external_submission_authorized=false")


@campaign_app.command("systems-preregister")
def campaign_systems_preregister(
    benchmark_id: Annotated[
        str,
        typer.Option("--benchmark-id", help="Stable Route B benchmark ID."),
    ] = "task260-autonomous-systems-v1",
    project_id: Annotated[
        str,
        typer.Option("--project-id", help="Obsidian project ID."),
    ] = "autoresearch-ccfb",
    deadline: Annotated[
        str,
        typer.Option("--deadline", help="ISO date or timezone-aware datetime."),
    ] = "2026-08-15",
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Route B run root."),
    ] = Path("runs/manual-live"),
    route_a_campaign: Annotated[
        Path,
        typer.Option(
            "--route-a-campaign",
            help="Completed two-round Route A campaign to bind.",
        ),
    ] = Path("runs/manual-live/task260-autonomous-ccfb-v1"),
    llm_config: Annotated[
        Path,
        typer.Option("--llm-config", help="Local Ollama OpenAI-compatible config."),
    ] = Path("configs/campaign/ollama-qwen35-sprint-8k.yaml"),
) -> None:
    """Freeze the ten-task systems matrix before any controller result exists."""

    benchmark_dir = Path(output_dir) / benchmark_id
    try:
        prereg = build_task260_systems_preregistration(
            benchmark_dir,
            project_id=project_id,
            deadline=_parse_deadline(deadline),
            route_a_campaign_dir=route_a_campaign,
            llm_config_path=llm_config,
        )
    except (OSError, RuntimeError, ValidationError, ValueError) as exc:
        typer.echo(f"[BLOCKED] campaign_systems_preregister: {exc}")
        raise typer.Exit(code=2) from exc
    typer.echo(f"benchmark_dir={benchmark_dir.resolve()}")
    typer.echo(f"preregistration_hash={prereg.preregistration_hash}")
    typer.echo(f"task_count={len(prereg.tasks)}")
    typer.echo(f"seed_count={len(prereg.seeds)}")
    typer.echo("external_submission_authorized=false")


@campaign_app.command("systems-run")
def campaign_systems_run(
    benchmark_dir: Annotated[
        Path,
        typer.Argument(help="Frozen Route B benchmark directory."),
    ],
) -> None:
    """Run or idempotently resume the complete systems-paper matrix."""

    try:
        result = run_systems_benchmark(benchmark_dir)
    except (OSError, RuntimeError, ValidationError, ValueError) as exc:
        typer.echo(f"[BLOCKED] campaign_systems_run: {exc}")
        raise typer.Exit(code=2) from exc
    typer.echo(f"benchmark_id={result.benchmark_id}")
    typer.echo(f"result_hash={result.result_hash}")
    typer.echo(f"cell_count={result.cell_count}")
    typer.echo(
        "paired_bootstrap_ci95="
        f"[{result.bootstrap_ci95_lower:.6f},{result.bootstrap_ci95_upper:.6f}]"
    )
    typer.echo(f"report={result.report_path}")
    typer.echo(f"contribution_gate={result.contribution_gate_path}")
    typer.echo("external_submission_authorized=false")


@campaign_app.command("systems-status")
def campaign_systems_status(
    benchmark_dir: Annotated[
        Path,
        typer.Argument(help="Frozen or completed Route B benchmark directory."),
    ],
) -> None:
    """Verify the preregistration, sources, cell hashes, and aggregate decision."""

    try:
        status = systems_benchmark_status(benchmark_dir)
    except (OSError, RuntimeError, ValidationError, ValueError) as exc:
        typer.echo(f"[BLOCKED] campaign_systems_status: {exc}")
        raise typer.Exit(code=2) from exc
    typer.echo(f"benchmark_dir={status.benchmark_dir}")
    typer.echo(f"preregistration_hash={status.preregistration_hash}")
    typer.echo(f"completed={str(status.completed).lower()}")
    typer.echo(f"result_hash={status.result_hash}")
    typer.echo(f"contribution_gate_passed={status.contribution_gate_passed}")
    typer.echo(f"cell_count={status.cell_count}")
    typer.echo("external_submission_authorized=false")


@campaign_app.command("paper-build")
def campaign_paper_build(
    route_a_campaign: Annotated[
        Path,
        typer.Option("--route-a-campaign", help="Completed two-round Route A campaign."),
    ] = Path("runs/manual-live/task260-autonomous-ccfb-v1"),
    systems_benchmark: Annotated[
        Path,
        typer.Option(
            "--systems-benchmark",
            help="Completed preregistered Route B systems benchmark.",
        ),
    ] = Path("runs/manual-live/task260-autonomous-systems-v1"),
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Final hash-bound paper package directory."),
    ] = Path("runs/manual-live/task260-final-paper-v1"),
    reproduction_dir: Annotated[
        Path,
        typer.Option(
            "--reproduction-dir",
            help="Absent or empty directory used for the independent rebuild.",
        ),
    ] = Path("runs/manual-live/task260-final-paper-reproduction-v1"),
    vault: Annotated[
        Path,
        typer.Option("--vault", help="Obsidian vault root."),
    ] = Path("autoresearch-vault"),
    live_citations: Annotated[
        bool,
        typer.Option(
            "--live-citations/--no-live-citations",
            help="Resolve every registered bibliography source during the audit.",
        ),
    ] = True,
    compile_pdf: Annotated[
        bool,
        typer.Option(
            "--compile/--no-compile",
            help="Compile all vector figures and the ACM two-column manuscript.",
        ),
    ] = True,
    copy_dossier: Annotated[
        bool,
        typer.Option(
            "--copy-dossier/--no-copy-dossier",
            help="Copy both complete campaign directories into the package.",
        ),
    ] = True,
) -> None:
    """Build, independently reproduce, and audit the task 260 paper package."""

    try:
        result = build_task260_paper_package(
            route_a_campaign_dir=route_a_campaign,
            systems_benchmark_dir=systems_benchmark,
            output_dir=output_dir,
            reproduction_dir=reproduction_dir,
            vault_root=vault,
            live_citation_check=live_citations,
            compile_pdf=compile_pdf,
            copy_dossier=copy_dossier,
        )
    except (OSError, RuntimeError, ValidationError, ValueError) as exc:
        typer.echo(f"[BLOCKED] campaign_paper_build: {exc}")
        raise typer.Exit(code=2) from exc
    typer.echo(f"package_dir={result.package_dir}")
    typer.echo(f"package_hash={result.package_hash}")
    typer.echo(f"verdict={result.verdict}")
    typer.echo(f"manuscript_pdf={result.manuscript_pdf_path}")
    typer.echo(f"deliverables_index={result.deliverables_index_path}")
    typer.echo(f"reproduction_report={result.reproduction_report_path}")
    typer.echo("external_submission_authorized=false")
    if result.verdict != "ready_for_human_submission_review":
        raise typer.Exit(code=3)


@campaign_app.command("paper-status")
def campaign_paper_status(
    package_dir: Annotated[
        Path,
        typer.Argument(help="Existing task 260 paper package directory."),
    ],
) -> None:
    """Verify the paper manifest, audit, and every recorded artifact hash."""

    try:
        result = validate_task260_paper_package(package_dir)
    except (OSError, RuntimeError, ValidationError, ValueError) as exc:
        typer.echo(f"[BLOCKED] campaign_paper_status: {exc}")
        raise typer.Exit(code=2) from exc
    typer.echo(f"package_dir={result.package_dir}")
    typer.echo(f"package_hash={result.package_hash}")
    typer.echo(f"verdict={result.verdict}")
    typer.echo(f"manuscript_pdf={result.manuscript_pdf_path}")
    typer.echo(f"deliverables_index={result.deliverables_index_path}")
    typer.echo("external_submission_authorized=false")


@campaign_app.command("sprint-run")
def campaign_sprint_run(
    sprint_id: Annotated[
        str,
        typer.Option("--sprint-id", help="Stable path-safe sprint ID."),
    ] = "autoresearch-bounded-sprint-v1",
    project_id: Annotated[
        str,
        typer.Option("--project-id", help="Obsidian project ID."),
    ] = "autoresearch-ccfb",
    brief: Annotated[
        str,
        typer.Option(
            "--brief",
            help=(
                "High-level research objective. The local model selects the primary "
                "question from executable programs after live literature retrieval."
            ),
        ),
    ] = (
        "Identify and execute the strongest falsifiable local experiment about "
        "evidence-bound autonomous research loops on local compute."
    ),
    route_a_campaign: Annotated[
        Path,
        typer.Option(
            "--route-a-campaign",
            help=(
                "Completed Route A evidence imported as a prelaunch boundary. "
                "The autonomy audit records that it was not generated in this sprint."
            ),
        ),
    ] = Path("runs/manual-live/task260-autonomous-ccfb-v1"),
    llm_config: Annotated[
        Path,
        typer.Option("--llm-config", help="Local Ollama OpenAI-compatible config."),
    ] = Path("configs/campaign/ollama-qwen35-sprint-8k.yaml"),
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Autonomous sprint run root."),
    ] = Path("runs/autonomous-sprints"),
    vault: Annotated[
        Path,
        typer.Option("--vault", help="Canonical Obsidian vault root."),
    ] = Path("autoresearch-vault"),
    compile_pdf: Annotated[
        bool,
        typer.Option(
            "--compile/--no-compile",
            help="Automatically compile the generated manuscript in the same run.",
        ),
    ] = True,
) -> None:
    """Run live topic selection, experiment, task-level inference, and PDF build."""

    try:
        spec = build_sprint_spec(
            sprint_id=sprint_id,
            project_id=project_id,
            high_level_brief=brief,
            route_a_campaign_path=route_a_campaign,
            llm_config_path=llm_config,
            compile_pdf=compile_pdf,
        )
        result = AutonomousResearchSprint(
            output_root=output_dir,
            vault_root=vault,
        ).run(spec)
    except (OSError, RuntimeError, ValidationError, ValueError) as exc:
        typer.echo(f"[BLOCKED] campaign_sprint_run: {exc}")
        raise typer.Exit(code=2) from exc
    _echo_sprint_result(result)
    if result.outcome is SprintOutcome.BLOCKED:
        typer.echo(
            "[BLOCKED] sprint stopped rather than using a topic, policy, or "
            "manuscript fallback"
        )
        raise typer.Exit(code=2)


@campaign_app.command("sprint-status")
def campaign_sprint_status(
    sprint_dir: Annotated[
        Path,
        typer.Argument(help="Existing autonomous sprint directory."),
    ],
) -> None:
    """Verify sprint hashes and print the audited autonomy boundary."""

    try:
        result = AutonomousResearchSprint(
            output_root=sprint_dir.parent,
        ).status(sprint_dir)
    except (OSError, RuntimeError, ValidationError, ValueError) as exc:
        typer.echo(f"[BLOCKED] campaign_sprint_status: {exc}")
        raise typer.Exit(code=2) from exc
    _echo_sprint_result(result)


@campaign_app.command("mechanism-develop")
def campaign_mechanism_develop(
    foundation_dir: Annotated[
        Path,
        typer.Option(
            "--foundation-dir",
            help="Verified task 261.2.1 foundation directory.",
        ),
    ] = Path("runs/manual-live/task2612-mechanism-foundation-live-v3"),
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            help="Absent or empty task 261.2.2 evidence directory.",
        ),
    ] = Path("runs/manual-live/task2612-mechanism-development-live-v1"),
    run_id: Annotated[
        str,
        typer.Option("--run-id", help="Stable task 261.2.2 run ID."),
    ] = "task2612-mechanism-development-live-v1",
    llm_config: Annotated[
        Path,
        typer.Option(
            "--llm-config",
            help="Provider-neutral OpenAI-compatible model configuration.",
        ),
    ] = Path("configs/campaign/ollama-qwen35-sprint-8k.yaml"),
    env_path: Annotated[
        Path,
        typer.Option(
            "--env-path",
            help="Optional local environment file; secret values are never persisted.",
        ),
    ] = Path(".env"),
) -> None:
    """Generate, secure, and development-screen one parent-bound mechanism."""

    try:
        result = run_task2612_mechanism_development(
            output_dir=output_dir,
            foundation_dir=foundation_dir,
            llm_config_path=llm_config,
            env_path=env_path,
            run_id=run_id,
        )
    except (OSError, RuntimeError, ValidationError, ValueError) as exc:
        typer.echo(f"[BLOCKED] campaign_mechanism_develop: {exc}")
        raise typer.Exit(code=2) from exc
    _echo_mechanism_development(result)
    if result.status is MechanismDevelopmentStatus.BLOCKED:
        raise typer.Exit(code=2)
    if result.status is MechanismDevelopmentStatus.NEGATIVE_DEVELOPMENT:
        raise typer.Exit(code=3)


@campaign_app.command("mechanism-status")
def campaign_mechanism_status(
    mechanism_dir: Annotated[
        Path,
        typer.Argument(help="Existing terminal task 261.2.2 directory."),
    ],
) -> None:
    """Verify every task 261.2.2 artifact hash without advancing the run."""

    try:
        result = load_mechanism_development(mechanism_dir)
    except (OSError, RuntimeError, ValidationError, ValueError) as exc:
        typer.echo(f"[BLOCKED] campaign_mechanism_status: {exc}")
        raise typer.Exit(code=2) from exc
    _echo_mechanism_development(result)


@campaign_app.command("mechanism-confirmatory-freeze")
def campaign_mechanism_confirmatory_freeze(
    development_dir: Annotated[
        Path,
        typer.Option(
            "--development-dir",
            help="Hash-valid ready task 261.2.2 development directory.",
        ),
    ] = Path("runs/manual-live/task2612-mechanism-development-live-v12"),
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            help="Absent or empty task 261.2.3 confirmatory directory.",
        ),
    ] = Path("runs/manual-live/task2612-mechanism-confirmatory-live-v1"),
    run_id: Annotated[
        str,
        typer.Option("--run-id", help="Stable task 261.2.3 run ID."),
    ] = "task2612-mechanism-confirmatory-live-v1",
) -> None:
    """Freeze exact code, environment, statistics, and panel before reveal."""

    try:
        result = freeze_task2612_confirmatory(
            development_dir=development_dir,
            output_dir=output_dir,
            run_id=run_id,
        )
    except (OSError, RuntimeError, ValidationError, ValueError) as exc:
        typer.echo(f"[BLOCKED] campaign_mechanism_confirmatory_freeze: {exc}")
        raise typer.Exit(code=2) from exc
    typer.echo(f"run_id={result.run_id}")
    typer.echo(f"preregistration_hash={result.preregistration_hash}")
    typer.echo(f"environment_hash={result.environment.environment_hash}")
    typer.echo(f"control_spec_hash={result.control_spec_hash}")
    typer.echo(f"generated_source_sha256={result.generated_source_sha256}")
    typer.echo("confirmatory_results_revealed=false")
    typer.echo("scientific_result_created=false")
    typer.echo("external_submission_authorized=false")


@campaign_app.command("mechanism-confirmatory-run")
def campaign_mechanism_confirmatory_run(
    output_dir: Annotated[
        Path,
        typer.Argument(help="Existing frozen task 261.2.3 directory."),
    ],
) -> None:
    """Execute the frozen panel once and seal its scientific endpoint."""

    try:
        result = run_task2612_confirmatory(output_dir=output_dir)
    except (OSError, RuntimeError, ValidationError, ValueError) as exc:
        typer.echo(f"[BLOCKED] campaign_mechanism_confirmatory_run: {exc}")
        raise typer.Exit(code=2) from exc
    _echo_mechanism_confirmatory(result)
    if result.status is MechanismConfirmatoryStatus.VERIFICATION_FAILED:
        raise typer.Exit(code=2)


@campaign_app.command("mechanism-confirmatory-status")
def campaign_mechanism_confirmatory_status(
    output_dir: Annotated[
        Path,
        typer.Argument(help="Frozen or terminal task 261.2.3 directory."),
    ],
) -> None:
    """Verify preregistration or every terminal confirmatory artifact."""

    try:
        if (output_dir / "confirmatory-manifest.json").is_file():
            _echo_mechanism_confirmatory(
                load_mechanism_confirmatory(output_dir)
            )
        else:
            result = load_mechanism_confirmatory_preregistration(output_dir)
            typer.echo(f"run_id={result.run_id}")
            typer.echo("status=frozen_unrevealed")
            typer.echo(f"preregistration_hash={result.preregistration_hash}")
            typer.echo("confirmatory_results_revealed=false")
            typer.echo("scientific_result_created=false")
            typer.echo("external_submission_authorized=false")
    except (OSError, RuntimeError, ValidationError, ValueError) as exc:
        typer.echo(f"[BLOCKED] campaign_mechanism_confirmatory_status: {exc}")
        raise typer.Exit(code=2) from exc


@campaign_app.command("mechanism-paper-build")
def campaign_mechanism_paper_build(
    foundation_dir: Annotated[
        Path,
        typer.Option(
            "--foundation-dir",
            help="Hash-valid task 261.2.1 foundation directory.",
        ),
    ] = Path("runs/manual-live/task2612-mechanism-foundation-live-v3"),
    confirmatory_dir: Annotated[
        Path,
        typer.Option(
            "--confirmatory-dir",
            help="Terminal task 261.2.3 confirmatory directory.",
        ),
    ] = Path("runs/manual-live/task2612-mechanism-confirmatory-live-v1"),
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            help="Absent or empty task 261.2.4 paper-package directory.",
        ),
    ] = Path("runs/manual-live/task2612-mechanism-paper-live-v1"),
    reproduction_dir: Annotated[
        Path,
        typer.Option(
            "--reproduction-dir",
            help="Absent or empty independent paper-rebuild directory.",
        ),
    ] = Path("runs/manual-live/task2612-mechanism-paper-reproduction-live-v1"),
    compile_pdf: Annotated[
        bool,
        typer.Option(
            "--compile/--no-compile",
            help="Compile and quality-check primary and independently rebuilt PDFs.",
        ),
    ] = True,
    live_sources: Annotated[
        bool,
        typer.Option(
            "--live-sources/--frozen-source-snapshot",
            help="Recheck all fourteen frozen source URLs during this build.",
        ),
    ] = False,
) -> None:
    """Build the evidence-bound negative-result child paper and audit."""

    try:
        result = build_task2612_child_paper(
            foundation_dir=foundation_dir,
            confirmatory_dir=confirmatory_dir,
            output_dir=output_dir,
            reproduction_dir=reproduction_dir,
            compile_pdf=compile_pdf,
            live_source_check=live_sources,
        )
    except (OSError, RuntimeError, ValidationError, ValueError) as exc:
        typer.echo(f"[BLOCKED] campaign_mechanism_paper_build: {exc}")
        raise typer.Exit(code=2) from exc
    _echo_mechanism_paper(result)


@campaign_app.command("mechanism-paper-status")
def campaign_mechanism_paper_status(
    output_dir: Annotated[
        Path,
        typer.Argument(help="Terminal task 261.2.4 paper-package directory."),
    ],
) -> None:
    """Verify the full child-paper artifact index and semantic audits."""

    try:
        result = load_task2612_child_paper(output_dir)
    except (OSError, RuntimeError, ValidationError, ValueError) as exc:
        typer.echo(f"[BLOCKED] campaign_mechanism_paper_status: {exc}")
        raise typer.Exit(code=2) from exc
    _echo_mechanism_paper(result)


def _development_campaign_spec(
    *,
    campaign_id: str,
    project_id: str,
    deadline: datetime,
    adapter_id: str,
) -> CampaignSpec:
    return CampaignSpec(
        campaign_id=campaign_id,
        project_id=project_id,
        policy=CampaignPolicy.FAST_CCFB,
        adapter_id=adapter_id,
        deadline=deadline,
        min_experimental_rounds=2,
        root_result_hash=data_hash("development-fixture-root-negative-result"),
        root_evidence_refs=("fixture:root-negative-result",),
        round_designs=(
            CampaignRoundDesign(
                round_number=1,
                track=CampaignTrack.AUTONOMOUS_RESEARCH_SYSTEM,
                development_data_refs=("fixture:development:linear-a",),
                unseen_data_refs=("fixture:sealed:linear-a",),
                seeds=(101, 103, 107),
                candidate_mechanism_families=("fixture-noise-conditioned-regression",),
                primary_metric="relative_mse_improvement",
                acceptance_criteria=("development metric payload is non-constant",),
                max_wall_time_seconds=60,
            ),
            CampaignRoundDesign(
                round_number=2,
                track=CampaignTrack.AUTONOMOUS_RESEARCH_SYSTEM,
                development_data_refs=("fixture:development:linear-b",),
                unseen_data_refs=("fixture:sealed:linear-b",),
                seeds=(109, 113, 127),
                candidate_mechanism_families=("fixture-robust-regression",),
                primary_metric="relative_mse_improvement",
                acceptance_criteria=("frozen evaluation is reproducible",),
                max_wall_time_seconds=60,
            ),
        ),
    )


def _mdbench_campaign_spec(
    *,
    campaign_id: str,
    project_id: str,
    deadline: datetime,
    output_dir: Path,
) -> CampaignSpec:
    archive_manifest = _required_existing_path(
        "official MDBench archive manifest",
        Path(
            "runs/manual-live/task259-mdbench-official-v1/data/prepared/"
            "archive-manifest.json"
        ),
    )
    original_preregistration = _required_existing_path(
        "original MDBench preregistration",
        Path(
            "runs/manual-live/task259-mdbench-official-v1/"
            "gate-a-preregistration.json"
        ),
    )
    recovery_preregistration = _required_existing_path(
        "recovery MDBench preregistration",
        Path(
            "runs/manual-live/task259-mdbench-recovery-v1/"
            "gate-a-recovery-preregistration.json"
        ),
    )
    root_adjudication = _required_existing_path(
        "latest immutable negative adjudication",
        Path(
            "runs/manual-live/task259-mdbench-recovery-official-v1/"
            "gate-a-v1/gate-a-adjudication.json"
        ),
    )
    llm_config = _required_existing_path(
        "local Ollama campaign config",
        Path("configs/campaign/ollama-qwen35-9b.yaml"),
    )
    preflight_path = (
        Path(output_dir).resolve()
        / "_campaign-preflight"
        / f"{campaign_id}-holdout-audit.json"
    )
    audit = audit_mdbench_holdout(
        archive_manifest,
        (original_preregistration, recovery_preregistration),
        preflight_path,
        required_rounds=2,
        systems_per_round=6,
    )
    if audit.route_decision != "route_a":
        raise ValueError(
            f"{audit.decision_reason}; task 260.4 Route B adapter must be used"
        )
    root_payload = json.loads(root_adjudication.read_text(encoding="utf-8"))
    root_result_hash = root_payload.get("report_hash")
    if not isinstance(root_result_hash, str) or len(root_result_hash) != 64:
        raise ValueError("latest negative adjudication has no valid report_hash")
    mechanisms = {
        "1": "noise_conditioned_ensemble_sindy",
        "2": "spline_group_sparse_sindy",
    }
    adapter_config = MDBenchAdapterConfig(
        archive_manifest_path=archive_manifest.as_posix(),
        historical_metadata_paths=(
            original_preregistration.as_posix(),
            recovery_preregistration.as_posix(),
        ),
        root_adjudication_path=root_adjudication.as_posix(),
        root_adjudication_sha256=file_hash(root_adjudication),
        holdout_audit_path=Path(audit.output_path).as_posix(),
        holdout_audit_hash=_required_hash(audit.audit_hash, "holdout audit"),
        llm_config_path=llm_config.as_posix(),
        round_mechanisms=mechanisms,
    )
    designs: list[CampaignRoundDesign] = []
    for round_number, seeds in ((1, (131, 137, 139)), (2, (149, 151, 157))):
        panel = audit.selected_panels[str(round_number)]
        designs.append(
            CampaignRoundDesign(
                round_number=round_number,
                track=CampaignTrack.SCIENTIFIC_ML_METHOD,
                development_data_refs=tuple(
                    f"mdbench:ode:{system}:development"
                    for system in adapter_config.development_systems
                ),
                unseen_data_refs=tuple(
                    f"mdbench:ode:{system}:unseen" for system in panel
                ),
                seeds=seeds,
                candidate_mechanism_families=(mechanisms[str(round_number)],),
                primary_metric="failure_aware_snr20_relative_improvement",
                acceptance_criteria=(
                    "development paired median improvement >= 15 percent",
                    "candidate and Operon clean/noisy cells succeed across three seeds",
                    "unseen system-bootstrap 95 percent CI lower bound > 0",
                    "three frozen ablations and idempotent one-command rerun pass",
                ),
                max_wall_time_seconds=10_800,
            )
        )
    return CampaignSpec(
        campaign_id=campaign_id,
        project_id=project_id,
        policy=CampaignPolicy.FAST_CCFB,
        adapter_id=MDBenchCampaignAdapter.adapter_id,
        adapter_config=adapter_config.model_dump(mode="json"),
        deadline=deadline,
        pivot_after_hours=72,
        min_experimental_rounds=2,
        root_result_hash=root_result_hash,
        root_evidence_refs=(
            root_adjudication.as_posix(),
            original_preregistration.as_posix(),
            recovery_preregistration.as_posix(),
            Path(audit.output_path).as_posix(),
        ),
        round_designs=tuple(designs),
    )


def _resolve_adapter(
    spec: CampaignSpec,
    evidence_root: Path,
) -> DevelopmentFixtureCampaignAdapter | MDBenchCampaignAdapter:
    if spec.adapter_id == DevelopmentFixtureCampaignAdapter.adapter_id:
        return DevelopmentFixtureCampaignAdapter(evidence_root)
    if spec.adapter_id == MDBenchCampaignAdapter.adapter_id:
        return MDBenchCampaignAdapter(evidence_root, spec.adapter_config)
    raise ValueError(f"campaign adapter is not installed: {spec.adapter_id}")


def _required_existing_path(label: str, path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError(f"{label} is missing: {resolved}")
    return resolved


def _required_hash(value: str | None, label: str) -> str:
    if value is None:
        raise ValueError(f"{label} has no content hash")
    return value


def _echo_mechanism_development(result: MechanismDevelopmentManifest) -> None:
    typer.echo(f"run_id={result.run_id}")
    typer.echo(f"status={result.status.value}")
    typer.echo(f"manifest_hash={result.manifest_hash}")
    typer.echo(f"proposal_hash={result.proposal_hash}")
    typer.echo(f"generated_source_sha256={result.generated_source_sha256}")
    typer.echo(f"round_freeze_hash={result.round_freeze_hash}")
    typer.echo(f"development_screen_hash={result.development_screen_hash}")
    typer.echo("confirmatory_payload_executed=false")
    typer.echo("scientific_result_created=false")
    typer.echo("external_submission_authorized=false")


def _echo_mechanism_confirmatory(
    result: MechanismConfirmatoryManifest,
) -> None:
    typer.echo(f"run_id={result.run_id}")
    typer.echo(f"status={result.status.value}")
    typer.echo(f"manifest_hash={result.manifest_hash}")
    typer.echo(f"endpoint_hash={result.endpoint_hash}")
    typer.echo(
        f"scientific_projection_hash={result.scientific_projection_hash}"
    )
    typer.echo(f"scientific_outcome={result.scientific_outcome.value}")
    typer.echo(f"journal_lineage_hash={result.journal_lineage_hash}")
    typer.echo(f"provenance_bundle_hash={result.provenance_bundle_hash}")
    typer.echo(f"reproduction_report_hash={result.reproduction_report_hash}")
    typer.echo(f"rollback_report_hash={result.rollback_report_hash}")
    typer.echo("confirmatory_results_revealed=true")
    typer.echo("scientific_result_created=true")
    typer.echo("external_submission_authorized=false")


def _echo_mechanism_paper(result: MechanismPaperBuildResult) -> None:
    typer.echo(f"package_dir={result.package_dir}")
    typer.echo(f"status={result.status.value}")
    typer.echo(f"manifest_hash={result.manifest_hash}")
    typer.echo(f"endpoint_hash={result.endpoint_hash}")
    typer.echo(f"manuscript_path={result.manuscript_path}")
    typer.echo(f"pdf_path={result.pdf_path}")
    typer.echo(f"paper_quality_passed={str(result.paper_quality_passed).lower()}")
    typer.echo(
        "claim_coverage_complete="
        f"{str(result.claim_coverage_complete).lower()}"
    )
    typer.echo("submission_readiness_granted=false")
    typer.echo("external_submission_authorized=false")


def _parse_deadline(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("deadline must be an ISO date or datetime") from exc
    if parsed.tzinfo is None:
        if "T" in value or " " in value:
            parsed = parsed.replace(tzinfo=_SHANGHAI_TIMEZONE)
        else:
            parsed = datetime.combine(
                parsed.date(),
                time(23, 59, 59),
                tzinfo=_SHANGHAI_TIMEZONE,
            )
    return parsed


def _echo_result(result: object) -> None:
    for name in (
        "campaign_dir",
        "manifest_path",
        "outcome",
        "stage",
        "completed_round_count",
        "experimental_round_count",
        "human_intervention_count",
        "current_round_id",
    ):
        value = getattr(result, name)
        if hasattr(value, "value"):
            value = value.value
        typer.echo(f"{name}={value}")


def _echo_sprint_result(result: object) -> None:
    for name in (
        "sprint_dir",
        "outcome",
        "stage",
        "selected_candidate_id",
        "selected_program_id",
        "endpoint_passed",
        "autonomy_level",
        "manuscript_path",
        "manuscript_pdf_path",
        "manifest_path",
    ):
        value = getattr(result, name)
        if hasattr(value, "value"):
            value = value.value
        typer.echo(f"{name}={value}")
    typer.echo("external_submission_authorized=false")
