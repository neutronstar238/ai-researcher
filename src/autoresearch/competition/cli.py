"""Typer commands for the competition-first research service."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from autoresearch.competition.gate_a import (
    GateAAdjudicationError,
    adjudicate_mdbench_gate_a,
)
from autoresearch.competition.manifest import (
    load_cycle_manifest,
    write_json_model,
)
from autoresearch.competition.models import (
    CapabilityGrant,
    CompetitionRunSpec,
    CycleResult,
    MDBenchArchiveManifest,
    MDBenchOfficialPreflight,
    TopicMode,
)
from autoresearch.competition.official import run_mdbench_official_preflight
from autoresearch.competition.official_data import (
    MDBenchDataError,
    download_mdbench_processed_archive,
    prepare_mdbench_official_data,
)
from autoresearch.competition.official_execution import (
    MDBenchExecutionError,
    execute_mdbench_matrix,
)
from autoresearch.competition.preregistration import (
    MDBenchPreregistrationError,
    preregister_mdbench_gate_a,
)
from autoresearch.competition.recovery import (
    MDBenchRecoveryError,
    preregister_mdbench_gate_a_recovery,
)
from autoresearch.competition.service import ResearchCycleService, load_capability_grant

competition_app = typer.Typer(
    help="Run the resumable, competition-first unattended research loop.",
    no_args_is_help=True,
)
competition_access_app = typer.Typer(
    help="Create bounded capability grants without storing credential values.",
    no_args_is_help=True,
)
competition_mdbench_app = typer.Typer(
    help="Inspect and run the pinned official MDBench benchmark path.",
    no_args_is_help=True,
)
competition_app.add_typer(competition_access_app, name="access")
competition_app.add_typer(competition_mdbench_app, name="mdbench")


@competition_mdbench_app.command("preflight")
def competition_mdbench_preflight(
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Preflight evidence and access-request directory."),
    ] = Path("runs/competition/mdbench-preflight"),
    timeout_seconds: Annotated[
        int,
        typer.Option("--timeout-seconds", min=1, help="Network/container probe timeout."),
    ] = 20,
) -> None:
    """Verify revision, license, archive metadata, and container readiness."""

    report = run_mdbench_official_preflight(
        output_dir,
        timeout_seconds=timeout_seconds,
    )
    typer.echo(f"[OK] mdbench_preflight: {report.output_path}")
    typer.echo(f"[OK] pinned_revision_available: {str(report.revision_available).lower()}")
    typer.echo(f"[OK] container_available: {str(report.container_available).lower()}")
    typer.echo(f"[OK] dataset_license: {report.dataset_license or 'missing'}")
    typer.echo(f"[OK] access_request_count: {len(report.access_request_ids)}")
    if not report.ready_to_execute:
        for blocker in report.blockers:
            typer.echo(f"[BLOCKED] {blocker}")
        raise typer.Exit(code=2)


@competition_mdbench_app.command("prepare")
def competition_mdbench_prepare(
    preflight_report: Annotated[
        Path,
        typer.Option(
            "--preflight-report",
            help="Successful official-preflight.json produced by mdbench preflight.",
        ),
    ] = Path("runs/competition/mdbench-preflight/official-preflight.json"),
    archive_path: Annotated[
        Path,
        typer.Option(
            "--archive-path",
            help="Resumable processed.zip destination or an existing complete archive.",
        ),
    ] = Path("runs/competition/mdbench-official/data/processed.zip"),
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Verified extraction and manifest directory."),
    ] = Path("runs/competition/mdbench-official/data"),
    timeout_seconds: Annotated[
        int,
        typer.Option("--timeout-seconds", min=1, help="Per-download-attempt timeout."),
    ] = 60,
) -> None:
    """Download, verify, safely extract, and inventory official MDBench data."""

    try:
        preflight = MDBenchOfficialPreflight.model_validate_json(
            preflight_report.read_text(encoding="utf-8")
        )
        archive = download_mdbench_processed_archive(
            archive_path,
            preflight,
            timeout_seconds=timeout_seconds,
        )
        if preflight.dataset_license is None:
            raise MDBenchDataError("preflight does not contain a dataset license")
        manifest = prepare_mdbench_official_data(
            archive,
            output_dir,
            dataset_license=preflight.dataset_license,
        )
    except (MDBenchDataError, OSError, ValidationError) as exc:
        typer.echo(f"[BLOCKED] mdbench_prepare: {exc}")
        raise typer.Exit(code=2) from exc
    typer.echo(f"[OK] mdbench_archive_manifest: {manifest.output_path}")
    typer.echo(f"[OK] official_ode_systems: {len(manifest.ode_systems)}")
    typer.echo(f"[OK] official_pde_systems: {len(manifest.pde_systems)}")
    typer.echo(f"[OK] official_npz_artifacts: {len(manifest.artifacts)}")


@competition_mdbench_app.command("preregister")
def competition_mdbench_preregister(
    archive_manifest: Annotated[
        Path,
        typer.Option(
            "--archive-manifest",
            help="Verified archive-manifest.json produced by mdbench prepare.",
        ),
    ] = Path("runs/competition/mdbench-official/data/archive-manifest.json"),
    output: Annotated[
        Path,
        typer.Option("--output", help="Immutable pre-result experiment matrix JSON."),
    ] = Path("runs/competition/mdbench-official/gate-a-preregistration.json"),
) -> None:
    """Freeze systems, splits, methods, metrics, seeds, and budgets before results."""

    try:
        manifest = MDBenchArchiveManifest.model_validate_json(
            archive_manifest.read_text(encoding="utf-8")
        )
        matrix = preregister_mdbench_gate_a(manifest, output)
    except (MDBenchPreregistrationError, OSError, ValidationError) as exc:
        typer.echo(f"[BLOCKED] mdbench_preregister: {exc}")
        raise typer.Exit(code=2) from exc
    unseen_count = sum(case.evaluation_split == "unseen_test" for case in matrix.systems)
    typer.echo(f"[OK] mdbench_matrix: {matrix.output_path}")
    typer.echo(f"[OK] matrix_hash: {matrix.matrix_hash}")
    typer.echo(f"[OK] matrix_attempts: {len(matrix.attempts)}")
    typer.echo(f"[OK] unseen_test_systems: {unseen_count}")
    typer.echo(f"[OK] created_before_results: {str(matrix.created_before_results).lower()}")


@competition_mdbench_app.command("recover-preregister")
def competition_mdbench_recover_preregister(
    archive_manifest: Annotated[
        Path,
        typer.Option("--archive-manifest", help="Verified archive-manifest.json."),
    ] = Path("runs/competition/mdbench-official/data/archive-manifest.json"),
    parent_matrix: Annotated[
        Path,
        typer.Option("--parent-matrix", help="Frozen matrix from the closed parent cycle."),
    ] = Path("runs/competition/mdbench-official/gate-a-preregistration.json"),
    parent_report: Annotated[
        Path,
        typer.Option(
            "--parent-report",
            help="Hash-valid negative gate-a-adjudication.json from the parent cycle.",
        ),
    ] = Path("runs/competition/mdbench-official/gate-a/gate-a-adjudication.json"),
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Result-free recovery preregistration directory."),
    ] = Path("runs/competition/mdbench-recovery"),
) -> None:
    """Freeze a disjoint, literature-grounded recovery cycle before any result."""

    try:
        manifest = MDBenchArchiveManifest.model_validate_json(
            archive_manifest.read_text(encoding="utf-8")
        )
        preregistration, matrix = preregister_mdbench_gate_a_recovery(
            manifest,
            parent_matrix,
            parent_report,
            output_dir,
        )
    except (MDBenchRecoveryError, OSError, ValidationError) as exc:
        typer.echo(f"[BLOCKED] mdbench_recover_preregister: {exc}")
        raise typer.Exit(code=2) from exc
    unseen = tuple(
        f"{case.data_type}/{case.system_name}"
        for case in matrix.systems
        if case.evaluation_split == "unseen_test"
    )
    typer.echo(f"[OK] mdbench_recovery_preregistration: {preregistration.output_path}")
    typer.echo(f"[OK] recovery_hash: {preregistration.recovery_hash}")
    typer.echo(f"[OK] recovery_matrix: {matrix.output_path}")
    typer.echo(f"[OK] matrix_hash: {matrix.matrix_hash}")
    typer.echo(f"[OK] matrix_attempts: {len(matrix.attempts)}")
    typer.echo("[OK] candidate_method: weak_stability_sindy")
    typer.echo(f"[OK] fresh_unseen_systems: {','.join(unseen)}")
    typer.echo(f"[OK] created_before_results: {str(matrix.created_before_results).lower()}")


@competition_mdbench_app.command("execute")
def competition_mdbench_execute(
    matrix: Annotated[
        Path,
        typer.Option("--matrix", help="Frozen gate-a-preregistration.json."),
    ] = Path("runs/competition/mdbench-official/gate-a-preregistration.json"),
    archive_manifest: Annotated[
        Path,
        typer.Option("--archive-manifest", help="Verified archive-manifest.json."),
    ] = Path("runs/competition/mdbench-official/data/archive-manifest.json"),
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Hash-bound result/checkpoint directory."),
    ] = Path("runs/competition/mdbench-official/execution"),
    image: Annotated[
        str,
        typer.Option("--image", help="Versioned local Gate A container image."),
    ] = "autoresearch-mdbench-gate-a:f81813e",
    max_attempts: Annotated[
        int | None,
        typer.Option(
            "--max-attempts",
            min=1,
            help="Run at most this many pending cells; omit to drain the selection.",
        ),
    ] = None,
    attempt_id: Annotated[
        list[str] | None,
        typer.Option(
            "--attempt-id",
            help="Optional exact frozen attempt ID; repeat to select multiple cells.",
        ),
    ] = None,
) -> None:
    """Execute or resume the unchanged official matrix in disposable containers."""

    try:
        report = execute_mdbench_matrix(
            matrix,
            archive_manifest,
            output_dir,
            image=image,
            max_attempts=max_attempts,
            attempt_ids=attempt_id,
        )
    except (MDBenchExecutionError, OSError, ValidationError) as exc:
        typer.echo(f"[BLOCKED] mdbench_execute: {exc}")
        raise typer.Exit(code=2) from exc
    typer.echo(f"[OK] mdbench_execution_report: {report.output_path}")
    typer.echo(f"[OK] environment_hash: {report.environment.environment_hash}")
    typer.echo(f"[OK] terminal_attempts: {report.terminal_attempt_count}")
    typer.echo(f"[OK] succeeded: {report.succeeded_count}")
    typer.echo(f"[OK] failed: {report.failed_count}")
    typer.echo(f"[OK] timed_out: {report.timed_out_count}")
    typer.echo(f"[OK] pending: {report.pending_count}")
    typer.echo(f"[OK] complete: {str(report.complete).lower()}")


@competition_mdbench_app.command("evaluate")
def competition_mdbench_evaluate(
    matrix: Annotated[
        Path,
        typer.Option("--matrix", help="Frozen gate-a-preregistration.json."),
    ] = Path("runs/competition/mdbench-official/gate-a-preregistration.json"),
    execution_report: Annotated[
        Path,
        typer.Option(
            "--execution-report",
            help="Complete hash-bound execution-report.json.",
        ),
    ] = Path("runs/competition/mdbench-official/execution/execution-report.json"),
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Final Gate A JSON and Markdown directory."),
    ] = Path("runs/competition/mdbench-official/gate-a"),
) -> None:
    """Produce an immutable Gate A pass or credible negative result."""

    try:
        report = adjudicate_mdbench_gate_a(matrix, execution_report, output_dir)
    except (GateAAdjudicationError, OSError, ValidationError) as exc:
        typer.echo(f"[BLOCKED] mdbench_evaluate: {exc}")
        raise typer.Exit(code=2) from exc
    typer.echo(f"[OK] mdbench_gate_a_report: {report.output_path}")
    typer.echo(f"[OK] mdbench_gate_a_markdown: {report.markdown_path}")
    typer.echo(f"[OK] decision: {report.decision.value}")
    typer.echo(f"[OK] selected_baseline: {report.selected_baseline_method_id}")
    typer.echo(
        "[OK] bootstrap_ci95: "
        f"[{report.primary_comparison.bootstrap_ci95_lower:.6f}, "
        f"{report.primary_comparison.bootstrap_ci95_upper:.6f}]"
    )
    typer.echo(f"[OK] gate_b_allowed: {str(report.gate_b_allowed).lower()}")


@competition_app.command("run")
def competition_run(
    topic_mode: Annotated[
        str,
        typer.Option("--topic-mode", help="auto or seeded; auto is the default."),
    ] = TopicMode.AUTO.value,
    topic: Annotated[
        str | None,
        typer.Option("--topic", help="Optional topic constraint for seeded mode."),
    ] = None,
    guidance: Annotated[
        list[str] | None,
        typer.Option("--guidance", help="Optional guidance; repeat for multiple constraints."),
    ] = None,
    reference_uri: Annotated[
        list[str] | None,
        typer.Option("--reference-uri", help="Optional reference; repeat as needed."),
    ] = None,
    run_id: Annotated[
        str | None,
        typer.Option("--run-id", help="Stable path-safe ID used for checkpoint resume."),
    ] = None,
    project_id: Annotated[
        str,
        typer.Option("--project-id", help="Vault project ID."),
    ] = "competition-gate-a",
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Competition run root."),
    ] = Path("runs/competition"),
    vault: Annotated[
        Path,
        typer.Option("--vault", help="Obsidian vault root."),
    ] = Path("autoresearch-vault"),
    capability_grant: Annotated[
        Path | None,
        typer.Option("--capability-grant", help="Optional CapabilityGrant JSON."),
    ] = None,
    timeout_seconds: Annotated[
        int,
        typer.Option("--timeout-seconds", min=1, help="Per-experiment timeout."),
    ] = 30,
) -> None:
    """Run Gate A autonomously; optional topic input never bypasses gates."""

    try:
        mode = TopicMode(topic_mode)
    except ValueError as exc:
        raise typer.BadParameter("topic mode must be auto or seeded") from exc
    grant = load_capability_grant(capability_grant) if capability_grant else None
    payload: dict[str, object] = {
        "project_id": project_id,
        "topic_mode": mode,
        "topic": topic,
        "guidance": tuple(guidance or ()),
        "reference_uris": tuple(reference_uri or ()),
        "timeout_seconds": timeout_seconds,
        "capability_grant_id": grant.grant_id if grant is not None else None,
    }
    if run_id is not None:
        payload["run_id"] = run_id
    try:
        spec = CompetitionRunSpec.model_validate(payload)
    except ValidationError as exc:
        raise typer.BadParameter(str(exc)) from exc
    service = ResearchCycleService(
        output_root=output_dir,
        vault_root=vault,
        capability_grant=grant,
    )
    result = service.run(spec)
    _echo_result(result)


@competition_app.command("resume")
def competition_resume(
    cycle_dir: Annotated[Path, typer.Argument(help="Existing competition cycle directory.")],
    vault: Annotated[
        Path,
        typer.Option("--vault", help="Obsidian vault root."),
    ] = Path("autoresearch-vault"),
    capability_grant: Annotated[
        Path | None,
        typer.Option("--capability-grant", help="CapabilityGrant that satisfies a request."),
    ] = None,
) -> None:
    """Resume an interrupted or access-blocked cycle from its manifest."""

    grant = load_capability_grant(capability_grant) if capability_grant else None
    service = ResearchCycleService(
        output_root=cycle_dir.parent,
        vault_root=vault,
        capability_grant=grant,
    )
    _echo_result(service.resume(cycle_dir))


@competition_app.command("status")
def competition_status(
    cycle_dir: Annotated[Path, typer.Argument(help="Competition cycle directory.")],
) -> None:
    """Print persisted status without changing the cycle."""

    manifest = load_cycle_manifest(cycle_dir / "cycle-manifest.json")
    typer.echo(f"run_id={manifest.run_id}")
    typer.echo(f"stage={manifest.stage.value}")
    typer.echo(f"outcome={manifest.outcome.value}")
    typer.echo(f"attempts={len(manifest.attempts)}")
    typer.echo(f"human_intervention_count={manifest.human_intervention_count}")
    typer.echo(f"access_request_count={len(manifest.access_request_ids)}")
    typer.echo(f"release_eligible={str(manifest.release_eligible).lower()}")


@competition_app.command("export")
def competition_export(
    cycle_dir: Annotated[Path, typer.Argument(help="Completed competition cycle directory.")],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Local export root; this does not upload anything."),
    ] = Path("outputs/competition"),
) -> None:
    """Export required fields locally while preserving the submission gate."""

    service = ResearchCycleService(output_root=cycle_dir.parent)
    path = service.export(cycle_dir, output_dir)
    typer.echo(f"[OK] competition_export: {path}")
    payload = path.read_text(encoding="utf-8")
    if '"submission_ready": false' in payload:
        typer.echo("[BLOCKED] external_submission: evidence gate has not passed")


@competition_access_app.command("grant")
def competition_access_grant(
    output: Annotated[
        Path,
        typer.Option("--output", help="CapabilityGrant JSON output path."),
    ] = Path(".airesearcher/competition-capability-grant.json"),
    api_env_var: Annotated[
        list[str] | None,
        typer.Option("--api-env-var", help="Environment variable name only; repeat as needed."),
    ] = None,
    network_domain: Annotated[
        list[str] | None,
        typer.Option("--network-domain", help="Approved network domain; repeat as needed."),
    ] = None,
    dataset_license: Annotated[
        list[str] | None,
        typer.Option("--dataset-license", help="Approved dataset license identifier."),
    ] = None,
    max_cpu_hours: Annotated[
        float,
        typer.Option("--max-cpu-hours", min=0.0),
    ] = 1.0,
    max_gpu_hours: Annotated[
        float,
        typer.Option("--max-gpu-hours", min=0.0),
    ] = 0.0,
    max_storage_gb: Annotated[
        float,
        typer.Option("--max-storage-gb", min=0.0),
    ] = 1.0,
    max_cost_usd: Annotated[
        float,
        typer.Option("--max-cost-usd", min=0.0),
    ] = 0.0,
    valid_days: Annotated[
        int,
        typer.Option("--valid-days", min=1),
    ] = 7,
    allow_external_submission: Annotated[
        bool,
        typer.Option(
            "--allow-external-submission/--no-external-submission",
            help="Explicitly authorize or deny final external upload.",
        ),
    ] = False,
) -> None:
    """Create one reusable bounded grant; secret values are never accepted."""

    try:
        grant = CapabilityGrant(
            api_env_vars=tuple(api_env_var or ()),
            network_domains=tuple(network_domain or ()),
            dataset_licenses=tuple(dataset_license or ()),
            max_cpu_hours=max_cpu_hours,
            max_gpu_hours=max_gpu_hours,
            max_storage_gb=max_storage_gb,
            max_cost_usd=max_cost_usd,
            valid_until=datetime.now(timezone.utc) + timedelta(days=valid_days),
            allow_external_submission=allow_external_submission,
        )
    except ValidationError as exc:
        raise typer.BadParameter(str(exc)) from exc
    write_json_model(output, grant)
    typer.echo(f"[OK] capability_grant: {output}")
    typer.echo(f"[OK] grant_id: {grant.grant_id}")


def _echo_result(result: CycleResult) -> None:
    typer.echo(f"[OK] competition_cycle: {result.outcome.value}")
    typer.echo(f"[OK] manifest: {result.manifest_path}")
    typer.echo(f"[OK] human_intervention_count: {result.human_intervention_count}")
    typer.echo(f"[OK] access_request_count: {result.access_request_count}")
    typer.echo(f"[OK] release_eligible: {str(result.release_eligible).lower()}")
