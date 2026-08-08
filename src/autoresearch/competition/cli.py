"""Typer commands for the competition-first research service."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from autoresearch.competition.autonomous_development import (
    AutonomousDevelopmentError,
    build_autonomous_development_search_package,
)
from autoresearch.competition.autonomous_engine import (
    AutonomousBranchEngineError,
    build_autonomous_branch_engine_package,
)
from autoresearch.competition.autonomous_recovery import (
    AutonomousRecoveryError,
    freeze_autonomous_mdbench_research_plan,
)
from autoresearch.competition.final_research_report import (
    FinalResearchReportError,
    materialize_final_research_report,
)
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
from autoresearch.competition.official_lineage import (
    LINEAGE_STAGES,
    OfficialLineageConfig,
    OfficialLineageError,
    run_lineage_stage,
)
from autoresearch.competition.preregistration import (
    MDBenchPreregistrationError,
    preregister_mdbench_gate_a,
)
from autoresearch.competition.recovery import (
    MDBenchRecoveryError,
    preregister_mdbench_gate_a_recovery,
)
from autoresearch.competition.route_p2_paradigm_audit import (
    RouteP2AuditError,
    run_route_p2_paradigm_audit,
)
from autoresearch.competition.scientific_contract_harness import (
    ScientificContractHarnessError,
    build_scientific_contract_harness_package,
)
from autoresearch.competition.scientific_contract_recovery import (
    ScientificContractRecoveryError,
    freeze_scientific_contract_recovery_plan,
)
from autoresearch.competition.sentinel_identifiability import (
    SentinelIdentifiabilityError,
    freeze_sentinel_identifiability_erratum,
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


@competition_mdbench_app.command("autonomous-plan")
def competition_mdbench_autonomous_plan(
    archive_manifest: Annotated[
        Path,
        typer.Option("--archive-manifest", help="Verified official archive manifest."),
    ] = Path("runs/competition/mdbench-official/data/archive-manifest.json"),
    parent_matrix: Annotated[
        Path,
        typer.Option("--parent-matrix", help="Frozen matrix from the first formal cycle."),
    ] = Path("runs/competition/mdbench-official/gate-a-preregistration.json"),
    parent_report: Annotated[
        Path,
        typer.Option("--parent-report", help="Hash-valid first-cycle negative report."),
    ] = Path("runs/competition/mdbench-official/gate-a/gate-a-adjudication.json"),
    recovery_preregistration: Annotated[
        Path,
        typer.Option(
            "--recovery-preregistration",
            help="Hash-valid result-blind recovery contract.",
        ),
    ] = Path("runs/competition/mdbench-recovery/gate-a-recovery-preregistration.json"),
    recovery_matrix: Annotated[
        Path,
        typer.Option("--recovery-matrix", help="Frozen matrix from the recovery cycle."),
    ] = Path("runs/competition/mdbench-recovery/gate-a-recovery-matrix.json"),
    recovery_report: Annotated[
        Path,
        typer.Option("--recovery-report", help="Hash-valid recovery-cycle negative report."),
    ] = Path("runs/competition/mdbench-recovery/gate-a/gate-a-adjudication.json"),
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Result-free autonomous planning package."),
    ] = Path("runs/competition/mdbench-autonomous-recovery-plan"),
    timeout_seconds: Annotated[
        int,
        typer.Option("--timeout-seconds", min=1, help="Per-source live retrieval timeout."),
    ] = 20,
) -> None:
    """Freeze autonomous origin, source, search, and sealed-panel commitments."""

    try:
        plan = freeze_autonomous_mdbench_research_plan(
            archive_manifest,
            parent_matrix,
            parent_report,
            recovery_preregistration,
            recovery_matrix,
            recovery_report,
            output_dir,
            timeout_seconds=timeout_seconds,
        )
    except (AutonomousRecoveryError, OSError, ValidationError) as exc:
        typer.echo(f"[BLOCKED] mdbench_autonomous_plan: {exc}")
        raise typer.Exit(code=2) from exc
    typer.echo(f"[OK] autonomous_plan: {plan.output_path}")
    typer.echo(f"[OK] plan_hash: {plan.plan_hash}")
    typer.echo(f"[OK] primary_source_snapshots: {len(plan.evidence_sources)}")
    typer.echo(f"[OK] development_systems: {len(plan.development_panel.systems)}")
    typer.echo(
        f"[OK] sealed_confirmation_hash: {plan.confirmation_commitment.panel_hash}"
    )
    typer.echo(f"[OK] generated_candidates: {plan.generated_candidate_count}")
    typer.echo(f"[OK] result_records: {plan.result_record_count}")
    typer.echo(f"[OK] manuscripts: {plan.manuscript_count}")
    typer.echo(f"[OK] next_required_task: {plan.next_required_task}")


@competition_mdbench_app.command("autonomous-generate")
def competition_mdbench_autonomous_generate(
    plan: Annotated[
        Path,
        typer.Option(
            "--plan",
            help="Hash-valid public autonomous-research-plan.json from Task 265.1.",
        ),
    ] = Path(
        "runs/competition/mdbench-autonomous-recovery-plan/"
        "autonomous-research-plan.json"
    ),
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            help="Immutable literature/model/source/Harness preflight package.",
        ),
    ] = Path("runs/competition/mdbench-autonomous-branch-engine"),
    config: Annotated[
        Path,
        typer.Option("--config", help="Provider-neutral system configuration."),
    ] = Path("config.yaml"),
    env_file: Annotated[
        Path,
        typer.Option(
            "--env-file",
            help="Local credential environment file; secret values are never persisted.",
        ),
    ] = Path(".env"),
    timeout_seconds: Annotated[
        int,
        typer.Option("--timeout-seconds", min=1, help="Per-model-call timeout."),
    ] = 120,
    source_timeout_seconds: Annotated[
        int,
        typer.Option(
            "--source-timeout-seconds",
            min=1,
            help="Per-primary-source refresh timeout.",
        ),
    ] = 20,
) -> None:
    """Generate eight original exact-code branches and run bounded capability Harnesses."""

    try:
        package = build_autonomous_branch_engine_package(
            plan,
            output_dir,
            config_path=config,
            env_path=env_file,
            timeout_seconds=timeout_seconds,
            source_timeout_seconds=source_timeout_seconds,
        )
    except (AutonomousBranchEngineError, OSError, ValidationError) as exc:
        typer.echo(f"[BLOCKED] mdbench_autonomous_generate: {exc}")
        raise typer.Exit(code=2) from exc
    typer.echo(f"[OK] autonomous_branch_package: {package.output_path}")
    typer.echo(f"[OK] package_hash: {package.package_hash}")
    typer.echo(f"[OK] current_primary_sources: {len(package.literature_snapshots)}")
    typer.echo(f"[OK] model_interactions: {package.model_interaction_count}")
    typer.echo(f"[OK] exact_code_candidates: {package.generated_candidate_count}")
    typer.echo(f"[OK] mechanism_families: {package.mechanism_family_count}")
    typer.echo(f"[OK] capability_gate: {str(package.capability_gate_passed).lower()}")
    typer.echo(f"[OK] provenance_gate: {str(package.provenance_gate_passed).lower()}")
    typer.echo(
        "[OK] development_execution_authorized: "
        f"{str(package.development_execution_authorized).lower()}"
    )
    typer.echo("[OK] official_development_results: 0")
    typer.echo("[BLOCKED] confirmation_access: false")
    typer.echo("[BLOCKED] publication_ready: false")
    if not package.development_execution_authorized:
        raise typer.Exit(code=2)


@competition_mdbench_app.command("autonomous-search")
def competition_mdbench_autonomous_search(
    plan: Annotated[
        Path,
        typer.Option("--plan", help="Hash-valid Task 265.1 public plan."),
    ] = Path(
        "runs/competition/mdbench-autonomous-recovery-plan/"
        "autonomous-research-plan.json"
    ),
    branch_engine: Annotated[
        Path,
        typer.Option(
            "--branch-engine",
            help="Hash-valid Task 265.2 autonomous-branch-engine-package.json.",
        ),
    ] = Path(
        "runs/competition/mdbench-autonomous-branch-engine/"
        "autonomous-branch-engine-package.json"
    ),
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Append-only Task 265.3 development ledger."),
    ] = Path("runs/competition/mdbench-autonomous-development"),
    image: Annotated[
        str,
        typer.Option("--image", help="Pinned local MDBench scientific image."),
    ] = "autoresearch-mdbench:task260",
    config: Annotated[
        Path,
        typer.Option("--config", help="Provider-neutral system configuration."),
    ] = Path("config.yaml"),
    env_file: Annotated[
        Path,
        typer.Option("--env-file", help="Local credential file; secrets are never persisted."),
    ] = Path(".env"),
    timeout_seconds: Annotated[
        int,
        typer.Option("--timeout-seconds", min=1, help="Per-model intervention timeout."),
    ] = 180,
) -> None:
    """Run two-generation public-panel search and freeze one exact implementation."""

    try:
        package = build_autonomous_development_search_package(
            plan,
            branch_engine,
            output_dir,
            image=image,
            config_path=config,
            env_path=env_file,
            model_timeout_seconds=timeout_seconds,
        )
    except (AutonomousDevelopmentError, OSError, ValidationError) as exc:
        typer.echo(f"[BLOCKED] mdbench_autonomous_search: {exc}")
        raise typer.Exit(code=2) from exc
    selected = next(
        item
        for item in reversed(package.summaries)
        if item.candidate_id == package.selection.selected_candidate_id
        and item.stage == "full"
    )
    typer.echo(f"[OK] autonomous_development_package: {package.output_path}")
    typer.echo(f"[OK] package_hash: {package.package_hash}")
    typer.echo(f"[OK] candidate_results: {package.official_development_result_count}")
    typer.echo(f"[OK] baseline_results: {package.baseline_result_count}")
    typer.echo(f"[OK] searched_candidates: {len(package.candidates)}")
    typer.echo(f"[OK] mechanism_cycles: {package.executed_mechanism_cycle_count}")
    typer.echo(f"[OK] selected_candidate: {package.selection.selected_candidate_id}")
    typer.echo(
        "[OK] selected_operon_relative_system_median: "
        f"{selected.operon_system_median_relative_improvement}"
    )
    typer.echo(f"[OK] decision: {package.selection.decision}")
    typer.echo(
        "[OK] search_freeze_receipt: "
        f"{str(package.search_freeze_receipt_created).lower()}"
    )
    typer.echo("[BLOCKED] significance_claim: development_only")
    typer.echo("[BLOCKED] publication_ready: false")


@competition_mdbench_app.command("scientific-contract-plan")
def competition_mdbench_scientific_contract_plan(
    development_package: Annotated[
        Path,
        typer.Option(
            "--development-package",
            help="Hash-valid negative Task 265.3 autonomous-development package.",
        ),
    ] = Path(
        "runs/manual-live/task2653-autonomous-development-v1/"
        "autonomous-development-search-package.json"
    ),
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Result-blind Task 266.1 plan directory."),
    ] = Path("runs/competition/mdbench-scientific-contract-recovery-plan"),
    image: Annotated[
        str,
        typer.Option("--image", help="Pinned local MDBench baseline image."),
    ] = "autoresearch-mdbench:task260",
    timeout_seconds: Annotated[
        int,
        typer.Option("--timeout-seconds", min=1, help="Per-source retrieval timeout."),
    ] = 30,
) -> None:
    """Freeze fit/freeze/predict schemas, sentinels, baselines, and budgets."""

    try:
        plan = freeze_scientific_contract_recovery_plan(
            development_package,
            output_dir,
            image=image,
            timeout_seconds=timeout_seconds,
        )
    except (ScientificContractRecoveryError, OSError, ValidationError) as exc:
        typer.echo(f"[BLOCKED] mdbench_scientific_contract_plan: {exc}")
        raise typer.Exit(code=2) from exc
    typer.echo(f"[OK] scientific_contract_plan: {plan.output_path}")
    typer.echo(f"[OK] plan_hash: {plan.plan_hash}")
    typer.echo(f"[OK] primary_sources: {len(plan.sources)}")
    typer.echo(f"[OK] sentinel_fixtures: {len(plan.sentinels)}")
    typer.echo(f"[OK] domain_baselines: {len(plan.baselines)}")
    typer.echo(f"[OK] baseline_probe_hash: {plan.baseline_probe.probe_hash}")
    typer.echo("[OK] new_official_development_results: 0")
    typer.echo("[OK] confirmation_reads: 0")
    typer.echo("[AUTHORIZED] next_task: 266.2_harness_implementation_only")
    typer.echo("[BLOCKED] official_development_execution: false")
    typer.echo("[BLOCKED] significance_claim: no_new_result")
    typer.echo("[BLOCKED] publication_ready: false")


@competition_mdbench_app.command("sentinel-identifiability-erratum")
def competition_mdbench_sentinel_identifiability_erratum(
    plan: Annotated[
        Path,
        typer.Option(
            "--plan",
            help="Hash-valid result-blind Task 266.1 scientific-contract plan.",
        ),
    ] = Path(
        "runs/manual-live/task2661-scientific-contract-recovery-plan-v1/"
        "scientific-contract-recovery-plan.json"
    ),
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Result-blind Task 266.1.1 erratum."),
    ] = Path("runs/competition/mdbench-sentinel-identifiability-erratum"),
    image: Annotated[
        str,
        typer.Option("--image", help="Pinned local scientific-runtime image."),
    ] = "autoresearch-mdbench:task260",
) -> None:
    """Audit term identifiability and correct only the aliased 2D sentinel."""

    try:
        erratum = freeze_sentinel_identifiability_erratum(
            plan,
            output_dir,
            image=image,
        )
    except (SentinelIdentifiabilityError, OSError, ValidationError) as exc:
        typer.echo(f"[BLOCKED] mdbench_sentinel_identifiability_erratum: {exc}")
        raise typer.Exit(code=2) from exc
    typer.echo(f"[OK] sentinel_identifiability_erratum: {erratum.output_path}")
    typer.echo(f"[OK] erratum_hash: {erratum.erratum_hash}")
    typer.echo(f"[OK] parent_plan_hash: {erratum.parent_plan_hash}")
    typer.echo(
        "[OK] original_non_identifiable: "
        f"{','.join(erratum.probe.original_non_identifiable_ids)}"
    )
    typer.echo(
        "[OK] corrected_all_identifiable: "
        f"{str(erratum.probe.corrected_all_identifiable).lower()}"
    )
    typer.echo("[OK] new_official_development_results: 0")
    typer.echo("[OK] candidates_and_model_interactions: 0")
    typer.echo("[OK] confirmation_reads: 0")
    typer.echo("[AUTHORIZED] next_task: 266.2_harness_implementation_only")
    typer.echo("[BLOCKED] official_development_execution: false")
    typer.echo("[BLOCKED] publication_ready: false")


@competition_mdbench_app.command("scientific-contract-harness")
def competition_mdbench_scientific_contract_harness(
    plan: Annotated[
        Path,
        typer.Option("--plan", help="Hash-valid result-blind Task 266.1 plan."),
    ] = Path(
        "runs/manual-live/task2661-scientific-contract-recovery-plan-v1/"
        "scientific-contract-recovery-plan.json"
    ),
    erratum: Annotated[
        Path,
        typer.Option("--erratum", help="Hash-valid Task 266.1.1 sentinel erratum."),
    ] = Path(
        "runs/manual-live/task26611-sentinel-identifiability-erratum-v1/"
        "sentinel-identifiability-erratum.json"
    ),
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Task 266.2 exact-source Harness package."),
    ] = Path("runs/competition/mdbench-scientific-contract-harness"),
    config_path: Annotated[
        Path,
        typer.Option("--config", help="Provider-neutral model configuration."),
    ] = Path("config.yaml"),
    env_path: Annotated[
        Path,
        typer.Option("--env", help="Local provider credentials; never persisted."),
    ] = Path(".env"),
) -> None:
    """Let the configured model author and repair a synthetic-gated scientific method."""

    try:
        package = build_scientific_contract_harness_package(
            plan,
            erratum,
            output_dir,
            config_path=config_path,
            env_path=env_path,
        )
    except (ScientificContractHarnessError, OSError, ValidationError) as exc:
        typer.echo(f"[BLOCKED] mdbench_scientific_contract_harness: {exc}")
        raise typer.Exit(code=2) from exc
    typer.echo(f"[OK] scientific_contract_harness: {package.output_path}")
    typer.echo(f"[OK] package_hash: {package.package_hash}")
    typer.echo(f"[OK] model_revisions: {len(package.revisions)}")
    typer.echo(
        "[OK] synthetic_contract_gate: "
        f"{str(package.synthetic_contract_gate_passed).lower()}"
    )
    typer.echo("[OK] new_official_development_results_and_reads: 0/0")
    typer.echo("[OK] confirmation_identity_and_result_reads: 0/0")
    if package.task_266_3_authorized:
        typer.echo("[AUTHORIZED] next_task: 266.3_bounded_development_search")
    else:
        typer.echo("[BLOCKED] next_task: 266.2_model_only_repair_budget_exhausted")
    typer.echo("[BLOCKED] significance_claim: synthetic_only")
    typer.echo("[BLOCKED] publication_ready: false")


@competition_mdbench_app.command("lineage-stage")
def competition_mdbench_lineage_stage(
    lineage_id: Annotated[
        str,
        typer.Option("--lineage-id", help="Preregistered lineage identifier."),
    ],
    stage: Annotated[
        str,
        typer.Option("--stage", help=f"One of: {', '.join(LINEAGE_STAGES)}."),
    ],
    work_dir: Annotated[
        Path | None,
        typer.Option("--work-dir", help="Lineage directory; defaults to runs/manual-live/<id>."),
    ] = None,
    plan: Annotated[
        Path,
        typer.Option("--plan", help="Hash-valid result-blind Task 266.1 frozen plan."),
    ] = Path(
        "runs/manual-live/task2661-scientific-contract-recovery-plan-v1/"
        "scientific-contract-recovery-plan.json"
    ),
    autonomous_plan: Annotated[
        Path,
        typer.Option("--autonomous-plan", help="Hash-valid Task 265.1 autonomous plan."),
    ] = Path(
        "runs/manual-live/task2651-autonomous-recovery-plan-v1/autonomous-research-plan.json"
    ),
    data_root: Annotated[
        Path,
        typer.Option("--data-root", help="Prepared official MDBench data root."),
    ] = Path("runs/manual-live/task259-mdbench-official-v1/data/prepared/processed-9fe483c64ad6"),
    prior_run_dir: Annotated[
        list[Path] | None,
        typer.Option("--prior-run-dir", help="Prior lineage for plan evidence; repeatable."),
    ] = None,
    decided_by: Annotated[
        str,
        typer.Option("--decided-by", help="Who recorded the approval, for the approve stage."),
    ] = "operator",
    notes: Annotated[
        str,
        typer.Option("--notes", help="Reviewer's own approval reasoning, for approve."),
    ] = "",
    package_output_dir: Annotated[
        Path | None,
        typer.Option(
            "--package-output-dir",
            help="Write the adjudication package here instead of into the lineage.",
        ),
    ] = None,
) -> None:
    """Drive one stage of a preregistered official lineage under its frozen budget."""

    if stage not in LINEAGE_STAGES:
        typer.echo(f"[BLOCKED] unknown_stage: {stage}")
        raise typer.Exit(code=2)
    config = OfficialLineageConfig(
        lineage_id=lineage_id,
        work_dir=work_dir or Path("runs/manual-live") / lineage_id,
        frozen_plan_path=plan,
        autonomous_plan_path=autonomous_plan,
        data_root=data_root,
        prior_run_dirs=tuple(prior_run_dir or ()),
    )
    try:
        report = run_lineage_stage(
            config,
            stage=stage,
            decided_by=decided_by,
            notes=notes,
            package_output_dir=package_output_dir,
        )
    except (OfficialLineageError, RuntimeError, OSError, ValidationError) as exc:
        typer.echo(f"[BLOCKED] lineage_stage_{stage}: {exc}")
        raise typer.Exit(code=2) from exc
    for line in report.lines:
        typer.echo(line)
    typer.echo(f"[OK] lineage_stage: {report.stage}")
    if report.package_path is not None:
        typer.echo(f"[OK] package: {report.package_path}")
        typer.echo(
            "[OK] search_freeze_receipt: "
            f"{str(bool(report.search_freeze_receipt_issued)).lower()}"
        )


@competition_mdbench_app.command("final-report")
def competition_mdbench_final_report(
    lineage_dir: Annotated[
        Path,
        typer.Option(
            "--lineage-dir",
            help="Completed lineage containing plan, contract, package, and outcome.",
        ),
    ],
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            help="Separate derived-report directory; defaults to <lineage>/final-report.",
        ),
    ] = None,
    compile_pdf: Annotated[
        bool,
        typer.Option(
            "--compile-pdf/--no-compile-pdf",
            help="Compile with XeLaTeX and verify extracted PDF text.",
        ),
    ] = True,
) -> None:
    """Materialize observed results only after every evidence binding passes."""

    try:
        report = materialize_final_research_report(
            lineage_dir=lineage_dir,
            output_dir=output_dir,
            compile_pdf=compile_pdf,
        )
    except (FinalResearchReportError, OSError, ValidationError) as exc:
        typer.echo(f"[BLOCKED] final_research_report: {exc}")
        raise typer.Exit(code=2) from exc
    destination = Path(report.output_path).parent
    typer.echo(f"[OK] final_research_report: {report.output_path}")
    typer.echo(f"[OK] report_hash: {report.report_hash}")
    typer.echo(f"[OK] markdown: {destination / 'final-research-report.md'}")
    typer.echo(f"[OK] latex: {destination / 'final-research-report.tex'}")
    if compile_pdf:
        typer.echo(f"[OK] pdf: {destination / 'final-research-report.pdf'}")
    typer.echo("[BLOCKED] publication_ready: false")


@competition_mdbench_app.command("route-p2-paradigm-audit")
def competition_mdbench_route_p2_paradigm_audit(
    preregistration_hash: Annotated[
        str,
        typer.Option(
            "--preregistration-hash",
            help="Hash of the frozen Task 267.6 dual-route preregistration.",
        ),
    ],
    plan: Annotated[
        Path,
        typer.Option("--plan", help="Hash-valid result-blind Task 266.1 plan."),
    ] = Path(
        "runs/manual-live/task2661-scientific-contract-recovery-plan-v1/"
        "scientific-contract-recovery-plan.json"
    ),
    erratum: Annotated[
        Path,
        typer.Option("--erratum", help="Hash-valid Task 266.1.1 sentinel erratum."),
    ] = Path(
        "runs/manual-live/task26611-sentinel-identifiability-erratum-v1/"
        "sentinel-identifiability-erratum.json"
    ),
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Route P2 comparison package."),
    ] = Path("runs/competition/mdbench-route-p2-paradigm-audit"),
    matched_model_call_budget: Annotated[
        int,
        typer.Option(
            "--matched-budget",
            help="Identical model-call budget spent by BOTH arms.",
        ),
    ] = 4,
    config_path: Annotated[
        Path,
        typer.Option("--config", help="Provider-neutral model configuration."),
    ] = Path("config.yaml"),
    env_path: Annotated[
        Path,
        typer.Option("--env", help="Local provider credentials; never persisted."),
    ] = Path(".env"),
) -> None:
    """Compare LLM evolution against independent sampling under a matched budget."""

    try:
        package = run_route_p2_paradigm_audit(
            output_dir=output_dir,
            preregistration_hash=preregistration_hash,
            plan_path=plan,
            erratum_path=erratum,
            matched_model_call_budget=matched_model_call_budget,
            config_path=config_path,
            env_path=env_path,
        )
    except (RouteP2AuditError, ScientificContractHarnessError, OSError, ValidationError) as exc:
        typer.echo(f"[BLOCKED] mdbench_route_p2_paradigm_audit: {exc}")
        raise typer.Exit(code=2) from exc

    typer.echo(f"[OK] route_p2_paradigm_audit: {package.output_path}")
    typer.echo(f"[OK] package_hash: {package.package_hash}")
    typer.echo(f"[OK] matched_model_call_budget: {package.matched_model_call_budget}")
    typer.echo(f"[OK] reasoning_mode: {package.reasoning_mode}")
    for arm in package.arms:
        typer.echo(
            f"[OK] arm {arm.arm_id}: calls={arm.model_call_count} "
            f"generations={arm.generations} selected=#{arm.selected_proposal_index}"
        )
    typer.echo(
        "[RESULT] median_paired_effect: "
        f"{package.median_paired_effect:.6f} "
        f"CI95=[{package.bootstrap_lower:.6f}, {package.bootstrap_upper:.6f}]"
    )
    typer.echo(
        "[RESULT] strata: "
        f"ode={package.ode_stratum_median} pde={package.pde_stratum_median}"
    )
    typer.echo("[NOTE] positive effect means parent-conditioned evolution had lower loss")
    typer.echo("[OK] new_official_development_results_and_reads: 0/0")
    typer.echo("[BLOCKED] significance_claim: exploratory_synthetic_only")
    typer.echo("[BLOCKED] publication_ready: false")


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
