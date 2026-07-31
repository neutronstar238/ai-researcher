"""Result-blind plan for an autonomous, formal MDBench recovery campaign.

This module deliberately does not contain a candidate scientific method.  It
binds two completed negative cycles, snapshots primary literature, creates a
development panel, and commits a disjoint confirmation panel before any model
call or numerical result is opened.  Candidate code and the paper must be
produced later by the same autonomous run ledger.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import Field, ValidationError, model_validator

from autoresearch.competition.gate_a import (
    GateAAdjudicationError,
    GateADecision,
    MDBenchGateAReport,
    load_mdbench_gate_a_report,
)
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import (
    MDBenchArchiveManifest,
    MDBenchExperimentMatrix,
    StrictFrozenModel,
)
from autoresearch.competition.preregistration import (
    MDBenchPreregistrationError,
    validate_mdbench_preregistration,
)
from autoresearch.competition.recovery import (
    MDBenchGateARecoveryPreregistration,
    MDBenchRecoveryError,
    validate_mdbench_recovery_preregistration,
)

_PROTOCOL_ID = "mdbench-autonomous-formal-recovery-v1"
_PLAN_NAME = "autonomous-research-plan.json"
_MARKDOWN_NAME = "autonomous-research-plan.md"
_CONFIRMATION_NAME = "confirmation-panel.sealed.json"
_CONDITIONS = ("clean", "snr_20")
_DEVELOPMENT_SEEDS = (101, 211, 307)
_CONFIRMATION_SEEDS = (401, 503, 601)
_FORBIDDEN_OUTPUT_NAMES = {
    "attempts",
    "candidates",
    "execution",
    "execution-report.json",
    "gate-a-adjudication.json",
    "manuscript",
    "paper",
    "results",
}
_MAX_SOURCE_BYTES = 8 * 1024 * 1024

DataType = Literal["ode", "pde"]
SourceDomain = Literal["autonomous_research", "equation_discovery"]
SourceFetcher = Callable[
    ["AutonomousRecoverySourceSpec", int],
    tuple[bytes, str, int],
]


class AutonomousRecoveryError(RuntimeError):
    """Raised when the autonomous recovery plan leaks, drifts, or is incomplete."""


class AutonomousRecoverySourceSpec(StrictFrozenModel):
    """One primary source and the architecture implication it is allowed to support."""

    source_id: str
    domain: SourceDomain
    title: str
    year: int = Field(ge=2000, le=2100)
    url: str
    required_marker: str
    design_implication: str


AUTONOMOUS_RECOVERY_SOURCE_SPECS: tuple[AutonomousRecoverySourceSpec, ...] = (
    AutonomousRecoverySourceSpec(
        source_id="ai-scientist-v2",
        domain="autonomous_research",
        title=(
            "The AI Scientist-v2: Workshop-Level Automated Scientific Discovery "
            "via Agentic Tree Search"
        ),
        year=2025,
        url="https://arxiv.org/abs/2504.08066",
        required_marker="AI Scientist-v2",
        design_implication=(
            "Use progressive branching and empirical pruning instead of one-shot method generation."
        ),
    ),
    AutonomousRecoverySourceSpec(
        source_id="mlrc-bench",
        domain="autonomous_research",
        title="MLRC-Bench: Can Language Agents Solve Machine Learning Research Challenges?",
        year=2025,
        url="https://arxiv.org/abs/2504.09702",
        required_marker="MLRC-Bench",
        design_implication=(
            "Judge research with executable objective outcomes; model ratings cannot establish progress."
        ),
    ),
    AutonomousRecoverySourceSpec(
        source_id="execution-grounded-ai-research",
        domain="autonomous_research",
        title="Execution-Grounded Automated AI Research",
        year=2026,
        url="https://arxiv.org/abs/2601.14525",
        required_marker="Execution-Grounded Automated AI Research",
        design_implication=(
            "Feed real execution evidence into evolutionary selection and retain failed branches."
        ),
    ),
    AutonomousRecoverySourceSpec(
        source_id="mars",
        domain="autonomous_research",
        title="MARS: A Multi-Agent Framework for Automated Scientific Research",
        year=2026,
        url="https://arxiv.org/abs/2602.02660",
        required_marker="MARS",
        design_implication=(
            "Use a budget-aware modular search with comparative memory across executed branches."
        ),
    ),
    AutonomousRecoverySourceSpec(
        source_id="ai-research-agents",
        domain="autonomous_research",
        title="AI Research Agents for Machine Learning",
        year=2025,
        url="https://arxiv.org/abs/2507.02554",
        required_marker="AI Research Agents",
        design_implication=(
            "Treat search policy, edit operators, and objective evaluator as a coupled system."
        ),
    ),
    AutonomousRecoverySourceSpec(
        source_id="codescientist",
        domain="autonomous_research",
        title="CodeScientist: End-to-End Semi-Automated Scientific Discovery with Code",
        year=2025,
        url="https://arxiv.org/abs/2503.22708",
        required_marker="CodeScientist",
        design_implication=(
            "Search over executable code and require replication, ablation, and failure retention."
        ),
    ),
    AutonomousRecoverySourceSpec(
        source_id="wsindy",
        domain="equation_discovery",
        title="Robust learning of differential equations from data using weak form",
        year=2021,
        url="https://pmc.ncbi.nlm.nih.gov/articles/PMC8570254/",
        required_marker="weak form",
        design_implication=(
            "Expose test-function, threshold-learning, and scale handling as generated mechanisms."
        ),
    ),
    AutonomousRecoverySourceSpec(
        source_id="ensemble-sindy",
        domain="equation_discovery",
        title="Ensemble-SINDy: Robust sparse model discovery in the low-data, high-noise limit",
        year=2022,
        url="https://pmc.ncbi.nlm.nih.gov/articles/PMC9006119/",
        required_marker="SINDy",
        design_implication=(
            "Allow data and library bagging plus coefficient aggregation as searchable operators."
        ),
    ),
    AutonomousRecoverySourceSpec(
        source_id="wendy",
        domain="equation_discovery",
        title="Weak-form estimation of nonlinear dynamics",
        year=2023,
        url="https://pmc.ncbi.nlm.nih.gov/articles/PMC10556152/",
        required_marker="WENDy",
        design_implication=(
            "Treat weak regression as errors-in-variables and evaluate covariance-aware fitting."
        ),
    ),
    AutonomousRecoverySourceSpec(
        source_id="weakident",
        domain="equation_discovery",
        title="WeakIdent: Weak formulation for identifying differential equations",
        year=2022,
        url="https://arxiv.org/abs/2211.03134",
        required_marker="WeakIdent",
        design_implication=(
            "Allow narrow-fit, trimming, subspace pursuit, and cross-validation combinations."
        ),
    ),
    AutonomousRecoverySourceSpec(
        source_id="sr3",
        domain="equation_discovery",
        title=(
            "A unified sparse optimization framework to learn parsimonious "
            "physics-informed models from data"
        ),
        year=2019,
        url="https://arxiv.org/abs/1906.10612",
        required_marker="A unified sparse optimization framework",
        design_implication=(
            "Permit constrained and nonconvex sparsity solvers under the same execution budget."
        ),
    ),
    AutonomousRecoverySourceSpec(
        source_id="pde-read",
        domain="equation_discovery",
        title="PDE-READ: Human-readable partial differential equation discovery",
        year=2021,
        url="https://arxiv.org/abs/2111.00998",
        required_marker="PDE-READ",
        design_implication=(
            "Permit learned denoising surrogates while keeping equation scoring objective and explicit."
        ),
    ),
)


class AutonomousRecoverySourceSnapshot(StrictFrozenModel):
    """Content-addressed live evidence for one primary source."""

    source_id: str
    domain: SourceDomain
    title: str
    year: int
    source_url: str
    final_url: str
    status_code: int = Field(ge=200, le=299)
    required_marker: str
    marker_verified: bool
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_relative_path: str
    retrieved_at: datetime
    primary_source: bool = True
    redistribution_authorized: bool = False
    design_implication: str

    @model_validator(mode="after")
    def _require_verified_primary_source(self) -> AutonomousRecoverySourceSnapshot:
        if not self.marker_verified or not self.primary_source:
            raise ValueError("an autonomous recovery source must be a verified primary source")
        if self.redistribution_authorized:
            raise ValueError("source-page retrieval does not establish redistribution permission")
        return self


class AutonomousPanelSystem(StrictFrozenModel):
    """Metadata-only identity and artifact commitment for one official system."""

    data_type: DataType
    system_name: str
    selection_rank: int = Field(ge=1)
    selection_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_paths: dict[str, str]
    artifact_sha256: dict[str, str]

    @model_validator(mode="after")
    def _require_clean_and_noisy_artifacts(self) -> AutonomousPanelSystem:
        if set(self.artifact_paths) != set(_CONDITIONS):
            raise ValueError("panel systems require exactly clean and snr_20 artifact paths")
        if set(self.artifact_sha256) != set(_CONDITIONS):
            raise ValueError("panel systems require exactly clean and snr_20 artifact hashes")
        return self


class AutonomousDevelopmentPanel(StrictFrozenModel):
    """Only panel visible to generation, repair, selection, and comparative memory."""

    schema_version: str = "autonomous-mdbench-development-panel-v1"
    split_id: Literal["development"] = "development"
    seeds: tuple[int, ...]
    conditions: tuple[str, ...] = _CONDITIONS
    systems: tuple[AutonomousPanelSystem, ...]
    numeric_payload_opened_during_freeze: bool = False
    research_agent_read_allowed: bool = True

    @model_validator(mode="after")
    def _require_formal_development_panel(self) -> AutonomousDevelopmentPanel:
        _validate_panel_shape(self.systems, self.seeds)
        if self.conditions != _CONDITIONS:
            raise ValueError("development conditions changed")
        if self.numeric_payload_opened_during_freeze:
            raise ValueError("development panel freeze must not open numerical payloads")
        if not self.research_agent_read_allowed:
            raise ValueError("the development panel must be available to the research runtime")
        return self


class AutonomousConfirmationPanel(StrictFrozenModel):
    """Separate confirmation identity file, hidden from research agents until search freeze."""

    schema_version: str = "autonomous-mdbench-confirmation-panel-v1"
    split_id: Literal["sealed_confirmation"] = "sealed_confirmation"
    seeds: tuple[int, ...]
    conditions: tuple[str, ...] = _CONDITIONS
    systems: tuple[AutonomousPanelSystem, ...]
    numeric_payload_opened_during_freeze: bool = False
    research_agent_read_allowed: bool = False
    panel_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _require_sealed_confirmation_panel(self) -> AutonomousConfirmationPanel:
        _validate_panel_shape(self.systems, self.seeds)
        if self.conditions != _CONDITIONS:
            raise ValueError("confirmation conditions changed")
        if self.numeric_payload_opened_during_freeze:
            raise ValueError("confirmation freeze must not open numerical payloads")
        if self.research_agent_read_allowed:
            raise ValueError("confirmation identities must remain hidden during search")
        return self


class AutonomousPanelCommitment(StrictFrozenModel):
    """Public commitment to the sealed panel without revealing system identities."""

    split_id: Literal["sealed_confirmation"] = "sealed_confirmation"
    ode_system_count: int = 10
    pde_system_count: int = 4
    condition_count: int = 2
    seed_count: int = 3
    panel_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    sealed_panel_path: str
    research_agent_read_allowed: bool = False
    unseal_rule: str

    @model_validator(mode="after")
    def _require_fixed_shape_and_seal(self) -> AutonomousPanelCommitment:
        if (self.ode_system_count, self.pde_system_count) != (10, 4):
            raise ValueError("confirmation commitment must bind 10 ODE and 4 PDE systems")
        if (self.condition_count, self.seed_count) != (2, 3):
            raise ValueError("confirmation commitment must bind two conditions and three seeds")
        if self.research_agent_read_allowed:
            raise ValueError("sealed confirmation metadata cannot be exposed to research agents")
        return self


class AutonomousCycleBinding(StrictFrozenModel):
    """Content-addressed binding to one already closed formal competition cycle."""

    cycle_id: Literal["parent", "recovery"]
    matrix_path: str
    matrix_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    preregistration_path: str | None = None
    preregistration_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    report_path: str
    report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: GateADecision
    gate_b_allowed: bool
    candidate_method_id: str
    selected_baseline_method_id: str

    @model_validator(mode="after")
    def _require_closed_negative_cycle(self) -> AutonomousCycleBinding:
        if self.decision is not GateADecision.NEGATIVE_RESULT or self.gate_b_allowed:
            raise ValueError("autonomous recovery requires a closed negative predecessor cycle")
        if (self.preregistration_path is None) != (self.preregistration_hash is None):
            raise ValueError("recovery preregistration path and hash must be supplied together")
        if self.cycle_id == "recovery" and self.preregistration_path is None:
            raise ValueError("the recovery cycle requires its leakage preregistration binding")
        return self


class AutonomousFailureSummary(StrictFrozenModel):
    """Machine-derived failure facts; this is diagnosis, not a hand-authored new method."""

    cycle_id: Literal["parent", "recovery"]
    candidate_method_id: str
    baseline_method_id: str
    succeeded_count: int = Field(ge=0)
    total_attempt_count: int = Field(ge=1)
    failure_aware_system_median_relative_improvement: float
    bootstrap_ci95_lower: float
    bootstrap_ci95_upper: float
    required_relative_improvement: float
    failed_mandatory_check_ids: tuple[str, ...]
    negative_reasons: tuple[str, ...]


class AutonomousOriginPolicy(StrictFrozenModel):
    """Non-negotiable test for whether the system, rather than the operator, did the research."""

    allowed_human_scientific_input: tuple[str, ...] = (
        "one high-level competition objective supplied before the run",
    )
    post_start_human_scientific_decisions_allowed: bool = False
    human_authored_candidate_code_allowed: bool = False
    fixed_candidate_catalogue_allowed: bool = False
    code_side_scientific_repair_allowed: bool = False
    model_generated_exact_code_required: bool = True
    minimum_generated_candidates: int = 8
    maximum_generated_candidates: int = 12
    minimum_mechanism_families: int = 3
    minimum_generations: int = 2
    objective_execution_reward_required: bool = True
    llm_self_score_can_pass_gate: bool = False
    every_branch_retained: bool = True
    runtime_literature_refresh_required: bool = True
    manuscript_generated_inside_same_ledger: bool = True
    provider_hardcoding_allowed: bool = False
    provider_configuration_fields: tuple[str, ...] = (
        "base_url",
        "api_key",
        "model_name",
    )
    human_owned_boundaries: tuple[str, ...] = (
        "safety approval",
        "private-data approval",
        "license and public-release approval",
        "authorship and submission decision",
    )

    @model_validator(mode="after")
    def _require_autonomous_origin(self) -> AutonomousOriginPolicy:
        forbidden_true = (
            self.post_start_human_scientific_decisions_allowed,
            self.human_authored_candidate_code_allowed,
            self.fixed_candidate_catalogue_allowed,
            self.code_side_scientific_repair_allowed,
            self.llm_self_score_can_pass_gate,
            self.provider_hardcoding_allowed,
        )
        if any(forbidden_true):
            raise ValueError("autonomous origin forbids hidden human or judge-side research")
        required_true = (
            self.model_generated_exact_code_required,
            self.objective_execution_reward_required,
            self.every_branch_retained,
            self.runtime_literature_refresh_required,
            self.manuscript_generated_inside_same_ledger,
        )
        if not all(required_true):
            raise ValueError("autonomous origin requirements cannot be disabled")
        if not 8 <= self.minimum_generated_candidates <= self.maximum_generated_candidates <= 12:
            raise ValueError("candidate count must remain within the frozen 8-to-12 budget")
        if self.minimum_mechanism_families < 3 or self.minimum_generations < 2:
            raise ValueError("autonomous search needs multiple families and generations")
        if set(self.provider_configuration_fields) != {"base_url", "api_key", "model_name"}:
            raise ValueError("provider-neutral configuration contract changed")
        return self


class AutonomousSearchPolicy(StrictFrozenModel):
    """Budgeted literature-to-code search whose reward comes only from execution."""

    search_algorithm: Literal["budgeted_evolutionary_tree_search"] = (
        "budgeted_evolutionary_tree_search"
    )
    operators: tuple[str, ...] = (
        "literature_derive",
        "mechanism_compose",
        "code_implement",
        "execute",
        "reflect_from_metrics",
        "mutate",
        "ablate",
        "replicate",
    )
    initial_candidate_count: int = 8
    maximum_candidate_count: int = 12
    generation_count: int = 2
    minimum_mechanism_families: int = 3
    pilot_candidate_cell_budget: int = 96
    full_development_finalist_count: int = 3
    full_development_candidate_cell_budget: int = 252
    exploration_fraction: float = Field(default=0.25, ge=0.2, le=0.5)
    maximum_seconds_per_cell: int = 300
    maximum_cpu_cores_per_cell: int = 4
    maximum_memory_mb_per_cell: int = 8192
    required_runtime_capabilities: tuple[str, ...] = (
        "ode",
        "pde_1d",
        "pde_2d",
        "pde_3d",
        "multi_field",
    )
    primary_metric: Literal["derivative_nmse"] = "derivative_nmse"
    selection_metrics: tuple[str, ...] = (
        "derivative_nmse",
        "equation_structure_f1",
        "trajectory_extrapolation_nmse_ode",
        "model_complexity",
        "noise_robustness_ratio",
        "wall_time_seconds",
        "peak_rss_mb",
    )
    missing_cell_policy: str = "terminal failure receives zero primary improvement"
    comparative_memory_scope: Literal["development_only"] = "development_only"
    confirmation_reselection_allowed: bool = False

    @model_validator(mode="after")
    def _require_bounded_objective_search(self) -> AutonomousSearchPolicy:
        if self.initial_candidate_count != 8 or self.maximum_candidate_count != 12:
            raise ValueError("formal search candidate budget changed")
        if self.generation_count < 2 or self.minimum_mechanism_families < 3:
            raise ValueError("formal search breadth changed")
        if self.full_development_finalist_count != 3:
            raise ValueError("formal stage-racing finalist count changed")
        if self.confirmation_reselection_allowed:
            raise ValueError("confirmation results cannot select or repair a method")
        if set(self.required_runtime_capabilities) != {
            "ode",
            "pde_1d",
            "pde_2d",
            "pde_3d",
            "multi_field",
        }:
            raise ValueError("formal recovery must support the untouched multidimensional PDEs")
        return self


class AutonomousRecoveryLineage(StrictFrozenModel):
    """Immutable official data and predecessor-cycle identities."""

    archive_manifest_path: str
    benchmark_revision: str
    dataset_doi: str
    dataset_license: str
    archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    inventory_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_cycle: AutonomousCycleBinding
    recovery_cycle: AutonomousCycleBinding


class AutonomousMDBenchRecoveryPlan(StrictFrozenModel):
    """Hash-bound handoff from formal planning to autonomous implementation."""

    schema_version: str = "autonomous-mdbench-recovery-plan-v1"
    protocol_id: str = _PROTOCOL_ID
    research_brief: str
    lineage: AutonomousRecoveryLineage
    failure_summaries: tuple[AutonomousFailureSummary, ...]
    evidence_sources: tuple[AutonomousRecoverySourceSnapshot, ...]
    excluded_prior_systems: tuple[str, ...]
    untouched_ode_system_count: int
    untouched_pde_system_count: int
    development_panel: AutonomousDevelopmentPanel
    confirmation_commitment: AutonomousPanelCommitment
    origin_policy: AutonomousOriginPolicy
    search_policy: AutonomousSearchPolicy
    acceptance_criteria: tuple[str, ...]
    candidate_hypotheses: tuple[str, ...] = ()
    model_interaction_count: int = 0
    generated_candidate_count: int = 0
    result_record_count: int = 0
    manuscript_count: int = 0
    post_start_human_scientific_decision_count: int = 0
    development_generation_authorized: bool = True
    development_execution_authorized: bool = False
    confirmation_access_authorized: bool = False
    publication_ready: bool = False
    public_release_authorized: bool = False
    submission_authorized: bool = False
    next_required_task: str = "265.2"
    frozen_at: datetime
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str
    markdown_path: str

    @model_validator(mode="after")
    def _require_result_free_autonomous_handoff(self) -> AutonomousMDBenchRecoveryPlan:
        if len(self.failure_summaries) != 2:
            raise ValueError("the plan must diagnose both completed negative cycles")
        if {item.cycle_id for item in self.failure_summaries} != {"parent", "recovery"}:
            raise ValueError("failure summaries must cover parent and recovery cycles")
        domains = {domain: 0 for domain in ("autonomous_research", "equation_discovery")}
        for source in self.evidence_sources:
            domains[source.domain] += 1
        if any(count < 6 for count in domains.values()):
            raise ValueError("the plan requires at least six primary sources in each domain")
        if len({source.source_id for source in self.evidence_sources}) != len(
            self.evidence_sources
        ):
            raise ValueError("source IDs must be unique")
        if (self.untouched_ode_system_count, self.untouched_pde_system_count) != (43, 8):
            raise ValueError("official untouched inventory changed")
        activity_counts = (
            len(self.candidate_hypotheses),
            self.model_interaction_count,
            self.generated_candidate_count,
            self.result_record_count,
            self.manuscript_count,
            self.post_start_human_scientific_decision_count,
        )
        if any(activity_counts):
            raise ValueError("Task 265.1 must remain candidate-, model-, result-, and paper-free")
        if not self.development_generation_authorized:
            raise ValueError("a valid plan must authorize the next generation task")
        forbidden_permissions = (
            self.development_execution_authorized,
            self.confirmation_access_authorized,
            self.publication_ready,
            self.public_release_authorized,
            self.submission_authorized,
        )
        if any(forbidden_permissions):
            raise ValueError("planning cannot authorize execution, confirmation, or publication")
        if self.next_required_task != "265.2":
            raise ValueError("the implementation handoff must point to Task 265.2")
        return self


def freeze_autonomous_mdbench_research_plan(
    archive_manifest_path: Path | str,
    parent_matrix_path: Path | str,
    parent_report_path: Path | str,
    recovery_preregistration_path: Path | str,
    recovery_matrix_path: Path | str,
    recovery_report_path: Path | str,
    output_dir: Path | str,
    *,
    research_brief: str = (
        "在官方 MDBench 上由系统自主检索、提出、实现、淘汰和复验研究方法，并由同一运行账本"
        "生成论文草稿；人类仅提供参赛目标和治理边界。"
    ),
    source_fetcher: SourceFetcher | None = None,
    timeout_seconds: int = 20,
) -> AutonomousMDBenchRecoveryPlan:
    """Freeze the formal autonomous-research plan without reading numerical payloads."""

    if timeout_seconds < 1:
        raise AutonomousRecoveryError("source timeout must be positive")
    paths = _InputPaths.resolve(
        archive_manifest_path=archive_manifest_path,
        parent_matrix_path=parent_matrix_path,
        parent_report_path=parent_report_path,
        recovery_preregistration_path=recovery_preregistration_path,
        recovery_matrix_path=recovery_matrix_path,
        recovery_report_path=recovery_report_path,
    )
    (
        manifest,
        parent_matrix,
        parent_report,
        recovery_preregistration,
        recovery_matrix,
        recovery_report,
    ) = _load_and_validate_inputs(paths)
    lineage = _build_lineage(
        paths,
        manifest,
        parent_matrix,
        parent_report,
        recovery_preregistration,
        recovery_matrix,
        recovery_report,
    )
    output_root = Path(output_dir).resolve()
    plan_path = output_root / _PLAN_NAME
    if plan_path.is_file():
        existing = load_autonomous_mdbench_research_plan(plan_path)
        if existing.lineage != lineage or existing.research_brief != research_brief:
            raise AutonomousRecoveryError(
                "refusing to reuse an autonomous plan with different inputs or brief"
            )
        return existing
    _reject_research_activity(output_root)

    prior_keys = {
        (case.data_type, case.system_name)
        for matrix in (parent_matrix, recovery_matrix)
        for case in matrix.systems
    }
    available = _available_untouched_systems(manifest, prior_keys)
    development_systems, confirmation_systems = _split_panels(
        manifest,
        available,
    )
    development_panel = AutonomousDevelopmentPanel(
        seeds=_DEVELOPMENT_SEEDS,
        systems=development_systems,
    )
    confirmation_path = output_root / ".sealed" / _CONFIRMATION_NAME
    confirmation_panel = _build_confirmation_panel(
        confirmation_systems,
        confirmation_path,
    )
    snapshots, source_bodies = _fetch_source_snapshots(
        source_fetcher or _default_source_fetcher,
        timeout_seconds=timeout_seconds,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    for snapshot, body in zip(snapshots, source_bodies, strict=True):
        _write_bytes_atomically(output_root / snapshot.snapshot_relative_path, body)
    write_json_model(confirmation_path, confirmation_panel)

    output_path = output_root / _PLAN_NAME
    markdown_path = output_root / _MARKDOWN_NAME
    failure_summaries = (
        _failure_summary("parent", parent_report),
        _failure_summary("recovery", recovery_report),
    )
    acceptance_criteria = (
        "the runtime generates 8 to 12 exact-code candidates spanning at least three mechanism families without a fixed catalogue or human-authored candidate",
        "all selection and mutation decisions use objective development execution evidence; LLM self-scores are never a scientific gate",
        "the selected method, code, search state, comparative memory, failures, ablations, replications, and manuscript share one append-only run ledger",
        "the selected candidate improves sealed-confirmation snr_20 system-level median derivative NMSE by at least 5 percent versus the strongest official baseline",
        "the paired system-level bootstrap 95 percent confidence lower bound for that confirmation improvement is greater than zero",
        "all frozen confirmation cells terminate and missing cells receive zero primary improvement",
        "structure, trajectory, complexity, robustness, wall time, and peak memory remain reported even when unfavorable",
        "confirmation results cannot trigger candidate repair, reselection, metric substitution, panel substitution, or another confirmation attempt",
        "a negative result is retained and the system-generated manuscript must state it; publication and submission remain human decisions",
    )
    unstamped = AutonomousMDBenchRecoveryPlan(
        research_brief=research_brief,
        lineage=lineage,
        failure_summaries=failure_summaries,
        evidence_sources=snapshots,
        excluded_prior_systems=tuple(
            f"{data_type}/{system_name}" for data_type, system_name in sorted(prior_keys)
        ),
        untouched_ode_system_count=len(available["ode"]),
        untouched_pde_system_count=len(available["pde"]),
        development_panel=development_panel,
        confirmation_commitment=AutonomousPanelCommitment(
            panel_hash=confirmation_panel.panel_hash,
            sealed_panel_path=confirmation_path.as_posix(),
            unseal_rule=(
                "only a hash-bound Task 265.2 search-freeze receipt may expose identities to "
                "the independent confirmation executor; research agents and comparative memory "
                "remain denied"
            ),
        ),
        origin_policy=AutonomousOriginPolicy(),
        search_policy=AutonomousSearchPolicy(),
        acceptance_criteria=acceptance_criteria,
        frozen_at=datetime.now(timezone.utc),
        plan_hash="0" * 64,
        output_path=output_path.as_posix(),
        markdown_path=markdown_path.as_posix(),
    )
    plan = unstamped.model_copy(update={"plan_hash": canonical_model_hash(_plan_payload(unstamped))})
    write_json_model(output_path, plan)
    markdown_path.write_text(_render_markdown(plan), encoding="utf-8")
    load_autonomous_mdbench_research_plan(output_path)
    return plan


def load_autonomous_mdbench_research_plan(
    path: Path | str,
) -> AutonomousMDBenchRecoveryPlan:
    """Load a frozen plan and verify plan, source, and sealed-panel commitments."""

    resolved = Path(path).resolve()
    try:
        plan = AutonomousMDBenchRecoveryPlan.model_validate_json(
            resolved.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as exc:
        raise AutonomousRecoveryError(f"cannot load autonomous recovery plan: {exc}") from exc
    if Path(plan.output_path).resolve() != resolved:
        raise AutonomousRecoveryError("autonomous plan output path mismatch")
    expected_hash = canonical_model_hash(_plan_payload(plan))
    if plan.plan_hash != expected_hash:
        raise AutonomousRecoveryError(
            f"autonomous plan hash mismatch: {expected_hash} != {plan.plan_hash}"
        )
    output_root = resolved.parent
    _reject_research_activity(output_root)
    for source in plan.evidence_sources:
        snapshot_path = (output_root / source.snapshot_relative_path).resolve()
        if output_root not in snapshot_path.parents:
            raise AutonomousRecoveryError("source snapshot escapes the autonomous output root")
        if not snapshot_path.is_file():
            raise AutonomousRecoveryError(f"source snapshot missing: {source.source_id}")
        if _sha256_file(snapshot_path) != source.content_sha256:
            raise AutonomousRecoveryError(f"source snapshot hash mismatch: {source.source_id}")
    confirmation_path = Path(plan.confirmation_commitment.sealed_panel_path).resolve()
    if not confirmation_path.is_file():
        raise AutonomousRecoveryError("sealed confirmation panel is missing")
    try:
        confirmation = AutonomousConfirmationPanel.model_validate_json(
            confirmation_path.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as exc:
        raise AutonomousRecoveryError(f"cannot load sealed confirmation panel: {exc}") from exc
    if Path(confirmation.output_path).resolve() != confirmation_path:
        raise AutonomousRecoveryError("sealed confirmation output path mismatch")
    computed_panel_hash = canonical_model_hash(_confirmation_payload(confirmation))
    if confirmation.panel_hash != computed_panel_hash:
        raise AutonomousRecoveryError("sealed confirmation panel hash mismatch")
    if confirmation.panel_hash != plan.confirmation_commitment.panel_hash:
        raise AutonomousRecoveryError("confirmation commitment does not match sealed panel")
    development_keys = {
        (system.data_type, system.system_name) for system in plan.development_panel.systems
    }
    confirmation_keys = {
        (system.data_type, system.system_name) for system in confirmation.systems
    }
    if development_keys & confirmation_keys:
        raise AutonomousRecoveryError("development and confirmation panels overlap")
    if (development_keys | confirmation_keys) & {
        tuple(item.split("/", maxsplit=1)) for item in plan.excluded_prior_systems
    }:
        raise AutonomousRecoveryError("an autonomous panel reuses a predecessor-cycle system")
    return plan


class _InputPaths(StrictFrozenModel):
    archive_manifest: Path
    parent_matrix: Path
    parent_report: Path
    recovery_preregistration: Path
    recovery_matrix: Path
    recovery_report: Path

    @classmethod
    def resolve(
        cls,
        *,
        archive_manifest_path: Path | str,
        parent_matrix_path: Path | str,
        parent_report_path: Path | str,
        recovery_preregistration_path: Path | str,
        recovery_matrix_path: Path | str,
        recovery_report_path: Path | str,
    ) -> _InputPaths:
        return cls(
            archive_manifest=Path(archive_manifest_path).resolve(),
            parent_matrix=Path(parent_matrix_path).resolve(),
            parent_report=Path(parent_report_path).resolve(),
            recovery_preregistration=Path(recovery_preregistration_path).resolve(),
            recovery_matrix=Path(recovery_matrix_path).resolve(),
            recovery_report=Path(recovery_report_path).resolve(),
        )


def _load_and_validate_inputs(
    paths: _InputPaths,
) -> tuple[
    MDBenchArchiveManifest,
    MDBenchExperimentMatrix,
    MDBenchGateAReport,
    MDBenchGateARecoveryPreregistration,
    MDBenchExperimentMatrix,
    MDBenchGateAReport,
]:
    try:
        manifest = MDBenchArchiveManifest.model_validate_json(
            paths.archive_manifest.read_text(encoding="utf-8")
        )
        parent_matrix = _load_matrix(paths.parent_matrix, "parent")
        parent_report = load_mdbench_gate_a_report(paths.parent_report)
        recovery_matrix = _load_matrix(paths.recovery_matrix, "recovery")
        recovery_preregistration = MDBenchGateARecoveryPreregistration.model_validate_json(
            paths.recovery_preregistration.read_text(encoding="utf-8")
        )
        validate_mdbench_recovery_preregistration(
            recovery_preregistration,
            recovery_matrix,
        )
        recovery_report = load_mdbench_gate_a_report(paths.recovery_report)
    except (
        GateAAdjudicationError,
        MDBenchPreregistrationError,
        MDBenchRecoveryError,
        OSError,
        ValidationError,
    ) as exc:
        raise AutonomousRecoveryError(f"cannot load formal predecessor evidence: {exc}") from exc
    if Path(manifest.output_path).resolve() != paths.archive_manifest:
        raise AutonomousRecoveryError("archive manifest output path mismatch")
    expected_inventory_hash = canonical_model_hash(
        {
            "artifacts": [item.model_dump(mode="json") for item in manifest.artifacts],
            "archive_sha256": manifest.archive_sha256,
        }
    )
    if manifest.inventory_hash != expected_inventory_hash:
        raise AutonomousRecoveryError("archive manifest inventory hash mismatch")
    if Path(recovery_preregistration.output_path).resolve() != paths.recovery_preregistration:
        raise AutonomousRecoveryError("recovery preregistration output path mismatch")
    _validate_cycle(
        parent_matrix,
        parent_report,
        manifest,
        expected_candidate="stability_sindy",
        label="parent",
    )
    _validate_cycle(
        recovery_matrix,
        recovery_report,
        manifest,
        expected_candidate="weak_stability_sindy",
        label="recovery",
    )
    if Path(recovery_preregistration.matrix_path).resolve() != paths.recovery_matrix:
        raise AutonomousRecoveryError("recovery preregistration matrix path mismatch")
    if recovery_preregistration.matrix_hash != recovery_matrix.matrix_hash:
        raise AutonomousRecoveryError("recovery preregistration matrix hash mismatch")
    return (
        manifest,
        parent_matrix,
        parent_report,
        recovery_preregistration,
        recovery_matrix,
        recovery_report,
    )


def _load_matrix(path: Path, label: str) -> MDBenchExperimentMatrix:
    matrix = MDBenchExperimentMatrix.model_validate_json(path.read_text(encoding="utf-8"))
    validate_mdbench_preregistration(matrix)
    if Path(matrix.output_path).resolve() != path:
        raise AutonomousRecoveryError(f"{label} matrix output path mismatch")
    return matrix


def _validate_cycle(
    matrix: MDBenchExperimentMatrix,
    report: MDBenchGateAReport,
    manifest: MDBenchArchiveManifest,
    *,
    expected_candidate: str,
    label: str,
) -> None:
    if Path(report.matrix_path).resolve() != Path(matrix.output_path).resolve():
        raise AutonomousRecoveryError(f"{label} report matrix path mismatch")
    if report.matrix_hash != matrix.matrix_hash:
        raise AutonomousRecoveryError(f"{label} report matrix hash mismatch")
    if report.decision is not GateADecision.NEGATIVE_RESULT or report.gate_b_allowed:
        raise AutonomousRecoveryError(f"{label} cycle is not a closed negative result")
    if report.candidate_method_id != expected_candidate:
        raise AutonomousRecoveryError(f"{label} candidate identity changed")
    lineage_values = (
        (matrix.benchmark_revision, manifest.benchmark_revision, "revision"),
        (matrix.archive_sha256, manifest.archive_sha256, "archive"),
        (matrix.inventory_hash, manifest.inventory_hash, "inventory"),
        (matrix.dataset_doi, manifest.dataset_doi, "DOI"),
        (matrix.dataset_license, manifest.dataset_license, "license"),
    )
    for observed, expected, field in lineage_values:
        if observed != expected:
            raise AutonomousRecoveryError(f"{label} cycle {field} lineage mismatch")


def _build_lineage(
    paths: _InputPaths,
    manifest: MDBenchArchiveManifest,
    parent_matrix: MDBenchExperimentMatrix,
    parent_report: MDBenchGateAReport,
    recovery_preregistration: MDBenchGateARecoveryPreregistration,
    recovery_matrix: MDBenchExperimentMatrix,
    recovery_report: MDBenchGateAReport,
) -> AutonomousRecoveryLineage:
    return AutonomousRecoveryLineage(
        archive_manifest_path=paths.archive_manifest.as_posix(),
        benchmark_revision=manifest.benchmark_revision,
        dataset_doi=manifest.dataset_doi,
        dataset_license=manifest.dataset_license,
        archive_sha256=manifest.archive_sha256,
        inventory_hash=manifest.inventory_hash,
        parent_cycle=_cycle_binding("parent", parent_matrix, parent_report),
        recovery_cycle=_cycle_binding(
            "recovery",
            recovery_matrix,
            recovery_report,
            preregistration_path=paths.recovery_preregistration,
            preregistration_hash=recovery_preregistration.recovery_hash,
        ),
    )


def _cycle_binding(
    cycle_id: Literal["parent", "recovery"],
    matrix: MDBenchExperimentMatrix,
    report: MDBenchGateAReport,
    *,
    preregistration_path: Path | None = None,
    preregistration_hash: str | None = None,
) -> AutonomousCycleBinding:
    return AutonomousCycleBinding(
        cycle_id=cycle_id,
        matrix_path=Path(matrix.output_path).resolve().as_posix(),
        matrix_hash=matrix.matrix_hash,
        preregistration_path=(
            preregistration_path.resolve().as_posix() if preregistration_path else None
        ),
        preregistration_hash=preregistration_hash,
        report_path=Path(report.output_path).resolve().as_posix(),
        report_hash=report.report_hash or "",
        decision=report.decision,
        gate_b_allowed=report.gate_b_allowed,
        candidate_method_id=report.candidate_method_id,
        selected_baseline_method_id=report.selected_baseline_method_id,
    )


def _available_untouched_systems(
    manifest: MDBenchArchiveManifest,
    excluded: set[tuple[DataType, str]],
) -> dict[DataType, tuple[str, ...]]:
    artifact_keys = {
        (artifact.data_type, artifact.system_name, artifact.condition)
        for artifact in manifest.artifacts
    }
    available: dict[DataType, tuple[str, ...]] = {"ode": (), "pde": ()}
    inventories: tuple[tuple[DataType, tuple[str, ...]], ...] = (
        ("ode", manifest.ode_systems),
        ("pde", manifest.pde_systems),
    )
    for data_type, inventory in inventories:
        names = tuple(
            name
            for name in inventory
            if (data_type, name) not in excluded
            and all((data_type, name, condition) in artifact_keys for condition in _CONDITIONS)
        )
        available[data_type] = names
    if (len(available["ode"]), len(available["pde"])) != (43, 8):
        raise AutonomousRecoveryError(
            "expected 43 untouched ODE and 8 untouched PDE systems with clean/snr_20 artifacts"
        )
    return available


def _split_panels(
    manifest: MDBenchArchiveManifest,
    available: dict[DataType, tuple[str, ...]],
) -> tuple[tuple[AutonomousPanelSystem, ...], tuple[AutonomousPanelSystem, ...]]:
    development: list[AutonomousPanelSystem] = []
    confirmation: list[AutonomousPanelSystem] = []
    panel_counts: tuple[tuple[DataType, int], ...] = (("ode", 10), ("pde", 4))
    for data_type, development_count in panel_counts:
        ranked = sorted(
            available[data_type],
            key=lambda name: _selection_digest(manifest.inventory_hash, data_type, name),
        )
        selected = ranked[: development_count * 2]
        for index, name in enumerate(selected, start=1):
            panel_system = _panel_system(
                manifest,
                data_type,
                name,
                selection_rank=index,
            )
            if index % 2:
                development.append(panel_system)
            else:
                confirmation.append(panel_system)
    return tuple(development), tuple(confirmation)


def _selection_digest(inventory_hash: str, data_type: str, system_name: str) -> str:
    return canonical_model_hash(
        {
            "protocol_id": _PROTOCOL_ID,
            "selection_policy": "sha256-rank-then-alternate-v1",
            "inventory_hash": inventory_hash,
            "data_type": data_type,
            "system_name": system_name,
        }
    )


def _panel_system(
    manifest: MDBenchArchiveManifest,
    data_type: DataType,
    system_name: str,
    *,
    selection_rank: int,
) -> AutonomousPanelSystem:
    artifacts = {
        artifact.condition: artifact
        for artifact in manifest.artifacts
        if artifact.data_type == data_type
        and artifact.system_name == system_name
        and artifact.condition in _CONDITIONS
    }
    if set(artifacts) != set(_CONDITIONS):
        raise AutonomousRecoveryError(
            f"official artifact missing for autonomous panel: {data_type}/{system_name}"
        )
    return AutonomousPanelSystem(
        data_type=data_type,
        system_name=system_name,
        selection_rank=selection_rank,
        selection_digest=_selection_digest(
            manifest.inventory_hash,
            data_type,
            system_name,
        ),
        artifact_paths={condition: artifacts[condition].relative_path for condition in _CONDITIONS},
        artifact_sha256={condition: artifacts[condition].sha256 for condition in _CONDITIONS},
    )


def _validate_panel_shape(
    systems: tuple[AutonomousPanelSystem, ...],
    seeds: tuple[int, ...],
) -> None:
    if len(seeds) != 3 or len(set(seeds)) != 3:
        raise ValueError("formal panels require three distinct seeds")
    counts = (
        sum(system.data_type == "ode" for system in systems),
        sum(system.data_type == "pde" for system in systems),
    )
    if counts != (10, 4):
        raise ValueError("formal panels require exactly 10 ODE and 4 PDE systems")
    keys = {(system.data_type, system.system_name) for system in systems}
    if len(keys) != len(systems):
        raise ValueError("formal panel systems must be unique")


def _build_confirmation_panel(
    systems: tuple[AutonomousPanelSystem, ...],
    output_path: Path,
) -> AutonomousConfirmationPanel:
    unstamped = AutonomousConfirmationPanel(
        seeds=_CONFIRMATION_SEEDS,
        systems=systems,
        panel_hash="0" * 64,
        output_path=output_path.as_posix(),
    )
    return unstamped.model_copy(
        update={"panel_hash": canonical_model_hash(_confirmation_payload(unstamped))}
    )


def _confirmation_payload(panel: AutonomousConfirmationPanel) -> dict[str, object]:
    return panel.model_dump(
        mode="json",
        exclude={"schema_version", "panel_hash", "output_path"},
    )


def _fetch_source_snapshots(
    fetcher: SourceFetcher,
    *,
    timeout_seconds: int,
) -> tuple[tuple[AutonomousRecoverySourceSnapshot, ...], tuple[bytes, ...]]:
    snapshots: list[AutonomousRecoverySourceSnapshot] = []
    bodies: list[bytes] = []
    retrieved_at = datetime.now(timezone.utc)
    for spec in AUTONOMOUS_RECOVERY_SOURCE_SPECS:
        try:
            body, final_url, status_code = fetcher(spec, timeout_seconds)
        except Exception as exc:
            raise AutonomousRecoveryError(
                f"primary-source retrieval failed for {spec.source_id}: {exc}"
            ) from exc
        if len(body) > _MAX_SOURCE_BYTES:
            raise AutonomousRecoveryError(f"primary source is too large: {spec.source_id}")
        marker_verified = spec.required_marker.casefold() in body.decode(
            "utf-8", errors="replace"
        ).casefold()
        if status_code < 200 or status_code >= 300 or not marker_verified:
            raise AutonomousRecoveryError(
                f"primary-source marker/status failed for {spec.source_id}: {status_code}"
            )
        relative_path = f"sources/{spec.source_id}.html"
        snapshots.append(
            AutonomousRecoverySourceSnapshot(
                source_id=spec.source_id,
                domain=spec.domain,
                title=spec.title,
                year=spec.year,
                source_url=spec.url,
                final_url=final_url,
                status_code=status_code,
                required_marker=spec.required_marker,
                marker_verified=True,
                content_sha256=hashlib.sha256(body).hexdigest(),
                snapshot_relative_path=relative_path,
                retrieved_at=retrieved_at,
                design_implication=spec.design_implication,
            )
        )
        bodies.append(body)
    return tuple(snapshots), tuple(bodies)


def _default_source_fetcher(
    spec: AutonomousRecoverySourceSpec,
    timeout_seconds: int,
) -> tuple[bytes, str, int]:
    last_error: Exception | None = None
    for attempt in range(1, 3):
        request = Request(
            spec.url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": "AutoResearch/1.0 (formal primary-source audit)",
            },
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
                status = int(getattr(response, "status", 200))
                body = response.read(_MAX_SOURCE_BYTES + 1)
                return body, response.geturl(), status
        except (HTTPError, URLError, OSError, TimeoutError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(1)
    raise AutonomousRecoveryError(f"source retrieval failed after two attempts: {last_error}")


def _failure_summary(
    cycle_id: Literal["parent", "recovery"],
    report: MDBenchGateAReport,
) -> AutonomousFailureSummary:
    comparison = report.primary_comparison
    return AutonomousFailureSummary(
        cycle_id=cycle_id,
        candidate_method_id=report.candidate_method_id,
        baseline_method_id=report.selected_baseline_method_id,
        succeeded_count=report.succeeded_count,
        total_attempt_count=report.total_attempt_count,
        failure_aware_system_median_relative_improvement=(
            comparison.failure_aware_system_median_relative_improvement
        ),
        bootstrap_ci95_lower=comparison.bootstrap_ci95_lower,
        bootstrap_ci95_upper=comparison.bootstrap_ci95_upper,
        required_relative_improvement=comparison.required_relative_improvement,
        failed_mandatory_check_ids=tuple(
            check.check_id for check in report.checks if check.mandatory and not check.passed
        ),
        negative_reasons=report.negative_reasons,
    )


def _plan_payload(plan: AutonomousMDBenchRecoveryPlan) -> dict[str, object]:
    return plan.model_dump(
        mode="json",
        exclude={"plan_hash", "output_path", "markdown_path"},
    )


def _reject_research_activity(output_root: Path) -> None:
    if not output_root.exists():
        return
    for path in output_root.rglob("*"):
        if path.name.casefold() in _FORBIDDEN_OUTPUT_NAMES:
            raise AutonomousRecoveryError(
                f"result or candidate marker exists in result-free planning output: {path.name}"
            )


def _write_bytes_atomically(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(body)
    temporary.replace(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _render_markdown(plan: AutonomousMDBenchRecoveryPlan) -> str:
    development_names = "\n".join(
        f"- `{system.data_type}/{system.system_name}`"
        for system in plan.development_panel.systems
    )
    sources = "\n".join(
        f"- [{source.title}]({source.source_url}) — `{source.domain}`; "
        f"snapshot `{source.content_sha256}`"
        for source in plan.evidence_sources
    )
    failures = "\n".join(
        f"- `{item.cycle_id}`: `{item.candidate_method_id}` vs "
        f"`{item.baseline_method_id}`, failure-aware median "
        f"`{item.failure_aware_system_median_relative_improvement:.6f}`, "
        f"95% CI `[{item.bootstrap_ci95_lower:.6f}, "
        f"{item.bootstrap_ci95_upper:.6f}]`."
        for item in plan.failure_summaries
    )
    return f"""# Autonomous MDBench formal recovery plan

Plan hash: `{plan.plan_hash}`

## What this artifact does

This is a result-blind implementation handoff, not a paper and not a candidate method.  It
binds two completed negative formal cycles and requires the next runtime to generate,
implement, execute, select, mutate, ablate, replicate, and write from one append-only ledger.

At freeze time: model interactions = `0`; generated candidates = `0`; results = `0`;
manuscripts = `0`; post-start human scientific decisions = `0`.

## Prior formal evidence

{failures}

## Autonomous-origin boundary

- Human-authored candidates: **forbidden**.
- Fixed candidate catalogue: **forbidden**.
- Human algorithm selection or repair after start: **forbidden**.
- LLM self-score as a scientific gate: **forbidden**.
- Exact model-generated code and objective execution reward: **required**.
- At least 8 candidates, 3 mechanism families, and 2 generations: **required**.
- Manuscript generation inside the same run ledger: **required**.

## Development panel visible to the research runtime

{development_names}

## Sealed confirmation

The confirmation identities are not reproduced here.  The plan binds 10 ODE and 4 PDE
systems through `{plan.confirmation_commitment.panel_hash}`.  They remain unavailable to
generation, selection, repair, and comparative memory until a Task 265.2 search-freeze
receipt exists.  Confirmation cannot trigger reselection or a second attempt.

## Primary-source architecture evidence

{sources}

## Next gate

Only Task `{plan.next_required_task}` is authorized: implement the provider-neutral
literature-to-code branch generator, sandbox Harness, objective evaluator, comparative
memory, and search-freeze receipt.  Development execution, confirmation access,
publication, public release, and submission are still unauthorized.
"""
