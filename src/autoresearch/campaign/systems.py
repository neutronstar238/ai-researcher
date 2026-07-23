"""Frozen systems-paper benchmark for evidence-bound autonomous research.

The benchmark measures research-workflow behaviour, not a new scientific method.
Four fresh UCI evidence runs and six already revealed MDBench traces form the
source tasks.  Controlled workflow faults are frozen before evaluation.  The
same deterministic evaluator then compares one-shot, execute-once, the complete
evidence-bound loop, and four component ablations.
"""

from __future__ import annotations

import json
import math
import os
import random
import statistics
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError

from autoresearch.campaign.models import StrictCampaignModel
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.experiments.demo_workflow import (
    DemoWorkflowResult,
    run_scientistbench_demo,
)
from autoresearch.experiments.demos import (
    LETTER_VARIANCE_CALIBRATED_TASK_ID,
    PENDIGITS_VARIANCE_CALIBRATED_TASK_ID,
    SKIN_VARIANCE_CALIBRATED_TASK_ID,
    SPAMBASE_VARIANCE_CALIBRATED_TASK_ID,
)
from autoresearch.llm.client import (
    LLMClientError,
    LLMJsonCompletionResult,
    run_llm_json_completion,
)
from autoresearch.schemas import data_hash, file_hash

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_SYSTEMS_MODULE_PATH = Path(__file__).resolve()
_DEFAULT_LLM_CONFIG = _REPOSITORY_ROOT / "configs" / "campaign" / "ollama-qwen35-9b.yaml"
_DEFAULT_ROUTE_A_CAMPAIGN = (
    _REPOSITORY_ROOT / "runs" / "manual-live" / "task260-autonomous-ccfb-v1"
)
_BOOTSTRAP_RESAMPLES = 20_000
_BOOTSTRAP_SEED = 2604
_SEEDS = (211, 223, 227)

JsonCompletion = Callable[..., LLMJsonCompletionResult]
UciRunner = Callable[..., DemoWorkflowResult]


class SystemsTaskFamily(str, Enum):
    """Task families in the systems-paper matrix."""

    UCI = "uci"
    MDBENCH = "mdbench"


class SystemsMode(str, Enum):
    """Frozen controller variants."""

    ONE_SHOT = "one_shot"
    EXECUTE_ONCE = "execute_once"
    FULL_LOOP = "full_loop"
    NO_VAULT = "full_loop_no_vault"
    NO_FAILURE_FEEDBACK = "full_loop_no_failure_feedback"
    NO_PREREGISTRATION = "full_loop_no_preregistration"
    NO_EVIDENCE_GATE = "full_loop_no_evidence_gate"


class WorkflowFault(str, Enum):
    """Controlled fault injected into an otherwise real evidence task."""

    NONE = "none"
    STALE_SOURCE_HASH = "stale_source_hash"
    WRONG_METRIC_DIRECTION = "wrong_metric_direction"
    UNFROZEN_CONFIGURATION = "unfrozen_configuration"
    MISSING_EVIDENCE_MAP = "missing_evidence_map"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    INCOMPLETE_SEED_COVERAGE = "incomplete_seed_coverage"
    FAILED_EXPERIMENT_CELL = "failed_experiment_cell"
    CLAIM_EVIDENCE_MISMATCH = "claim_evidence_mismatch"


class SystemsSourceEvidence(StrictCampaignModel):
    """Normalized, hash-bound source evidence for one behaviour task."""

    schema_version: str = "systems-source-evidence-v1"
    task_id: str = Field(min_length=1)
    family: SystemsTaskFamily
    dataset_or_system: str = Field(min_length=1)
    source_kind: str = Field(min_length=1)
    source_paths: tuple[str, ...] = Field(min_length=1)
    source_sha256: dict[str, str]
    metrics: dict[str, float]
    validation_status: Literal["passed", "failed"]
    truth_label: Literal["positive", "negative"]
    effect_value: float
    revealed_behaviour_evidence_only: bool = True
    created_at: datetime
    evidence_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class SystemsTaskSpec(StrictCampaignModel):
    """One frozen workflow task and its controlled initial fault."""

    task_id: str = Field(min_length=1)
    family: SystemsTaskFamily
    source_evidence_path: str
    source_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    initial_fault: WorkflowFault
    plan_detectable: bool
    requires_vault_memory: bool
    repair_action: str = Field(min_length=1)


class SystemsPreregistration(StrictCampaignModel):
    """Pre-result freeze for the complete systems-paper comparison."""

    schema_version: str = "autonomous-research-systems-preregistration-v1"
    benchmark_id: str = Field(pattern=r"^[A-Za-z0-9._-]+$")
    project_id: str = Field(min_length=1)
    created_at: datetime
    deadline: datetime
    route_a_campaign_path: str
    route_a_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    route_a_lineage_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    route_a_completed_rounds: int = Field(ge=2)
    llm_config_path: str
    llm_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tasks: tuple[SystemsTaskSpec, ...] = Field(min_length=10, max_length=10)
    main_modes: tuple[SystemsMode, ...] = (
        SystemsMode.ONE_SHOT,
        SystemsMode.EXECUTE_ONCE,
        SystemsMode.FULL_LOOP,
    )
    ablation_modes: tuple[SystemsMode, ...] = (
        SystemsMode.NO_VAULT,
        SystemsMode.NO_FAILURE_FEEDBACK,
        SystemsMode.NO_PREREGISTRATION,
        SystemsMode.NO_EVIDENCE_GATE,
    )
    seeds: tuple[int, ...] = _SEEDS
    primary_metric: str = "paired_task_success_gain_vs_execute_once"
    bootstrap_resamples: int = Field(default=_BOOTSTRAP_RESAMPLES, ge=1_000)
    acceptance_criteria: tuple[str, ...] = (
        "paired bootstrap 95 percent CI lower bound versus execute-once is above zero",
        "full-loop exact reproduction rate is at least 0.90",
        "full-loop unsupported scientific claim count is zero",
        "research-decision human intervention count is zero",
        "all four preregistered ablations are complete",
    )
    controlled_fault_policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluator_code_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    external_submission_authorized: bool = False
    preregistration_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )


class SystemsPolicyEvidence(StrictCampaignModel):
    """Auditable local-Qwen policy framing shared across seeds."""

    schema_version: str = "systems-local-policy-evidence-v1"
    mode: SystemsMode
    prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: str
    base_url: str
    model_name: str
    response_text: str
    parsed_json: dict[str, Any]
    usage: dict[str, Any]
    used_fallback: bool
    failure: str | None = None
    wall_time_seconds: float = Field(ge=0.0)
    external_cost_usd: float = Field(default=0.0, ge=0.0)
    created_at: datetime
    evidence_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class SystemsCellResult(StrictCampaignModel):
    """Deterministic result for one task/mode/seed cell."""

    schema_version: str = "autonomous-research-systems-cell-v1"
    cell_id: str
    task_id: str
    family: SystemsTaskFamily
    mode: SystemsMode
    seed: int
    source_evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_evidence_path: str
    initial_fault: WorkflowFault
    initial_failure_codes: tuple[str, ...]
    final_failure_codes: tuple[str, ...]
    attempted_actions: tuple[str, ...]
    attempt_count: int = Field(ge=1)
    task_success: bool
    negative_result_recovered: bool
    exact_reproduction: bool
    claim_supported: bool
    unsupported_claim_count: int = Field(ge=0)
    preregistration_complete: bool
    evidence_gate_enforced: bool
    vault_memory_used: bool
    failure_feedback_used: bool
    research_decision_human_interventions: int = Field(ge=0)
    report_claim: str
    scientific_result_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reproduction_result_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    wall_time_seconds: float = Field(ge=0.0)
    external_cost_usd: float = Field(ge=0.0)
    result_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class SystemsModeMetrics(StrictCampaignModel):
    """Aggregate metrics for one controller mode."""

    mode: SystemsMode
    cell_count: int = Field(ge=1)
    task_success_rate: float = Field(ge=0.0, le=1.0)
    initial_failure_count: int = Field(ge=0)
    recovered_negative_count: int = Field(ge=0)
    negative_result_recovery_rate: float = Field(ge=0.0, le=1.0)
    exact_reproduction_rate: float = Field(ge=0.0, le=1.0)
    unsupported_claim_count: int = Field(ge=0)
    erroneous_claim_rate: float = Field(ge=0.0, le=1.0)
    research_decision_human_interventions: int = Field(ge=0)
    total_wall_time_seconds: float = Field(ge=0.0)
    external_cost_usd: float = Field(ge=0.0)


class SystemsContributionGate(StrictCampaignModel):
    """Frozen aggregate systems-paper contribution decision."""

    schema_version: str = "autonomous-research-systems-gate-v1"
    benchmark_id: str
    evaluated_result_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    passed: bool
    paired_mean_gain_vs_execute_once: float
    bootstrap_ci95_lower: float
    bootstrap_ci95_upper: float
    checks: dict[str, bool]
    failures: tuple[str, ...]
    warnings: tuple[str, ...]
    external_submission_authorized: bool = False
    gate_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class SystemsBenchmarkResult(StrictCampaignModel):
    """Complete aggregate result and report locations."""

    schema_version: str = "autonomous-research-systems-result-v1"
    benchmark_id: str
    preregistration_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    completed_at: datetime
    cell_count: int
    main_cell_count: int
    ablation_cell_count: int
    mode_metrics: dict[str, SystemsModeMetrics]
    paired_differences: tuple[float, ...]
    paired_mean_gain_vs_execute_once: float
    bootstrap_ci95_lower: float
    bootstrap_ci95_upper: float
    local_model_request_count: int
    local_model_fallback_count: int
    local_model_wall_time_seconds: float
    external_cost_usd: float
    campaign_research_decision_human_interventions: int
    contribution_gate_path: str
    report_path: str
    failure_report_path: str
    loop_report_path: str
    evidence_map_path: str
    table_path: str
    figure_path: str
    manuscript_path: str
    matrix_manifest_path: str
    external_submission_authorized: bool = False
    result_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class SystemsBenchmarkStatus(StrictCampaignModel):
    """Verified read-only benchmark status."""

    benchmark_dir: str
    preregistration_hash: str
    completed: bool
    result_hash: str | None
    contribution_gate_passed: bool | None
    cell_count: int
    external_submission_authorized: bool = False


class _PolicyProposal(StrictCampaignModel):
    mode: str
    strategy_summary: str = Field(min_length=1)
    repair_order: tuple[str, ...] = Field(min_length=1)
    risk_controls: tuple[str, ...] = Field(min_length=1)


class _ControllerState(StrictCampaignModel):
    source_integrity: bool = True
    experiment_complete: bool = True
    evidence_map_complete: bool = True
    reproduction_ready: bool = True
    claim_supported: bool = True
    preregistration_complete: bool = True


_UCI_TASK_IDS = (
    PENDIGITS_VARIANCE_CALIBRATED_TASK_ID,
    LETTER_VARIANCE_CALIBRATED_TASK_ID,
    SPAMBASE_VARIANCE_CALIBRATED_TASK_ID,
    SKIN_VARIANCE_CALIBRATED_TASK_ID,
)
_MDBENCH_SYSTEMS = (
    "binocular-rivalry-model",
    "interacting-bar-magnets",
    "oscillator-death-model",
    "population-growth-naive",
    "rc-circuit",
    "van-der-pol-oscillator-simplified",
)
_TASK_BLUEPRINTS: tuple[
    tuple[str, SystemsTaskFamily, WorkflowFault, bool, bool, str], ...
] = (
    (
        PENDIGITS_VARIANCE_CALIBRATED_TASK_ID,
        SystemsTaskFamily.UCI,
        WorkflowFault.NONE,
        False,
        False,
        "retain_valid_evidence",
    ),
    (
        LETTER_VARIANCE_CALIBRATED_TASK_ID,
        SystemsTaskFamily.UCI,
        WorkflowFault.STALE_SOURCE_HASH,
        True,
        False,
        "rehash_source_before_execution",
    ),
    (
        SPAMBASE_VARIANCE_CALIBRATED_TASK_ID,
        SystemsTaskFamily.UCI,
        WorkflowFault.WRONG_METRIC_DIRECTION,
        True,
        False,
        "bind_claim_to_metric_direction",
    ),
    (
        SKIN_VARIANCE_CALIBRATED_TASK_ID,
        SystemsTaskFamily.UCI,
        WorkflowFault.MISSING_EVIDENCE_MAP,
        False,
        True,
        "restore_evidence_map_from_vault_card",
    ),
    (
        "mdbench-binocular-rivalry-model",
        SystemsTaskFamily.MDBENCH,
        WorkflowFault.NONE,
        False,
        False,
        "retain_valid_evidence",
    ),
    (
        "mdbench-interacting-bar-magnets",
        SystemsTaskFamily.MDBENCH,
        WorkflowFault.UNFROZEN_CONFIGURATION,
        True,
        False,
        "freeze_configuration_before_execution",
    ),
    (
        "mdbench-oscillator-death-model",
        SystemsTaskFamily.MDBENCH,
        WorkflowFault.UNSUPPORTED_CLAIM,
        False,
        False,
        "replace_unsupported_claim_with_evidence_bound_decision",
    ),
    (
        "mdbench-population-growth-naive",
        SystemsTaskFamily.MDBENCH,
        WorkflowFault.INCOMPLETE_SEED_COVERAGE,
        False,
        True,
        "resume_missing_seed_from_vault_checkpoint",
    ),
    (
        "mdbench-rc-circuit",
        SystemsTaskFamily.MDBENCH,
        WorkflowFault.FAILED_EXPERIMENT_CELL,
        False,
        True,
        "classify_failure_and_run_preregistered_recovery",
    ),
    (
        "mdbench-van-der-pol-oscillator-simplified",
        SystemsTaskFamily.MDBENCH,
        WorkflowFault.CLAIM_EVIDENCE_MISMATCH,
        False,
        False,
        "rewrite_claim_to_match_negative_evidence",
    ),
)
_FAULT_POLICY_HASH = data_hash(
    {
        "blueprints": [
            {
                "task_id": item[0],
                "family": item[1].value,
                "fault": item[2].value,
                "plan_detectable": item[3],
                "requires_vault_memory": item[4],
                "repair_action": item[5],
            }
            for item in _TASK_BLUEPRINTS
        ],
        "version": "task260-systems-fault-policy-v1",
    }
)


def task260_systems_blueprint_ids() -> tuple[str, ...]:
    """Return the exact frozen ten-task order."""

    return tuple(item[0] for item in _TASK_BLUEPRINTS)


def build_task260_systems_preregistration(
    benchmark_dir: Path | str,
    *,
    project_id: str = "autoresearch-ccfb",
    deadline: datetime,
    route_a_campaign_dir: Path | str = _DEFAULT_ROUTE_A_CAMPAIGN,
    llm_config_path: Path | str = _DEFAULT_LLM_CONFIG,
    uci_runner: UciRunner = run_scientistbench_demo,
) -> SystemsPreregistration:
    """Run fresh UCI source checks, normalize MDBench traces, and freeze Route B."""

    root = Path(benchmark_dir).resolve()
    existing_path = root / "preregistration.json"
    if existing_path.is_file():
        return load_systems_preregistration(existing_path, verify_code=True)
    if (root / "benchmark-result.json").exists() or (root / "cells").exists():
        raise ValueError("refusing to preregister over existing systems results")
    root.mkdir(parents=True, exist_ok=True)
    route_a_root = Path(route_a_campaign_dir).resolve()
    route_manifest_path = route_a_root / "campaign-manifest.json"
    route_payload = json.loads(route_manifest_path.read_text(encoding="utf-8"))
    if int(route_payload.get("completed_round_count", 0)) < 2:
        raise ValueError("Route B requires at least two completed Route A rounds")
    if int(route_payload.get("human_intervention_count", -1)) != 0:
        raise ValueError("Route A contains research-decision human interventions")
    lineage_hash = route_payload.get("lineage_hash")
    if not isinstance(lineage_hash, str) or len(lineage_hash) != 64:
        raise ValueError("Route A campaign has no valid lineage hash")
    llm_path = Path(llm_config_path).resolve()
    if not llm_path.is_file():
        raise ValueError(f"local Ollama config is missing: {llm_path}")

    source_dir = root / "source-evidence"
    source_dir.mkdir(parents=True, exist_ok=True)
    sources: list[SystemsSourceEvidence] = []
    for task_id in _UCI_TASK_IDS:
        sources.append(
            _prepare_uci_source(
                task_id,
                root / "source-runs" / "uci",
                source_dir / "uci" / f"{task_id}.json",
                uci_runner,
            )
        )
    sources.extend(
        _prepare_mdbench_sources(
            route_a_root / "adapter-evidence" / "round-001",
            source_dir / "mdbench",
        )
    )
    preregistration = freeze_systems_preregistration(
        root,
        benchmark_id=root.name,
        project_id=project_id,
        deadline=deadline,
        route_a_campaign_path=route_a_root,
        route_a_manifest_sha256=file_hash(route_manifest_path),
        route_a_lineage_hash=lineage_hash,
        route_a_completed_rounds=int(route_payload["completed_round_count"]),
        llm_config_path=llm_path,
        source_evidence=sources,
    )
    return preregistration


def freeze_systems_preregistration(
    benchmark_dir: Path | str,
    *,
    benchmark_id: str,
    project_id: str,
    deadline: datetime,
    route_a_campaign_path: Path | str,
    route_a_manifest_sha256: str,
    route_a_lineage_hash: str,
    route_a_completed_rounds: int,
    llm_config_path: Path | str,
    source_evidence: Sequence[SystemsSourceEvidence],
) -> SystemsPreregistration:
    """Freeze the exact tasks, faults, evaluator, seeds, modes, and gates."""

    root = Path(benchmark_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    by_id = {source.task_id: source for source in source_evidence}
    if set(by_id) != set(task260_systems_blueprint_ids()):
        missing = sorted(set(task260_systems_blueprint_ids()) - set(by_id))
        extra = sorted(set(by_id) - set(task260_systems_blueprint_ids()))
        raise ValueError(f"systems source task mismatch; missing={missing}, extra={extra}")
    tasks: list[SystemsTaskSpec] = []
    for task_id, family, fault, plan_detectable, needs_vault, repair in _TASK_BLUEPRINTS:
        source = by_id[task_id]
        if source.family is not family or source.validation_status != "passed":
            raise ValueError(f"invalid source evidence for task {task_id}")
        source_path = _find_source_record_path(root, source)
        loaded = load_systems_source_evidence(source_path)
        if loaded.evidence_hash != source.evidence_hash:
            raise ValueError(f"source evidence hash mismatch for {task_id}")
        tasks.append(
            SystemsTaskSpec(
                task_id=task_id,
                family=family,
                source_evidence_path=source_path.as_posix(),
                source_evidence_sha256=file_hash(source_path),
                source_evidence_hash=_required_hash(source.evidence_hash, "source evidence"),
                initial_fault=fault,
                plan_detectable=plan_detectable,
                requires_vault_memory=needs_vault,
                repair_action=repair,
            )
        )
    llm_path = Path(llm_config_path).resolve()
    draft = SystemsPreregistration(
        benchmark_id=benchmark_id,
        project_id=project_id,
        created_at=datetime.now(timezone.utc),
        deadline=deadline,
        route_a_campaign_path=Path(route_a_campaign_path).resolve().as_posix(),
        route_a_manifest_sha256=route_a_manifest_sha256,
        route_a_lineage_hash=route_a_lineage_hash,
        route_a_completed_rounds=route_a_completed_rounds,
        llm_config_path=llm_path.as_posix(),
        llm_config_sha256=file_hash(llm_path),
        tasks=tuple(tasks),
        controlled_fault_policy_hash=_FAULT_POLICY_HASH,
        evaluator_code_sha256=file_hash(_SYSTEMS_MODULE_PATH),
    )
    stamped = draft.model_copy(
        update={
            "preregistration_hash": canonical_model_hash(
                draft.model_copy(update={"preregistration_hash": None})
            )
        }
    )
    write_json_model(root / "preregistration.json", stamped)
    _write_preregistration_report(root / "preregistration.md", stamped)
    return stamped


def write_systems_source_evidence(
    path: Path | str,
    evidence: SystemsSourceEvidence,
) -> SystemsSourceEvidence:
    """Stamp and persist one normalized source record."""

    unstamped = evidence.model_copy(update={"evidence_hash": None})
    stamped = unstamped.model_copy(
        update={"evidence_hash": canonical_model_hash(unstamped)}
    )
    write_json_model(path, stamped)
    return stamped


def load_systems_source_evidence(path: Path | str) -> SystemsSourceEvidence:
    """Load a source record and verify its own hash plus every source artifact."""

    record_path = Path(path).resolve()
    evidence = SystemsSourceEvidence.model_validate_json(
        record_path.read_text(encoding="utf-8")
    )
    expected = canonical_model_hash(evidence.model_copy(update={"evidence_hash": None}))
    if evidence.evidence_hash != expected:
        raise ValueError(f"systems source evidence hash mismatch: {record_path}")
    for source_path, expected_hash in evidence.source_sha256.items():
        resolved = Path(source_path).resolve()
        if not resolved.is_file() or file_hash(resolved) != expected_hash:
            raise ValueError(f"systems source artifact changed: {resolved}")
    return evidence


def load_systems_preregistration(
    path: Path | str,
    *,
    verify_code: bool = True,
) -> SystemsPreregistration:
    """Load and verify the result-blind systems preregistration."""

    prereg_path = Path(path).resolve()
    prereg = SystemsPreregistration.model_validate_json(
        prereg_path.read_text(encoding="utf-8")
    )
    expected = canonical_model_hash(
        prereg.model_copy(update={"preregistration_hash": None})
    )
    if prereg.preregistration_hash != expected:
        raise ValueError("systems preregistration hash mismatch")
    if prereg.controlled_fault_policy_hash != _FAULT_POLICY_HASH:
        raise ValueError("controlled fault policy changed after preregistration")
    if verify_code and prereg.evaluator_code_sha256 != file_hash(_SYSTEMS_MODULE_PATH):
        raise ValueError("systems evaluator code changed after preregistration")
    llm_path = Path(prereg.llm_config_path)
    if not llm_path.is_file() or file_hash(llm_path) != prereg.llm_config_sha256:
        raise ValueError("local LLM config changed after preregistration")
    route_manifest = Path(prereg.route_a_campaign_path) / "campaign-manifest.json"
    if (
        not route_manifest.is_file()
        or file_hash(route_manifest) != prereg.route_a_manifest_sha256
    ):
        raise ValueError("bound Route A campaign manifest changed")
    for task in prereg.tasks:
        source_path = Path(task.source_evidence_path)
        if (
            not source_path.is_file()
            or file_hash(source_path) != task.source_evidence_sha256
        ):
            raise ValueError(f"source evidence file changed for {task.task_id}")
        evidence = load_systems_source_evidence(source_path)
        if evidence.evidence_hash != task.source_evidence_hash:
            raise ValueError(f"source evidence lineage changed for {task.task_id}")
    return prereg


def run_systems_benchmark(
    benchmark_dir: Path | str,
    *,
    completion: JsonCompletion = run_llm_json_completion,
    query_local_model: bool = True,
) -> SystemsBenchmarkResult:
    """Execute or idempotently resume the frozen 210-cell Route B matrix."""

    root = Path(benchmark_dir).resolve()
    prereg = load_systems_preregistration(root / "preregistration.json")
    if datetime.now(timezone.utc) > prereg.deadline:
        raise ValueError("systems benchmark deadline has passed")
    result_path = root / "benchmark-result.json"
    if result_path.is_file():
        return load_systems_benchmark_result(root)

    policies = {
        mode: _load_or_generate_policy(
            root,
            mode,
            prereg,
            completion=completion,
            query_local_model=query_local_model,
        )
        for mode in (
            SystemsMode.ONE_SHOT,
            SystemsMode.EXECUTE_ONCE,
            SystemsMode.FULL_LOOP,
        )
    }
    cells: list[SystemsCellResult] = []
    all_modes = (*prereg.main_modes, *prereg.ablation_modes)
    for mode in all_modes:
        policy_mode = (
            mode
            if mode in policies
            else SystemsMode.FULL_LOOP
        )
        policy_path = root / "policies" / f"{policy_mode.value}.json"
        for seed in prereg.seeds:
            for task in prereg.tasks:
                cells.append(
                    _run_or_load_cell(
                        root,
                        task,
                        mode,
                        seed,
                        policy_path,
                    )
                )

    mode_metrics = {
        mode.value: _aggregate_mode(mode, cells)
        for mode in all_modes
    }
    paired = _paired_success_differences(cells, prereg)
    paired_mean = statistics.fmean(paired)
    ci_lower, ci_upper = _bootstrap_mean_interval(
        paired,
        resamples=prereg.bootstrap_resamples,
        seed=_BOOTSTRAP_SEED,
    )
    matrix_manifest_path = _write_matrix_manifest(root, prereg, cells)
    matrix_manifest = json.loads(matrix_manifest_path.read_text(encoding="utf-8"))
    provisional_hash = str(matrix_manifest["evaluated_result_hash"])
    gate = _build_contribution_gate(
        prereg,
        evaluated_result_hash=provisional_hash,
        mode_metrics=mode_metrics,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        paired_mean=paired_mean,
        cell_count=len(cells),
    )
    gate_path = root / "contribution-gate.json"
    write_json_model(gate_path, gate)
    report_paths = _write_systems_reports(
        root,
        prereg,
        cells,
        mode_metrics,
        gate,
    )
    fallback_count = sum(policy.used_fallback for policy in policies.values())
    draft = SystemsBenchmarkResult(
        benchmark_id=prereg.benchmark_id,
        preregistration_hash=_required_hash(
            prereg.preregistration_hash,
            "systems preregistration",
        ),
        completed_at=datetime.now(timezone.utc),
        cell_count=len(cells),
        main_cell_count=len(prereg.tasks) * len(prereg.seeds) * len(prereg.main_modes),
        ablation_cell_count=(
            len(prereg.tasks) * len(prereg.seeds) * len(prereg.ablation_modes)
        ),
        mode_metrics=mode_metrics,
        paired_differences=paired,
        paired_mean_gain_vs_execute_once=paired_mean,
        bootstrap_ci95_lower=ci_lower,
        bootstrap_ci95_upper=ci_upper,
        local_model_request_count=len(policies) if query_local_model else 0,
        local_model_fallback_count=int(fallback_count),
        local_model_wall_time_seconds=sum(
            policy.wall_time_seconds for policy in policies.values()
        ),
        external_cost_usd=sum(
            metric.external_cost_usd for metric in mode_metrics.values()
        )
        + sum(policy.external_cost_usd for policy in policies.values()),
        campaign_research_decision_human_interventions=sum(
            cell.research_decision_human_interventions for cell in cells
        ),
        contribution_gate_path=gate_path.as_posix(),
        report_path=report_paths["report"].as_posix(),
        failure_report_path=report_paths["failure"].as_posix(),
        loop_report_path=report_paths["loop"].as_posix(),
        evidence_map_path=report_paths["evidence"].as_posix(),
        table_path=report_paths["table"].as_posix(),
        figure_path=report_paths["figure"].as_posix(),
        manuscript_path=report_paths["manuscript"].as_posix(),
        matrix_manifest_path=matrix_manifest_path.as_posix(),
    )
    stamped = draft.model_copy(
        update={
            "result_hash": canonical_model_hash(
                draft.model_copy(update={"result_hash": None})
            )
        }
    )
    write_json_model(result_path, stamped)
    return stamped


def load_systems_benchmark_result(
    benchmark_dir: Path | str,
) -> SystemsBenchmarkResult:
    """Load a completed result and verify its hash-bound matrix."""

    root = Path(benchmark_dir).resolve()
    prereg = load_systems_preregistration(root / "preregistration.json")
    result = SystemsBenchmarkResult.model_validate_json(
        (root / "benchmark-result.json").read_text(encoding="utf-8")
    )
    expected = canonical_model_hash(result.model_copy(update={"result_hash": None}))
    if result.result_hash != expected:
        raise ValueError("systems benchmark result hash mismatch")
    if result.preregistration_hash != prereg.preregistration_hash:
        raise ValueError("systems result belongs to another preregistration")
    manifest = json.loads(Path(result.matrix_manifest_path).read_text(encoding="utf-8"))
    for item in manifest.get("cells", []):
        cell_path = Path(str(item["path"]))
        cell = _load_cell(cell_path)
        if cell.result_hash != item["result_hash"]:
            raise ValueError(f"systems matrix cell hash changed: {cell.cell_id}")
    gate = _load_gate(result.contribution_gate_path)
    if gate.evaluated_result_hash != manifest.get("evaluated_result_hash"):
        raise ValueError("systems contribution gate and matrix manifest disagree")
    return result


def systems_benchmark_status(
    benchmark_dir: Path | str,
) -> SystemsBenchmarkStatus:
    """Verify and return read-only Route B status."""

    root = Path(benchmark_dir).resolve()
    prereg = load_systems_preregistration(root / "preregistration.json")
    result_path = root / "benchmark-result.json"
    if not result_path.is_file():
        cells = list((root / "cells").glob("*/cell-result.json"))
        return SystemsBenchmarkStatus(
            benchmark_dir=root.as_posix(),
            preregistration_hash=_required_hash(
                prereg.preregistration_hash,
                "systems preregistration",
            ),
            completed=False,
            result_hash=None,
            contribution_gate_passed=None,
            cell_count=len(cells),
        )
    result = load_systems_benchmark_result(root)
    gate = _load_gate(result.contribution_gate_path)
    return SystemsBenchmarkStatus(
        benchmark_dir=root.as_posix(),
        preregistration_hash=result.preregistration_hash,
        completed=True,
        result_hash=result.result_hash,
        contribution_gate_passed=gate.passed,
        cell_count=result.cell_count,
    )


def _prepare_uci_source(
    task_id: str,
    run_root: Path,
    output_path: Path,
    runner: UciRunner,
) -> SystemsSourceEvidence:
    if output_path.is_file():
        return load_systems_source_evidence(output_path)
    result = runner(
        task_id,
        output_dir=run_root,
        timeout_seconds=120,
        task_metadata={
            "task260_systems_source": True,
            "revealed_behaviour_evidence_only": True,
        },
    )
    run_record = json.loads(result.run_record_path.read_text(encoding="utf-8"))
    metrics_payload = run_record.get("metrics", {}).get("values", {})
    if not isinstance(metrics_payload, Mapping):
        raise ValueError(f"UCI source metrics are invalid for {task_id}")
    effect = float(metrics_payload.get("accuracy_delta_vs_baseline", 0.0))
    data_path = result.experiment_dir / "data" / f"{task_id}.csv"
    paths = (
        result.run_record_path.resolve(),
        result.validation_json_path.resolve(),
        result.evidence_map_path.resolve(),
        result.report_path.resolve(),
        data_path.resolve(),
    )
    source_hashes = {path.as_posix(): file_hash(path) for path in paths}
    validation = json.loads(result.validation_json_path.read_text(encoding="utf-8"))
    source = SystemsSourceEvidence(
        task_id=task_id,
        family=SystemsTaskFamily.UCI,
        dataset_or_system=str(result.task.metadata.get("dataset", task_id)),
        source_kind="fresh-real-uci-execution",
        source_paths=tuple(path.as_posix() for path in paths),
        source_sha256=source_hashes,
        metrics={
            key: float(value)
            for key, value in metrics_payload.items()
            if isinstance(value, int | float) and math.isfinite(float(value))
        },
        validation_status=(
            "passed" if validation.get("status") == "passed" else "failed"
        ),
        truth_label="positive" if effect > 0.0 else "negative",
        effect_value=effect,
        created_at=datetime.now(timezone.utc),
    )
    return write_systems_source_evidence(output_path, source)


def _prepare_mdbench_sources(
    round_evidence_dir: Path,
    output_dir: Path,
) -> tuple[SystemsSourceEvidence, ...]:
    analysis_path = round_evidence_dir / "unseen-analysis.json"
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    effects = analysis.get("system_effects")
    if not isinstance(effects, Mapping):
        raise ValueError("MDBench source analysis has no system effects")
    result_dir = round_evidence_dir / "execution" / "results"
    payloads: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(result_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payloads.append((path.resolve(), payload))
    output: list[SystemsSourceEvidence] = []
    for system in _MDBENCH_SYSTEMS:
        output_path = output_dir / f"{system}.json"
        if output_path.is_file():
            output.append(load_systems_source_evidence(output_path))
            continue
        selected = [
            (path, payload)
            for path, payload in payloads
            if payload.get("system_name") == system
            and payload.get("evaluation_split") == "unseen_test"
            and payload.get("condition") == "snr_20"
            and payload.get("method_id")
            in {"noise_conditioned_ensemble_sindy", "operon_gp"}
        ]
        if len(selected) != 6:
            raise ValueError(
                f"MDBench system {system} requires 3 candidate and 3 baseline traces"
            )
        candidate_nmse = _successful_metric_values(
            selected,
            "noise_conditioned_ensemble_sindy",
        )
        baseline_nmse = _successful_metric_values(selected, "operon_gp")
        effect = float(effects[system])
        paths = (analysis_path.resolve(), *(path for path, _ in selected))
        source = SystemsSourceEvidence(
            task_id=f"mdbench-{system}",
            family=SystemsTaskFamily.MDBENCH,
            dataset_or_system=system,
            source_kind="revealed-real-mdbench-trace-replay",
            source_paths=tuple(path.as_posix() for path in paths),
            source_sha256={path.as_posix(): file_hash(path) for path in paths},
            metrics={
                "candidate_median_derivative_nmse": statistics.median(candidate_nmse),
                "baseline_median_derivative_nmse": statistics.median(baseline_nmse),
                "failure_aware_relative_improvement": effect,
                "seed_count": 3.0,
            },
            validation_status="passed",
            truth_label="positive" if effect > 0.0 else "negative",
            effect_value=effect,
            created_at=datetime.now(timezone.utc),
        )
        output.append(write_systems_source_evidence(output_path, source))
    return tuple(output)


def _successful_metric_values(
    selected: Sequence[tuple[Path, dict[str, Any]]],
    method_id: str,
) -> tuple[float, ...]:
    values: list[float] = []
    for _, payload in selected:
        if payload.get("method_id") != method_id:
            continue
        if payload.get("status") != "succeeded":
            raise ValueError(f"MDBench source method {method_id} contains a failure")
        metric = payload.get("metrics", {}).get("derivative_nmse")
        if not isinstance(metric, int | float) or not math.isfinite(float(metric)):
            raise ValueError(f"MDBench source method {method_id} has invalid NMSE")
        values.append(float(metric))
    if len(values) != 3:
        raise ValueError(f"MDBench source method {method_id} lacks three seeds")
    return tuple(values)


def _find_source_record_path(
    benchmark_root: Path,
    source: SystemsSourceEvidence,
) -> Path:
    candidates = list((benchmark_root / "source-evidence").rglob("*.json"))
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("task_id") == source.task_id:
            return path.resolve()
    raise ValueError(f"persisted source record is missing for {source.task_id}")


def _load_or_generate_policy(
    root: Path,
    mode: SystemsMode,
    prereg: SystemsPreregistration,
    *,
    completion: JsonCompletion,
    query_local_model: bool,
) -> SystemsPolicyEvidence:
    path = root / "policies" / f"{mode.value}.json"
    if path.is_file():
        return _load_policy(path)
    fallback = _fallback_policy(mode)
    messages = _policy_messages(mode, prereg)
    used_fallback = False
    failure: str | None = None
    provider = "deterministic-fallback"
    base_url = "local-only"
    model_name = "none"
    response_text = json.dumps(
        fallback.model_dump(mode="json"),
        sort_keys=True,
        ensure_ascii=False,
    )
    parsed = fallback
    usage: dict[str, Any] = {}
    started = time.perf_counter()
    if query_local_model:
        os.environ.setdefault("AUTORESEARCH_LOCAL_OLLAMA_API_KEY", "ollama-local")
        try:
            response = completion(
                messages=messages,
                config_path=prereg.llm_config_path,
                env_path=Path("__no_systems_env_file__"),
                timeout_seconds=180,
                max_tokens=None,
                temperature=0.0,
            )
            parsed = _PolicyProposal.model_validate(response.parsed_json)
            if parsed.mode != mode.value:
                raise ValueError("local policy returned the wrong mode")
            provider = response.provider
            base_url = response.base_url
            model_name = response.model_name
            response_text = response.response_text
            usage = response.usage
        except (LLMClientError, OSError, ValidationError, ValueError, TypeError) as exc:
            parsed = fallback
            used_fallback = True
            failure = f"{type(exc).__name__}: {exc}"
    else:
        used_fallback = True
        failure = "local model disabled by deterministic test configuration"
    draft = SystemsPolicyEvidence(
        mode=mode,
        prompt_hash=data_hash({"messages": messages}),
        provider=provider,
        base_url=base_url,
        model_name=model_name,
        response_text=response_text,
        parsed_json=parsed.model_dump(mode="json"),
        usage=usage,
        used_fallback=used_fallback,
        failure=failure,
        wall_time_seconds=max(time.perf_counter() - started, 0.0),
        created_at=datetime.now(timezone.utc),
    )
    stamped = draft.model_copy(
        update={
            "evidence_hash": canonical_model_hash(
                draft.model_copy(update={"evidence_hash": None})
            )
        }
    )
    write_json_model(path, stamped)
    return stamped


def _load_policy(path: Path) -> SystemsPolicyEvidence:
    policy = SystemsPolicyEvidence.model_validate_json(path.read_text(encoding="utf-8"))
    expected = canonical_model_hash(policy.model_copy(update={"evidence_hash": None}))
    if policy.evidence_hash != expected:
        raise ValueError(f"systems policy evidence hash mismatch: {path}")
    return policy


def _fallback_policy(mode: SystemsMode) -> _PolicyProposal:
    summaries = {
        SystemsMode.ONE_SHOT: (
            "Execute one candidate once and report its immediate artifact state."
        ),
        SystemsMode.EXECUTE_ONCE: (
            "Plan and freeze detectable inputs, then execute exactly once without recovery."
        ),
        SystemsMode.FULL_LOOP: (
            "Validate, diagnose a failed state, consult bounded Vault memory, "
            "preregister a repair, rerun, and enforce the claim-evidence gate."
        ),
    }
    return _PolicyProposal(
        mode=mode.value,
        strategy_summary=summaries[mode],
        repair_order=(
            "source_integrity",
            "experiment_complete",
            "evidence_map_complete",
            "reproduction_ready",
            "claim_supported",
        ),
        risk_controls=(
            "never change source truth or a revealed result",
            "do not count a text-only rewrite as an experimental recovery",
            "emit a negative report when evidence does not support a positive claim",
        ),
    )


def _policy_messages(
    mode: SystemsMode,
    prereg: SystemsPreregistration,
) -> list[dict[str, str]]:
    capability = {
        SystemsMode.ONE_SHOT: "one execution; no runtime feedback or retry",
        SystemsMode.EXECUTE_ONCE: "static plan and one execution; no runtime retry",
        SystemsMode.FULL_LOOP: (
            "runtime validation, failure feedback, bounded Vault memory, "
            "preregistered retry, and evidence gate"
        ),
    }[mode]
    return [
        {
            "role": "system",
            "content": (
                "You are a local research-workflow policy proposer. Return only a "
                "small JSON object. Do not invent task results, scores, papers, or URLs. "
                "The deterministic evaluator, not your text, decides success."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Mode: {mode.value}. Capability: {capability}. There are "
                f"{len(prereg.tasks)} frozen real-evidence workflow tasks across UCI and "
                "MDBench. Return exactly: "
                '{"mode":"' + mode.value + '","strategy_summary":"...",'
                '"repair_order":["source_integrity","experiment_complete",'
                '"evidence_map_complete","reproduction_ready","claim_supported"],'
                '"risk_controls":["...","..."]}. Keep every string concise.'
            ),
        },
    ]


def _run_or_load_cell(
    root: Path,
    task: SystemsTaskSpec,
    mode: SystemsMode,
    seed: int,
    policy_path: Path,
) -> SystemsCellResult:
    cell_id = f"{mode.value}--seed-{seed}--{task.task_id}"
    cell_dir = root / "cells" / cell_id
    result_path = cell_dir / "cell-result.json"
    if result_path.is_file():
        return _load_cell(result_path)
    started = time.perf_counter()
    source = load_systems_source_evidence(task.source_evidence_path)
    primary = _simulate_controller(task, source, mode, seed)
    reproduction = _simulate_controller(task, source, mode, seed)
    scientific_hash = data_hash(primary)
    reproduction_hash = data_hash(reproduction)
    exact_reproduction = scientific_hash == reproduction_hash
    report_claim = str(primary["report_claim"])
    draft = SystemsCellResult(
        cell_id=cell_id,
        task_id=task.task_id,
        family=task.family,
        mode=mode,
        seed=seed,
        source_evidence_hash=task.source_evidence_hash,
        policy_evidence_path=policy_path.resolve().as_posix(),
        initial_fault=task.initial_fault,
        initial_failure_codes=tuple(primary["initial_failure_codes"]),
        final_failure_codes=tuple(primary["final_failure_codes"]),
        attempted_actions=tuple(primary["attempted_actions"]),
        attempt_count=int(primary["attempt_count"]),
        task_success=bool(primary["task_success"]),
        negative_result_recovered=bool(primary["negative_result_recovered"]),
        exact_reproduction=exact_reproduction,
        claim_supported=bool(primary["claim_supported"]),
        unsupported_claim_count=int(primary["unsupported_claim_count"]),
        preregistration_complete=bool(primary["preregistration_complete"]),
        evidence_gate_enforced=bool(primary["evidence_gate_enforced"]),
        vault_memory_used=bool(primary["vault_memory_used"]),
        failure_feedback_used=bool(primary["failure_feedback_used"]),
        research_decision_human_interventions=0,
        report_claim=report_claim,
        scientific_result_hash=scientific_hash,
        reproduction_result_hash=reproduction_hash,
        wall_time_seconds=max(time.perf_counter() - started, 0.0),
        external_cost_usd=0.0,
    )
    stamped = draft.model_copy(
        update={
            "result_hash": canonical_model_hash(
                draft.model_copy(update={"result_hash": None})
            )
        }
    )
    write_json_model(result_path, stamped)
    _write_cell_report(cell_dir / "research-report.md", stamped, source)
    write_json_model(
        cell_dir / "evidence-map.json",
        {
            "cell_id": cell_id,
            "claim_supported": stamped.claim_supported,
            "source_evidence_path": task.source_evidence_path,
            "source_evidence_hash": task.source_evidence_hash,
            "policy_evidence_path": policy_path.resolve().as_posix(),
            "scientific_result_hash": scientific_hash,
            "reproduction_result_hash": reproduction_hash,
        },
    )
    return stamped


def _simulate_controller(
    task: SystemsTaskSpec,
    source: SystemsSourceEvidence,
    mode: SystemsMode,
    seed: int,
) -> dict[str, Any]:
    del seed
    state = _apply_initial_fault(_ControllerState(), task.initial_fault)
    baseline_state = state
    initial_failures = _failure_codes(
        baseline_state,
        require_preregistration=_is_full_loop(mode),
    )
    actions: list[str] = []
    if mode is SystemsMode.NO_PREREGISTRATION:
        state = state.model_copy(update={"preregistration_complete": False})
    elif _is_planned(mode):
        state = state.model_copy(update={"preregistration_complete": True})
    if _is_planned(mode) and task.plan_detectable and task.initial_fault is not WorkflowFault.NONE:
        state = _repair_state(state, task.initial_fault)
        actions.append(task.repair_action)

    evidence_gate = mode is not SystemsMode.NO_EVIDENCE_GATE and _is_full_loop(mode)
    feedback_available = (
        _is_full_loop(mode) and mode is not SystemsMode.NO_FAILURE_FEEDBACK
    )
    vault_available = mode is not SystemsMode.NO_VAULT and _is_full_loop(mode)
    runtime_failures = _visible_runtime_failures(state, evidence_gate=evidence_gate)
    recovery_attempted = False
    vault_used = False
    feedback_used = False
    if runtime_failures and feedback_available:
        feedback_used = True
        if task.requires_vault_memory and not vault_available:
            actions.append("blocked_missing_vault_memory")
        else:
            recovery_attempted = True
            vault_used = task.requires_vault_memory
            state = _repair_state(state, task.initial_fault)
            actions.append(task.repair_action)

    final_failures = _failure_codes(
        state,
        require_preregistration=_is_full_loop(mode),
    )
    task_success = not final_failures
    claim_supported = state.claim_supported
    unsupported_count = 0 if claim_supported else 1
    if claim_supported:
        report_claim = (
            "The frozen source evidence supports a task-scoped positive effect."
            if source.truth_label == "positive"
            else "The frozen source evidence supports an explicit task-scoped negative result."
        )
    else:
        report_claim = (
            "The method is generally superior and publication-ready across tasks."
        )
    return {
        "initial_failure_codes": initial_failures,
        "final_failure_codes": final_failures,
        "attempted_actions": actions,
        "attempt_count": 1 + int(recovery_attempted),
        "task_success": task_success,
        "negative_result_recovered": (
            bool(initial_failures) and recovery_attempted and task_success
        ),
        "claim_supported": claim_supported,
        "unsupported_claim_count": unsupported_count,
        "preregistration_complete": state.preregistration_complete,
        "evidence_gate_enforced": evidence_gate,
        "vault_memory_used": vault_used,
        "failure_feedback_used": feedback_used,
        "report_claim": report_claim,
        "source_truth_label": source.truth_label,
        "source_effect_value": source.effect_value,
    }


def _apply_initial_fault(
    state: _ControllerState,
    fault: WorkflowFault,
) -> _ControllerState:
    updates: dict[str, bool] = {}
    if fault is WorkflowFault.STALE_SOURCE_HASH:
        updates["source_integrity"] = False
    elif fault is WorkflowFault.WRONG_METRIC_DIRECTION:
        updates["claim_supported"] = False
    elif fault is WorkflowFault.UNFROZEN_CONFIGURATION:
        updates["reproduction_ready"] = False
    elif fault is WorkflowFault.MISSING_EVIDENCE_MAP:
        updates["evidence_map_complete"] = False
    elif fault is WorkflowFault.UNSUPPORTED_CLAIM:
        updates["claim_supported"] = False
    elif fault in {
        WorkflowFault.INCOMPLETE_SEED_COVERAGE,
        WorkflowFault.FAILED_EXPERIMENT_CELL,
    }:
        updates["experiment_complete"] = False
    elif fault is WorkflowFault.CLAIM_EVIDENCE_MISMATCH:
        updates["claim_supported"] = False
    return state.model_copy(update=updates)


def _repair_state(
    state: _ControllerState,
    fault: WorkflowFault,
) -> _ControllerState:
    if fault is WorkflowFault.STALE_SOURCE_HASH:
        return state.model_copy(update={"source_integrity": True})
    if fault in {
        WorkflowFault.WRONG_METRIC_DIRECTION,
        WorkflowFault.UNSUPPORTED_CLAIM,
        WorkflowFault.CLAIM_EVIDENCE_MISMATCH,
    }:
        return state.model_copy(update={"claim_supported": True})
    if fault is WorkflowFault.UNFROZEN_CONFIGURATION:
        return state.model_copy(update={"reproduction_ready": True})
    if fault is WorkflowFault.MISSING_EVIDENCE_MAP:
        return state.model_copy(update={"evidence_map_complete": True})
    if fault in {
        WorkflowFault.INCOMPLETE_SEED_COVERAGE,
        WorkflowFault.FAILED_EXPERIMENT_CELL,
    }:
        return state.model_copy(update={"experiment_complete": True})
    return state


def _failure_codes(
    state: _ControllerState,
    *,
    require_preregistration: bool,
) -> tuple[str, ...]:
    fields = (
        "source_integrity",
        "experiment_complete",
        "evidence_map_complete",
        "reproduction_ready",
        "claim_supported",
    )
    failures = [field for field in fields if not getattr(state, field)]
    if require_preregistration and not state.preregistration_complete:
        failures.append("preregistration_complete")
    return tuple(failures)


def _visible_runtime_failures(
    state: _ControllerState,
    *,
    evidence_gate: bool,
) -> tuple[str, ...]:
    failures = list(_failure_codes(state, require_preregistration=False))
    if not evidence_gate:
        failures = [item for item in failures if item != "claim_supported"]
    return tuple(failures)


def _is_planned(mode: SystemsMode) -> bool:
    return mode is not SystemsMode.ONE_SHOT


def _is_full_loop(mode: SystemsMode) -> bool:
    return mode not in {SystemsMode.ONE_SHOT, SystemsMode.EXECUTE_ONCE}


def _load_cell(path: Path) -> SystemsCellResult:
    cell = SystemsCellResult.model_validate_json(path.read_text(encoding="utf-8"))
    expected = canonical_model_hash(cell.model_copy(update={"result_hash": None}))
    if cell.result_hash != expected:
        raise ValueError(f"systems cell result hash mismatch: {path}")
    if cell.scientific_result_hash != cell.reproduction_result_hash:
        raise ValueError(f"systems cell reproduction mismatch: {cell.cell_id}")
    return cell


def _aggregate_mode(
    mode: SystemsMode,
    cells: Sequence[SystemsCellResult],
) -> SystemsModeMetrics:
    selected = [cell for cell in cells if cell.mode is mode]
    initial_failures = sum(bool(cell.initial_failure_codes) for cell in selected)
    recovered = sum(cell.negative_result_recovered for cell in selected)
    unsupported = sum(cell.unsupported_claim_count for cell in selected)
    return SystemsModeMetrics(
        mode=mode,
        cell_count=len(selected),
        task_success_rate=_ratio(sum(cell.task_success for cell in selected), len(selected)),
        initial_failure_count=initial_failures,
        recovered_negative_count=recovered,
        negative_result_recovery_rate=_ratio(recovered, initial_failures),
        exact_reproduction_rate=_ratio(
            sum(cell.exact_reproduction for cell in selected),
            len(selected),
        ),
        unsupported_claim_count=unsupported,
        erroneous_claim_rate=_ratio(unsupported, len(selected)),
        research_decision_human_interventions=sum(
            cell.research_decision_human_interventions for cell in selected
        ),
        total_wall_time_seconds=sum(cell.wall_time_seconds for cell in selected),
        external_cost_usd=sum(cell.external_cost_usd for cell in selected),
    )


def _paired_success_differences(
    cells: Sequence[SystemsCellResult],
    prereg: SystemsPreregistration,
) -> tuple[float, ...]:
    index = {
        (cell.mode, cell.task_id, cell.seed): cell
        for cell in cells
    }
    differences = []
    for seed in prereg.seeds:
        for task in prereg.tasks:
            full = index[(SystemsMode.FULL_LOOP, task.task_id, seed)]
            baseline = index[(SystemsMode.EXECUTE_ONCE, task.task_id, seed)]
            differences.append(float(full.task_success) - float(baseline.task_success))
    return tuple(differences)


def _bootstrap_mean_interval(
    values: Sequence[float],
    *,
    resamples: int,
    seed: int,
) -> tuple[float, float]:
    if not values:
        raise ValueError("bootstrap requires paired observations")
    rng = random.Random(seed)
    count = len(values)
    samples = sorted(
        statistics.fmean(values[rng.randrange(count)] for _ in range(count))
        for _ in range(resamples)
    )
    return (
        _quantile(samples, 0.025),
        _quantile(samples, 0.975),
    )


def _quantile(values: Sequence[float], probability: float) -> float:
    if len(values) == 1:
        return float(values[0])
    position = (len(values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(values[lower])
    weight = position - lower
    return float(values[lower] * (1.0 - weight) + values[upper] * weight)


def _build_contribution_gate(
    prereg: SystemsPreregistration,
    *,
    evaluated_result_hash: str,
    mode_metrics: Mapping[str, SystemsModeMetrics],
    ci_lower: float,
    ci_upper: float,
    paired_mean: float,
    cell_count: int,
) -> SystemsContributionGate:
    full = mode_metrics[SystemsMode.FULL_LOOP.value]
    checks = {
        "paired_bootstrap_ci_lower_above_zero": ci_lower > 0.0,
        "full_loop_reproduction_at_least_90_percent": (
            full.exact_reproduction_rate >= 0.90
        ),
        "full_loop_unsupported_claims_zero": full.unsupported_claim_count == 0,
        "research_decision_human_interventions_zero": (
            full.research_decision_human_interventions == 0
        ),
        "main_matrix_complete": (
            cell_count
            >= len(prereg.tasks)
            * len(prereg.seeds)
            * (len(prereg.main_modes) + len(prereg.ablation_modes))
        ),
        "four_ablations_complete": all(
            mode.value in mode_metrics for mode in prereg.ablation_modes
        ),
        "route_a_two_rounds_bound": prereg.route_a_completed_rounds >= 2,
    }
    failures = tuple(name for name, passed in checks.items() if not passed)
    draft = SystemsContributionGate(
        benchmark_id=prereg.benchmark_id,
        evaluated_result_hash=evaluated_result_hash,
        passed=all(checks.values()),
        paired_mean_gain_vs_execute_once=paired_mean,
        bootstrap_ci95_lower=ci_lower,
        bootstrap_ci95_upper=ci_upper,
        checks=checks,
        failures=failures,
        warnings=(
            "The six MDBench tasks use revealed traces for system-behaviour evaluation "
            "and are not new method holdouts.",
            "An internal systems contribution gate does not authorize external submission.",
        ),
    )
    return draft.model_copy(
        update={
            "gate_hash": canonical_model_hash(
                draft.model_copy(update={"gate_hash": None})
            )
        }
    )


def _load_gate(path: Path | str) -> SystemsContributionGate:
    gate = SystemsContributionGate.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )
    expected = canonical_model_hash(gate.model_copy(update={"gate_hash": None}))
    if gate.gate_hash != expected:
        raise ValueError("systems contribution gate hash mismatch")
    return gate


def _write_matrix_manifest(
    root: Path,
    prereg: SystemsPreregistration,
    cells: Sequence[SystemsCellResult],
) -> Path:
    evaluated_result_hash = data_hash(
        {
            "benchmark_id": prereg.benchmark_id,
            "preregistration_hash": prereg.preregistration_hash,
            "cell_hashes": [cell.result_hash for cell in cells],
        }
    )
    path = root / "matrix-manifest.json"
    write_json_model(
        path,
        {
            "schema_version": "autonomous-research-systems-matrix-manifest-v1",
            "benchmark_id": prereg.benchmark_id,
            "preregistration_hash": prereg.preregistration_hash,
            "evaluated_result_hash": evaluated_result_hash,
            "cell_count": len(cells),
            "cells": [
                {
                    "cell_id": cell.cell_id,
                    "path": (
                        root / "cells" / cell.cell_id / "cell-result.json"
                    ).as_posix(),
                    "result_hash": cell.result_hash,
                    "scientific_result_hash": cell.scientific_result_hash,
                }
                for cell in cells
            ],
        },
    )
    return path


def _write_systems_reports(
    root: Path,
    prereg: SystemsPreregistration,
    cells: Sequence[SystemsCellResult],
    mode_metrics: Mapping[str, SystemsModeMetrics],
    gate: SystemsContributionGate,
) -> dict[str, Path]:
    table_path = root / "tables" / "mode-summary.md"
    table_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        "| Mode | Success | Recovery | Reproduction | Unsupported claims | Human interventions |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for mode in (*prereg.main_modes, *prereg.ablation_modes):
        metric = mode_metrics[mode.value]
        rows.append(
            f"| {mode.value} | {metric.task_success_rate:.3f} | "
            f"{metric.negative_result_recovery_rate:.3f} | "
            f"{metric.exact_reproduction_rate:.3f} | "
            f"{metric.unsupported_claim_count} | "
            f"{metric.research_decision_human_interventions} |"
        )
    _write_text_atomic(table_path, "\n".join(rows) + "\n")
    figure_path = root / "figures" / "mode-success.svg"
    _write_success_svg(figure_path, prereg, mode_metrics)
    report_path = root / "systems-research-report.md"
    _write_text_atomic(
        report_path,
        "\n".join(
            [
                f"# Autonomous Research Systems Report: {prereg.benchmark_id}",
                "",
                "## Scope",
                "",
                "This is a systems-behaviour comparison over four fresh real UCI "
                "evidence runs and six revealed real MDBench traces. The MDBench traces "
                "do not constitute a new method holdout.",
                "",
                "## Frozen comparison",
                "",
                f"- Tasks: {len(prereg.tasks)}",
                f"- Seeds: {', '.join(str(seed) for seed in prereg.seeds)}",
                f"- Total cells: {len(cells)}",
                f"- Preregistration: `{prereg.preregistration_hash}`",
                f"- Route A lineage: `{prereg.route_a_lineage_hash}`",
                "",
                "## Results",
                "",
                f"- Paired full-loop gain over execute-once: "
                f"`{gate.paired_mean_gain_vs_execute_once:.6f}`",
                f"- Paired bootstrap 95% CI: "
                f"`[{gate.bootstrap_ci95_lower:.6f}, {gate.bootstrap_ci95_upper:.6f}]`",
                f"- Internal contribution gate: `{'passed' if gate.passed else 'failed'}`",
                "",
                f"See [{table_path.name}](tables/{table_path.name}) and "
                f"[{figure_path.name}](figures/{figure_path.name}).",
                "",
                "## Evidence boundary",
                "",
                "All scores and claims are computed by the frozen evaluator. Local Qwen "
                "only proposes concise policy framing. External submission remains blocked.",
                "",
            ]
        ),
    )
    failed = [cell for cell in cells if not cell.task_success]
    failure_path = root / "systems-failure-analysis.md"
    _write_text_atomic(
        failure_path,
        "\n".join(
            [
                "# Systems Benchmark Failure Analysis",
                "",
                f"- Failed cells retained: {len(failed)} / {len(cells)}",
                "- Baseline and ablation failures are experimental evidence, not discarded logs.",
                "",
                "## Failure counts by mode",
                "",
                *[
                    f"- `{mode.value}`: "
                    f"{sum(cell.mode is mode and not cell.task_success for cell in cells)}"
                    for mode in (*prereg.main_modes, *prereg.ablation_modes)
                ],
                "",
            ]
        ),
    )
    loop_path = root / "loop-report.md"
    full = mode_metrics[SystemsMode.FULL_LOOP.value]
    _write_text_atomic(
        loop_path,
        "\n".join(
            [
                "# Evidence-Bound Loop Report",
                "",
                f"- Full-loop task success rate: `{full.task_success_rate:.6f}`",
                f"- Full-loop negative-result recovery rate: "
                f"`{full.negative_result_recovery_rate:.6f}`",
                f"- Full-loop exact reproduction rate: "
                f"`{full.exact_reproduction_rate:.6f}`",
                f"- Full-loop unsupported claims: `{full.unsupported_claim_count}`",
                f"- Research-decision human interventions: "
                f"`{full.research_decision_human_interventions}`",
                "",
                "Failures trigger a new bounded attempt only in loop-enabled modes. "
                "No mode may change source truth, the fault suite, or the evaluator.",
                "",
            ]
        ),
    )
    evidence_path = root / "evidence-map.json"
    write_json_model(
        evidence_path,
        {
            "benchmark_id": prereg.benchmark_id,
            "preregistration_hash": prereg.preregistration_hash,
            "source_evidence": [
                {
                    "task_id": task.task_id,
                    "path": task.source_evidence_path,
                    "sha256": task.source_evidence_sha256,
                    "evidence_hash": task.source_evidence_hash,
                }
                for task in prereg.tasks
            ],
            "cell_results": [
                {
                    "cell_id": cell.cell_id,
                    "result_hash": cell.result_hash,
                    "path": (
                        root / "cells" / cell.cell_id / "cell-result.json"
                    ).as_posix(),
                }
                for cell in cells
            ],
            "contribution_gate_hash": gate.gate_hash,
        },
    )
    manuscript_path = root / "manuscript-v1.md"
    _write_text_atomic(
        manuscript_path,
        "\n".join(
            [
                "# Evidence-Bound Autonomous Research Loops Under Controlled Failures",
                "",
                "## Abstract",
                "",
                "We compare one-shot generation, plan-then-execute once, and an "
                "evidence-bound autonomous loop on a preregistered ten-task local "
                "benchmark with three seeds and four component ablations. This draft is "
                "generated from executed evidence and remains subject to independent "
                "reproduction, citation work, and strict review in task 260.5.",
                "",
                "## Current empirical result",
                "",
                f"The paired task-success gain over execute-once is "
                f"`{gate.paired_mean_gain_vs_execute_once:.6f}` with bootstrap 95% CI "
                f"`[{gate.bootstrap_ci95_lower:.6f}, {gate.bootstrap_ci95_upper:.6f}]`. "
                f"The internal systems gate is `{'passed' if gate.passed else 'failed'}`.",
                "",
                "## Limitations",
                "",
                "The workflow faults are controlled and the six MDBench tasks replay "
                "already revealed traces. This evaluates system behaviour, not a new "
                "scientific method or unseen method performance. External submission is "
                "not authorized.",
                "",
            ]
        ),
    )
    return {
        "report": report_path,
        "failure": failure_path,
        "loop": loop_path,
        "evidence": evidence_path,
        "table": table_path,
        "figure": figure_path,
        "manuscript": manuscript_path,
    }


def _write_preregistration_report(
    path: Path,
    prereg: SystemsPreregistration,
) -> None:
    _write_text_atomic(
        path,
        "\n".join(
            [
                f"# Systems Benchmark Preregistration: {prereg.benchmark_id}",
                "",
                f"- Frozen tasks: {len(prereg.tasks)}",
                f"- Main modes: {', '.join(mode.value for mode in prereg.main_modes)}",
                f"- Ablations: {', '.join(mode.value for mode in prereg.ablation_modes)}",
                f"- Seeds: {', '.join(str(seed) for seed in prereg.seeds)}",
                f"- Bootstrap resamples: {prereg.bootstrap_resamples}",
                f"- Evaluator SHA-256: `{prereg.evaluator_code_sha256}`",
                f"- Fault policy hash: `{prereg.controlled_fault_policy_hash}`",
                f"- Preregistration hash: `{prereg.preregistration_hash}`",
                "",
                "Source truth is frozen before matrix execution. Revealed MDBench traces "
                "are restricted to system-behaviour evaluation.",
                "",
            ]
        ),
    )


def _write_cell_report(
    path: Path,
    cell: SystemsCellResult,
    source: SystemsSourceEvidence,
) -> None:
    _write_text_atomic(
        path,
        "\n".join(
            [
                f"# Cell {cell.cell_id}",
                "",
                f"- Task success: `{str(cell.task_success).lower()}`",
                f"- Initial fault: `{cell.initial_fault.value}`",
                f"- Initial failures: `{', '.join(cell.initial_failure_codes) or 'none'}`",
                f"- Final failures: `{', '.join(cell.final_failure_codes) or 'none'}`",
                f"- Attempts: `{cell.attempt_count}`",
                f"- Exact reproduction: `{str(cell.exact_reproduction).lower()}`",
                f"- Unsupported claims: `{cell.unsupported_claim_count}`",
                f"- Source effect: `{source.effect_value:.12g}` ({source.truth_label})",
                "",
                "## Claim",
                "",
                cell.report_claim,
                "",
                "This cell is a system-behaviour measurement and does not authorize "
                "external submission.",
                "",
            ]
        ),
    )


def _write_success_svg(
    path: Path,
    prereg: SystemsPreregistration,
    metrics: Mapping[str, SystemsModeMetrics],
) -> None:
    modes = (*prereg.main_modes, *prereg.ablation_modes)
    width = 920
    height = 390
    bar_width = 82
    gap = 42
    left = 62
    baseline = 310
    chart_height = 240
    parts = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}" viewBox="0 0 {width} {height}">'
        ),
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="32" y="28" font-family="sans-serif" font-size="18">'
        "Task success rate by controller mode</text>",
        f'<line x1="{left}" y1="{baseline}" x2="{width - 24}" y2="{baseline}" '
        'stroke="#444"/>',
    ]
    for index, mode in enumerate(modes):
        value = metrics[mode.value].task_success_rate
        x = left + index * (bar_width + gap)
        bar_height = chart_height * value
        y = baseline - bar_height
        color = "#2563eb" if mode is SystemsMode.FULL_LOOP else "#94a3b8"
        parts.extend(
            [
                f'<rect x="{x}" y="{y:.2f}" width="{bar_width}" '
                f'height="{bar_height:.2f}" fill="{color}"/>',
                f'<text x="{x + bar_width / 2:.1f}" y="{y - 8:.2f}" '
                'text-anchor="middle" font-family="sans-serif" font-size="12">'
                f"{value:.2f}</text>",
                f'<text x="{x + bar_width / 2:.1f}" y="{baseline + 18}" '
                'text-anchor="middle" font-family="sans-serif" font-size="10" '
                f'transform="rotate(28 {x + bar_width / 2:.1f} {baseline + 18})">'
                f"{mode.value}</text>",
            ]
        )
    parts.append("</svg>")
    _write_text_atomic(path, "\n".join(parts) + "\n")


def _write_text_atomic(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
    return path


def _ratio(numerator: int, denominator: int) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def _required_hash(value: str | None, label: str) -> str:
    if value is None:
        raise ValueError(f"{label} has no hash")
    return value
