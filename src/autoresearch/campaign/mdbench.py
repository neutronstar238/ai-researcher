"""Result-blind local MDBench adapter for autonomous campaign rounds.

The language model may explain a failure and phrase a falsifiable proposal, but
the benchmark matrix, development selection, bootstrap interval, and final gate
are deterministic.  Current-round unseen arrays are never opened outside the
hash-bound container executor and are not available to proposal prompts.
"""

from __future__ import annotations

import json
import math
import os
import random
import re
import statistics
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import Field, ValidationError

from autoresearch.campaign.models import (
    ContributionGateResult,
    DevelopmentResult,
    FailureDiagnosis,
    FailureKind,
    FreezeInputs,
    FrozenRoundProtocol,
    HypothesisProposal,
    HypothesisScreening,
    Preregistration,
    PreregistrationInputs,
    RoundDevelopmentContext,
    RoundObservation,
    RoundOutcome,
    StrictCampaignModel,
    UnseenEvaluation,
)
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import (
    MDBenchArchiveManifest,
    MDBenchAttemptResult,
    MDBenchAttemptState,
    MDBenchExecutionReport,
    MDBenchExperimentMatrix,
    MDBenchMatrixAttemptSpec,
    MDBenchMethodSpec,
    MDBenchSystemCase,
    MDBenchTemporalSplit,
)
from autoresearch.competition.official_execution import (
    execute_mdbench_matrix,
    load_mdbench_attempt_result,
)
from autoresearch.competition.preregistration import validate_mdbench_preregistration
from autoresearch.config import ConfigParser, SystemConfig
from autoresearch.llm.client import (
    LLMClientError,
    LLMJsonCompletionResult,
    run_llm_json_completion,
)
from autoresearch.schemas import data_hash, file_hash

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_RUNNER_PATH = _REPOSITORY_ROOT / "deploy" / "experiments" / "mdbench" / "runner.py"
_OFFICIAL_EXECUTOR_PATH = (
    _REPOSITORY_ROOT / "src" / "autoresearch" / "competition" / "official_execution.py"
)
_COMPETITION_MODELS_PATH = (
    _REPOSITORY_ROOT / "src" / "autoresearch" / "competition" / "models.py"
)
_REF_PATTERN = re.compile(r"^mdbench:ode:(?P<system>.+):(?P<split>development|unseen)$")
_CONDITIONS = ("clean", "snr_20")
_DEVELOPMENT_THRESHOLD = 0.15
_BOOTSTRAP_RESAMPLES = 20_000
_ADJUDICATION_POLICY_VERSION = "mdbench-campaign-adjudicator-v1"

JsonCompletion = Callable[..., LLMJsonCompletionResult]
MatrixExecutor = Callable[..., MDBenchExecutionReport]


class MDBenchHoldoutAudit(StrictCampaignModel):
    """Metadata-only proof that new result-blind systems remain available."""

    schema_version: str = "mdbench-holdout-audit-v1"
    archive_manifest_path: str
    inventory_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    historical_metadata_paths: tuple[str, ...]
    historical_metadata_sha256: dict[str, str]
    previously_used_systems: tuple[str, ...]
    eligible_ode_systems: tuple[str, ...]
    eligible_pde_systems: tuple[str, ...]
    required_rounds: int = Field(ge=1)
    unseen_systems_per_round: int = Field(ge=1)
    selected_panels: dict[str, tuple[str, ...]]
    route_decision: Literal["route_a", "route_b"]
    decision_reason: str
    created_at: datetime
    audit_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    output_path: str


class MDBenchAdapterConfig(StrictCampaignModel):
    """Persisted paths and local-only execution settings for the real adapter."""

    archive_manifest_path: str
    historical_metadata_paths: tuple[str, ...]
    root_adjudication_path: str
    root_adjudication_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    holdout_audit_path: str
    holdout_audit_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    llm_config_path: str
    local_api_key_env: str = "AUTORESEARCH_LOCAL_OLLAMA_API_KEY"
    image: str = "autoresearch-mdbench:task260"
    development_systems: tuple[str, ...] = (
        "harmonic-oscillator",
        "brusselator",
    )
    round_mechanisms: dict[str, str]
    bootstrap_resamples: int = Field(default=_BOOTSTRAP_RESAMPLES, ge=1_000)


class LLMPhaseEvidence(StrictCampaignModel):
    """Redacted, auditable local-model request and fallback record."""

    schema_version: str = "campaign-local-llm-evidence-v1"
    round_id: str
    phase: Literal["diagnose", "propose"]
    prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: str
    base_url: str
    model_name: str
    response_text: str
    parsed_json: dict[str, Any]
    usage: dict[str, Any]
    used_fallback: bool
    failure: str | None = None
    created_at: datetime
    output_path: str


class _DiagnosisOutput(StrictCampaignModel):
    failure_kind: FailureKind
    causal_hypothesis: str = Field(min_length=1)
    required_mechanism_change: str = Field(min_length=1)
    observations: tuple[str, ...] = Field(min_length=1)
    constraints: tuple[str, ...] = Field(min_length=1)


class _ProposalOutput(StrictCampaignModel):
    title: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    mechanism_family: str = Field(min_length=1)
    mechanism_change: str = Field(min_length=1)
    repair_rationale: str = Field(min_length=1)
    predicted_effect: str = Field(min_length=1)
    falsification_conditions: tuple[str, ...] = Field(min_length=1)


class MDBenchRoundAnalysis(StrictCampaignModel):
    """Deterministic development or unseen aggregation artifact."""

    schema_version: str = "mdbench-campaign-round-analysis-v1"
    phase: Literal["development", "unseen"]
    round_id: str
    matrix_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_method_id: str
    baseline_method_id: str
    ablation_method_ids: tuple[str, ...]
    total_expected_attempts: int = Field(ge=1)
    terminal_attempts: int = Field(ge=0)
    succeeded_attempts: int = Field(ge=0)
    median_relative_improvement: float
    bootstrap_ci95_lower: float | None = None
    bootstrap_ci95_upper: float | None = None
    seed_median_improvements: dict[str, float] = Field(default_factory=dict)
    system_effects: dict[str, float] = Field(default_factory=dict)
    method_median_nmse: dict[str, float] = Field(default_factory=dict)
    checks: dict[str, bool]
    failures: tuple[str, ...]
    output_path: str


def audit_mdbench_holdout(
    archive_manifest_path: Path | str,
    historical_metadata_paths: Sequence[Path | str],
    output_path: Path | str,
    *,
    required_rounds: int = 2,
    systems_per_round: int = 6,
) -> MDBenchHoldoutAudit:
    """Audit only metadata and reserve deterministic disjoint ODE holdout panels."""

    archive_path = Path(archive_manifest_path).resolve()
    resolved_output = Path(output_path).resolve()
    requested_historical = tuple(
        Path(path).resolve().as_posix() for path in historical_metadata_paths
    )
    if resolved_output.is_file():
        existing = load_mdbench_holdout_audit(resolved_output)
        if (
            Path(existing.archive_manifest_path).resolve() != archive_path
            or existing.historical_metadata_paths != requested_historical
            or existing.required_rounds != required_rounds
            or existing.unseen_systems_per_round != systems_per_round
        ):
            raise ValueError("existing MDBench holdout audit belongs to different inputs")
        return existing
    archive = MDBenchArchiveManifest.model_validate_json(
        archive_path.read_text(encoding="utf-8")
    )
    historical_paths = tuple(Path(path).resolve() for path in historical_metadata_paths)
    previously_used: set[str] = set()
    historical_hashes: dict[str, str] = {}
    for path in historical_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        previously_used.update(_collect_system_names(payload))
        historical_hashes[path.as_posix()] = file_hash(path)

    coverage = {
        (artifact.data_type, artifact.system_name)
        for artifact in archive.artifacts
        if artifact.condition in _CONDITIONS
    }
    complete = {
        key
        for key in coverage
        if all(
            any(
                artifact.data_type == key[0]
                and artifact.system_name == key[1]
                and artifact.condition == condition
                for artifact in archive.artifacts
            )
            for condition in _CONDITIONS
        )
    }
    eligible_ode = sorted(
        system
        for data_type, system in complete
        if data_type == "ode" and system not in previously_used
    )
    eligible_pde = sorted(
        system
        for data_type, system in complete
        if data_type == "pde" and system not in previously_used
    )
    ordered_ode = sorted(
        eligible_ode,
        key=lambda system: data_hash(
            {"inventory_hash": archive.inventory_hash, "system_name": system}
        ),
    )
    required = required_rounds * systems_per_round
    route: Literal["route_a", "route_b"] = (
        "route_a" if len(ordered_ode) >= required else "route_b"
    )
    panels: dict[str, tuple[str, ...]] = {}
    if route == "route_a":
        for index in range(required_rounds):
            start = index * systems_per_round
            panels[str(index + 1)] = tuple(ordered_ode[start : start + systems_per_round])
    reason = (
        f"{len(ordered_ode)} unused ODE systems provide {required_rounds} disjoint "
        f"{systems_per_round}-system unseen panels"
        if route == "route_a"
        else (
            f"only {len(ordered_ode)} unused ODE systems remain; {required} are required, "
            "so the campaign must pivot to Route B"
        )
    )
    unstamped = MDBenchHoldoutAudit(
        archive_manifest_path=archive_path.as_posix(),
        inventory_hash=archive.inventory_hash,
        historical_metadata_paths=tuple(path.as_posix() for path in historical_paths),
        historical_metadata_sha256=historical_hashes,
        previously_used_systems=tuple(sorted(previously_used)),
        eligible_ode_systems=tuple(eligible_ode),
        eligible_pde_systems=tuple(eligible_pde),
        required_rounds=required_rounds,
        unseen_systems_per_round=systems_per_round,
        selected_panels=panels,
        route_decision=route,
        decision_reason=reason,
        created_at=datetime.now(timezone.utc),
        output_path=resolved_output.as_posix(),
    )
    stamped = unstamped.model_copy(
        update={
            "audit_hash": canonical_model_hash(
                unstamped.model_dump(mode="json", exclude={"audit_hash", "output_path"})
            )
        }
    )
    write_json_model(resolved_output, stamped)
    return stamped


def load_mdbench_holdout_audit(path: Path | str) -> MDBenchHoldoutAudit:
    """Load and verify one metadata-only holdout audit."""

    resolved = Path(path).resolve()
    audit = MDBenchHoldoutAudit.model_validate_json(resolved.read_text(encoding="utf-8"))
    if Path(audit.output_path).resolve() != resolved:
        raise ValueError("MDBench holdout audit output path mismatch")
    expected = canonical_model_hash(
        audit.model_dump(mode="json", exclude={"audit_hash", "output_path"})
    )
    if audit.audit_hash != expected:
        raise ValueError("MDBench holdout audit hash mismatch")
    archive = MDBenchArchiveManifest.model_validate_json(
        Path(audit.archive_manifest_path).read_text(encoding="utf-8")
    )
    if archive.inventory_hash != audit.inventory_hash:
        raise ValueError("official archive inventory changed after holdout audit")
    for raw_path, digest in audit.historical_metadata_sha256.items():
        path_item = Path(raw_path)
        if not path_item.is_file() or file_hash(path_item) != digest:
            raise ValueError(f"historical metadata changed after holdout audit: {path_item}")
    return audit


def build_mdbench_campaign_matrix(
    *,
    archive_manifest_path: Path | str,
    output_path: Path | str,
    development_systems: Sequence[str],
    unseen_systems: Sequence[str],
    seeds: Sequence[int],
    mechanism_family: str,
) -> MDBenchExperimentMatrix:
    """Freeze one compact ODE-only development/unseen matrix before results."""

    archive_path = Path(archive_manifest_path).resolve()
    archive = MDBenchArchiveManifest.model_validate_json(
        archive_path.read_text(encoding="utf-8")
    )
    systems = _matrix_systems(
        archive,
        development_systems=development_systems,
        unseen_systems=unseen_systems,
    )
    methods = _method_specs(mechanism_family)
    split = MDBenchTemporalSplit()
    attempts = _attempt_specs(systems, methods, tuple(seeds), split)
    payload: dict[str, Any] = {
        "benchmark_revision": archive.benchmark_revision,
        "dataset_doi": archive.dataset_doi,
        "dataset_license": archive.dataset_license,
        "archive_sha256": archive.archive_sha256,
        "inventory_hash": archive.inventory_hash,
        "selection_policy": (
            "metadata-hash ordered unused ODE holdout panel; no numerical array or method "
            "result was opened before the matrix hash"
        ),
        "split_policy": split.model_dump(mode="json"),
        "conditions": _CONDITIONS,
        "seeds": tuple(seeds),
        "systems": [system.model_dump(mode="json") for system in systems],
        "methods": [method.model_dump(mode="json") for method in methods],
        "attempts": [attempt.model_dump(mode="json") for attempt in attempts],
        "metrics": (
            "derivative_nmse",
            "trajectory_extrapolation_nmse_ode",
            "model_complexity",
            "wall_time_seconds",
            "peak_rss_mb",
        ),
        "acceptance_criteria": (
            "development candidate-versus-Operon median relative improvement is at least 15 percent",
            "candidate and baseline clean/noisy development cells all succeed across three seeds",
            "unseen failure-aware system bootstrap 95 percent confidence lower bound is above zero",
            "candidate and strong baseline reproduce across three seeds",
            "three preregistered ablations terminate and the unchanged matrix rerun reuses every result",
            "no current unseen value enters proposal, development selection, or prompt context",
        ),
        "upstream_divergences": (
            "campaign matrix is an ODE-only Route A sprint, not the legacy 10 ODE/4 PDE Gate A matrix",
            "the prior revealed MDBench systems are excluded from both new unseen panels",
            "all numerical decisions use deterministic host code rather than the local language model",
        ),
        "created_before_results": True,
    }
    matrix_hash = canonical_model_hash(payload)
    resolved_output = Path(output_path).resolve()
    matrix = MDBenchExperimentMatrix(
        schema_version="mdbench-campaign-matrix-v1",
        benchmark_revision=archive.benchmark_revision,
        dataset_doi=archive.dataset_doi,
        dataset_license=archive.dataset_license,
        archive_sha256=archive.archive_sha256,
        inventory_hash=archive.inventory_hash,
        selection_policy=str(payload["selection_policy"]),
        split_policy=split,
        conditions=_CONDITIONS,
        seeds=tuple(seeds),
        systems=systems,
        methods=methods,
        attempts=attempts,
        metrics=tuple(str(item) for item in payload["metrics"]),
        acceptance_criteria=tuple(
            str(item) for item in payload["acceptance_criteria"]
        ),
        upstream_divergences=tuple(
            str(item) for item in payload["upstream_divergences"]
        ),
        created_before_results=True,
        matrix_hash=matrix_hash,
        output_path=resolved_output.as_posix(),
    )
    validate_mdbench_preregistration(matrix)
    if resolved_output.is_file():
        existing = MDBenchExperimentMatrix.model_validate_json(
            resolved_output.read_text(encoding="utf-8")
        )
        validate_mdbench_preregistration(existing)
        if existing.matrix_hash != matrix.matrix_hash:
            raise ValueError("refusing to replace a different frozen campaign matrix")
        return existing
    write_json_model(resolved_output, matrix)
    return matrix


class MDBenchCampaignAdapter:
    """Execute local Qwen-guided, deterministically adjudicated MDBench rounds."""

    adapter_id = "mdbench-autonomous-route-a-v1"

    def __init__(
        self,
        evidence_root: Path | str,
        config: MDBenchAdapterConfig | dict[str, Any],
        *,
        completion: JsonCompletion = run_llm_json_completion,
        executor: MatrixExecutor = execute_mdbench_matrix,
    ) -> None:
        self.evidence_root = Path(evidence_root).resolve()
        self.config = (
            config
            if isinstance(config, MDBenchAdapterConfig)
            else MDBenchAdapterConfig.model_validate(config)
        )
        self.completion = completion
        self.executor = executor
        self.audit = load_mdbench_holdout_audit(self.config.holdout_audit_path)
        if self.audit.audit_hash != self.config.holdout_audit_hash:
            raise ValueError("adapter holdout audit hash mismatch")
        if self.audit.route_decision != "route_a":
            raise ValueError("holdout audit requires Route B; Route A adapter is blocked")
        root = Path(self.config.root_adjudication_path)
        if not root.is_file() or file_hash(root) != self.config.root_adjudication_sha256:
            raise ValueError("root negative adjudication changed after campaign configuration")
        self._llm_identity = _validate_local_llm_config(self.config.llm_config_path)
        os.environ.setdefault(self.config.local_api_key_env, "ollama-local")

    def observe(self, context: RoundDevelopmentContext) -> RoundObservation:
        root_payload = json.loads(
            Path(self.config.root_adjudication_path).read_text(encoding="utf-8")
        )
        negative_reasons = tuple(str(item) for item in root_payload.get("negative_reasons", ()))
        if context.round_number > 1:
            negative_reasons = (
                "The previous autonomous campaign round did not clear its frozen gate.",
                *negative_reasons[:2],
            )
        return RoundObservation(
            round_id=context.round_id,
            parent_result_hash=context.parent_result_hash,
            evidence_refs=tuple(
                dict.fromkeys(
                    (
                        *context.historical_evidence_refs,
                        self.config.holdout_audit_path,
                        self.config.root_adjudication_path,
                    )
                )
            ),
            summary=(
                "The official parent and recovery cycles are immutable negative results. "
                "A metadata-only audit reserved a fresh disjoint ODE holdout panel; only "
                "development references are visible to diagnosis and proposal."
            ),
            observed_failures=negative_reasons
            or ("The parent noisy-system confidence interval did not clear zero.",),
        )

    def diagnose(
        self,
        context: RoundDevelopmentContext,
        observation: RoundObservation,
    ) -> FailureDiagnosis:
        fallback = _DiagnosisOutput(
            failure_kind=(
                FailureKind.ROOT_NEGATIVE_RESULT
                if context.round_number == 1
                else FailureKind.UNSEEN_PERFORMANCE
            ),
            causal_hypothesis=(
                "Pointwise or weak-form derivative estimates amplified SNR20 noise, while "
                "support-stability selection did not control coefficient error across systems."
            ),
            required_mechanism_change=(
                f"Replace the closed weak-form/support-stability family with "
                f"{context.candidate_mechanism_families[0]}."
            ),
            observations=observation.observed_failures,
            constraints=(
                "do not inspect current-round unseen arrays or metrics",
                "do not reopen weak-form or support-stability mechanisms",
                "keep numerical selection and adjudication deterministic",
            ),
        )
        messages = _diagnosis_messages(context, observation)
        parsed, evidence_path = self._local_json(
            context=context,
            phase="diagnose",
            messages=messages,
            model_type=_DiagnosisOutput,
            fallback=fallback,
        )
        if not isinstance(parsed, _DiagnosisOutput):
            raise TypeError("diagnosis completion returned the wrong structured output")
        return FailureDiagnosis(
            round_id=context.round_id,
            parent_result_hash=context.parent_result_hash,
            failure_kind=parsed.failure_kind,
            observations=parsed.observations,
            causal_hypothesis=parsed.causal_hypothesis,
            required_mechanism_change=parsed.required_mechanism_change,
            constraints=parsed.constraints,
            evidence_refs=tuple(
                dict.fromkeys((*observation.evidence_refs, evidence_path.as_posix()))
            ),
        )

    def propose(
        self,
        context: RoundDevelopmentContext,
        diagnosis: FailureDiagnosis,
    ) -> HypothesisProposal:
        mechanism = self._mechanism(context.round_number)
        fallback = _fallback_proposal(mechanism, diagnosis)
        messages = _proposal_messages(context, diagnosis, mechanism)
        parsed, evidence_path = self._local_json(
            context=context,
            phase="propose",
            messages=messages,
            model_type=_ProposalOutput,
            fallback=fallback,
        )
        if not isinstance(parsed, _ProposalOutput):
            raise TypeError("proposal completion returned the wrong structured output")
        if parsed.mechanism_family != mechanism:
            parsed = fallback
        return HypothesisProposal(
            round_id=context.round_id,
            parent_result_hash=context.parent_result_hash,
            title=parsed.title,
            statement=parsed.statement,
            mechanism_family=mechanism,
            mechanism_change=parsed.mechanism_change,
            repair_rationale=parsed.repair_rationale,
            predicted_effect=parsed.predicted_effect,
            primary_metric=context.primary_metric,
            evidence_refs=tuple(
                dict.fromkeys(
                    (
                        *context.development_data_refs,
                        *diagnosis.evidence_refs,
                        evidence_path.as_posix(),
                    )
                )
            ),
            falsification_conditions=parsed.falsification_conditions,
        )

    def screen(
        self,
        context: RoundDevelopmentContext,
        diagnosis: FailureDiagnosis,
        proposal: HypothesisProposal,
    ) -> HypothesisScreening:
        del diagnosis
        panel = self._panel(context.round_number)
        mechanism_allowed = (
            proposal.mechanism_family in context.candidate_mechanism_families
            and proposal.mechanism_family == self._mechanism(context.round_number)
        )
        enough_holdout = len(panel) >= self.audit.unseen_systems_per_round
        files_ready = all(
            Path(path).is_file()
            for path in (
                self.config.archive_manifest_path,
                self.config.root_adjudication_path,
                self.config.llm_config_path,
                _RUNNER_PATH,
            )
        )
        passed = mechanism_allowed and enough_holdout and files_ready
        reasons = (
            (
                "mechanism differs from the closed weak-form/support-stability family",
                "six-system result-blind holdout panel is reserved by metadata hash",
                "local Qwen and hash-bound Docker execution inputs are available",
            )
            if passed
            else (
                "mechanism, holdout capacity, or local execution input failed screening",
            )
        )
        return HypothesisScreening(
            round_id=context.round_id,
            hypothesis_id=proposal.hypothesis_id,
            passed=passed,
            reasons=reasons,
            development_score=1.0 if passed else 0.0,
            duplicate_risk=0.1,
            estimated_wall_time_seconds=min(
                10_800,
                max(1, int((context.deadline - datetime.now(timezone.utc)).total_seconds())),
            ),
        )

    def preregistration_inputs(
        self,
        context: RoundDevelopmentContext,
        proposal: HypothesisProposal,
        screening: HypothesisScreening,
    ) -> PreregistrationInputs:
        if not screening.passed:
            raise ValueError("cannot preregister a screened-out MDBench proposal")
        round_dir = self._round_dir(context.round_id)
        matrix = build_mdbench_campaign_matrix(
            archive_manifest_path=self.config.archive_manifest_path,
            output_path=round_dir / "campaign-matrix.json",
            development_systems=self.config.development_systems,
            unseen_systems=self._panel(context.round_number),
            seeds=_design_seeds(context),
            mechanism_family=proposal.mechanism_family,
        )
        expected_refs = tuple(
            f"mdbench:ode:{case.system_name}:unseen"
            for case in matrix.systems
            if case.evaluation_split == "unseen_test"
        )
        if expected_refs != tuple(
            f"mdbench:ode:{name}:unseen" for name in self._panel(context.round_number)
        ):
            raise ValueError("frozen matrix unseen panel differs from the holdout audit")
        implementation_hashes = self._current_code_hashes(Path(matrix.output_path))
        return PreregistrationInputs(
            parameter_space={
                "matrix_path": matrix.output_path,
                "matrix_hash": matrix.matrix_hash,
                "holdout_audit_path": self.config.holdout_audit_path,
                "holdout_audit_hash": self.config.holdout_audit_hash,
                "candidate_method_id": _primary_method_id(proposal.mechanism_family),
                "baseline_method_id": "operon_gp",
                "ablation_method_ids": list(_ablation_method_ids(proposal.mechanism_family)),
                "development_threshold": _DEVELOPMENT_THRESHOLD,
                "bootstrap_resamples": self.config.bootstrap_resamples,
                "selection": "development-only paired derivative NMSE",
            },
            stop_rules=(
                "do not execute current-round unseen attempts unless the development gate passes",
                "after unseen reveal do not change systems, methods, parameters, seeds, or adjudicator",
                "a failed gate creates a new mechanism round; it never triggers same-round tuning",
                "stop Route A after the reserved designs or 72-hour budget and retain negative results",
            ),
            implementation_family_hashes=implementation_hashes,
            adjudicator_hash=_adjudicator_hash(
                matrix.matrix_hash,
                self.config.bootstrap_resamples,
            ),
        )

    def develop(
        self,
        context: RoundDevelopmentContext,
        proposal: HypothesisProposal,
        preregistration: Preregistration,
    ) -> DevelopmentResult:
        started = datetime.now(timezone.utc)
        matrix = self._load_matrix(preregistration)
        attempt_ids = tuple(
            attempt.attempt_id
            for attempt in matrix.attempts
            if attempt.evaluation_split == "development"
        )
        report = self.executor(
            matrix.output_path,
            self.config.archive_manifest_path,
            self._round_dir(context.round_id) / "execution",
            image=self.config.image,
            attempt_ids=attempt_ids,
        )
        analysis, evidence_paths = _analyze_development(
            matrix,
            report,
            round_id=context.round_id,
            candidate_method_id=_primary_method_id(proposal.mechanism_family),
            baseline_method_id="operon_gp",
            output_path=self._round_dir(context.round_id) / "development-analysis.json",
        )
        selected = (
            {
                "matrix_hash": matrix.matrix_hash,
                "candidate_method_id": analysis.candidate_method_id,
                "candidate_method": next(
                    method.model_dump(mode="json")
                    for method in matrix.methods
                    if method.method_id == analysis.candidate_method_id
                ),
                "development_analysis_path": analysis.output_path,
            }
            if analysis.checks["development_gate_passed"]
            else {}
        )
        return DevelopmentResult(
            round_id=context.round_id,
            hypothesis_id=proposal.hypothesis_id,
            preregistration_hash=_required(preregistration.preregistration_hash),
            passed=analysis.checks["development_gate_passed"],
            selected_configuration=selected,
            metrics={
                "median_relative_improvement": analysis.median_relative_improvement,
                "terminal_attempts": float(analysis.terminal_attempts),
                "succeeded_attempts": float(analysis.succeeded_attempts),
                "three_seed_consistent": float(
                    analysis.checks["three_seed_consistent"]
                ),
                "all_clean_noisy_cells_valid": float(
                    analysis.checks["all_clean_noisy_cells_valid"]
                ),
            },
            evidence_paths=evidence_paths,
            failure_reasons=analysis.failures,
            started_at=started,
            completed_at=datetime.now(timezone.utc),
        )

    def freeze_inputs(
        self,
        context: RoundDevelopmentContext,
        proposal: HypothesisProposal,
        preregistration: Preregistration,
        development: DevelopmentResult,
    ) -> FreezeInputs:
        del context, proposal
        matrix = self._load_matrix(preregistration)
        hashes = self._current_code_hashes(Path(matrix.output_path))
        if hashes != preregistration.implementation_family_hashes:
            raise ValueError("implementation bytes changed after preregistration")
        return FreezeInputs(
            selected_config_hash=data_hash(development.selected_configuration),
            code_hashes=hashes,
            adjudicator_hash=preregistration.adjudicator_hash,
        )

    def evaluate_unseen(
        self,
        proposal: HypothesisProposal,
        preregistration: Preregistration,
        frozen_protocol: FrozenRoundProtocol,
    ) -> UnseenEvaluation:
        started = datetime.now(timezone.utc)
        matrix = self._load_matrix(preregistration)
        current_hashes = self._current_code_hashes(Path(matrix.output_path))
        if current_hashes != frozen_protocol.code_hashes:
            raise ValueError("code or frozen matrix changed before unseen execution")
        if frozen_protocol.adjudicator_hash != _adjudicator_hash(
            matrix.matrix_hash,
            self.config.bootstrap_resamples,
        ):
            raise ValueError("adjudicator bytes or policy changed before unseen execution")
        attempt_ids = tuple(
            attempt.attempt_id
            for attempt in matrix.attempts
            if attempt.evaluation_split == "unseen_test"
        )
        execution_dir = self._round_dir(frozen_protocol.round_id) / "execution"
        self.executor(
            matrix.output_path,
            self.config.archive_manifest_path,
            execution_dir,
            image=self.config.image,
            attempt_ids=attempt_ids,
        )
        reproduced = self.executor(
            matrix.output_path,
            self.config.archive_manifest_path,
            execution_dir,
            image=self.config.image,
            attempt_ids=attempt_ids,
        )
        analysis, evidence_paths = _analyze_unseen(
            matrix,
            reproduced,
            round_id=frozen_protocol.round_id,
            candidate_method_id=_primary_method_id(proposal.mechanism_family),
            baseline_method_id="operon_gp",
            bootstrap_resamples=self.config.bootstrap_resamples,
            output_path=self._round_dir(frozen_protocol.round_id)
            / "unseen-analysis.json",
        )
        reproduce_path = _write_reproduction_entrypoint(
            self._round_dir(frozen_protocol.round_id),
            matrix=matrix,
            archive_manifest_path=Path(self.config.archive_manifest_path),
            image=self.config.image,
        )
        all_checks = all(analysis.checks.values())
        paths = tuple(dict.fromkeys((*evidence_paths, reproduce_path.as_posix())))
        return UnseenEvaluation(
            round_id=frozen_protocol.round_id,
            hypothesis_id=proposal.hypothesis_id,
            frozen_hash=_required(frozen_protocol.frozen_hash),
            outcome=(
                RoundOutcome.POSITIVE_RESULT if all_checks else RoundOutcome.NEGATIVE_RESULT
            ),
            metrics={
                "median_relative_improvement": analysis.median_relative_improvement,
                "bootstrap_ci95_lower": float(analysis.bootstrap_ci95_lower or 0.0),
                "bootstrap_ci95_upper": float(analysis.bootstrap_ci95_upper or 0.0),
                "candidate_success_rate": _check_float(
                    analysis, "candidate_three_seed_reproducible"
                ),
                "strong_baseline_complete": _check_float(
                    analysis, "strong_baseline_complete"
                ),
                "three_ablations_complete": _check_float(
                    analysis, "three_ablations_complete"
                ),
                "idempotent_reproduction": _check_float(
                    analysis, "idempotent_reproduction"
                ),
                "unseen_evidence_complete": _check_float(
                    analysis, "unseen_evidence_complete"
                ),
            },
            evidence_paths=paths,
            mandatory_evidence_complete=analysis.checks["unseen_evidence_complete"],
            human_intervention_count=reproduced.human_intervention_count,
            started_at=started,
            completed_at=datetime.now(timezone.utc),
        )

    def adjudicate(
        self,
        proposal: HypothesisProposal,
        preregistration: Preregistration,
        frozen_protocol: FrozenRoundProtocol,
        evaluation: UnseenEvaluation,
    ) -> ContributionGateResult:
        del proposal
        checks = {
            "bootstrap_ci_lower_above_zero": evaluation.metrics.get(
                "bootstrap_ci95_lower", 0.0
            )
            > 0.0,
            "candidate_three_seed_reproducible": evaluation.metrics.get(
                "candidate_success_rate", 0.0
            )
            == 1.0,
            "strong_baseline_complete": evaluation.metrics.get(
                "strong_baseline_complete", 0.0
            )
            == 1.0,
            "three_ablations_complete": evaluation.metrics.get(
                "three_ablations_complete", 0.0
            )
            == 1.0,
            "idempotent_reproduction": evaluation.metrics.get(
                "idempotent_reproduction", 0.0
            )
            == 1.0,
            "mandatory_evidence_complete": evaluation.mandatory_evidence_complete,
            "zero_human_intervention": evaluation.human_intervention_count == 0,
        }
        failures = tuple(
            f"{name} failed under the preregistered Route A contribution gate"
            for name, passed in checks.items()
            if not passed
        )
        return ContributionGateResult(
            round_id=frozen_protocol.round_id,
            track=preregistration.track,
            evaluated_result_hash=_required(evaluation.result_hash),
            passed=all(checks.values()),
            checks=checks,
            failures=failures,
            warnings=(
                "An internal positive gate would authorize paper build only; external "
                "submission still requires explicit human approval.",
            ),
            evidence_paths=evaluation.evidence_paths,
        )

    def _local_json(
        self,
        *,
        context: RoundDevelopmentContext,
        phase: Literal["diagnose", "propose"],
        messages: list[dict[str, str]],
        model_type: type[_DiagnosisOutput] | type[_ProposalOutput],
        fallback: _DiagnosisOutput | _ProposalOutput,
    ) -> tuple[_DiagnosisOutput | _ProposalOutput, Path]:
        serialized_messages = json.dumps(messages, sort_keys=True, ensure_ascii=False)
        forbidden = tuple(
            f"mdbench:ode:{name}:unseen" for name in self._panel(context.round_number)
        )
        if any(reference in serialized_messages for reference in forbidden):
            raise ValueError("current-round unseen references leaked into a local Qwen prompt")
        used_fallback = False
        failure: str | None = None
        response_text = ""
        usage: dict[str, Any] = {}
        provider, base_url, model_name = self._llm_identity
        try:
            result = self.completion(
                messages=messages,
                config_path=self.config.llm_config_path,
                env_path=Path("__no_campaign_env_file__"),
                timeout_seconds=180,
                max_tokens=1_500,
                temperature=0.0,
            )
            parsed = model_type.model_validate(result.parsed_json)
            response_text = result.response_text
            usage = result.usage
            provider, base_url, model_name = (
                result.provider,
                result.base_url,
                result.model_name,
            )
        except (LLMClientError, OSError, ValidationError, ValueError, TypeError) as exc:
            parsed = fallback
            used_fallback = True
            failure = f"{type(exc).__name__}: {exc}"
            response_text = json.dumps(
                fallback.model_dump(mode="json"),
                sort_keys=True,
                ensure_ascii=False,
            )
        evidence_path = self._round_dir(context.round_id) / f"local-qwen-{phase}.json"
        record = LLMPhaseEvidence(
            round_id=context.round_id,
            phase=phase,
            prompt_hash=data_hash({"messages": messages}),
            provider=provider,
            base_url=base_url,
            model_name=model_name,
            response_text=response_text,
            parsed_json=parsed.model_dump(mode="json"),
            usage=usage,
            used_fallback=used_fallback,
            failure=failure,
            created_at=datetime.now(timezone.utc),
            output_path=evidence_path.as_posix(),
        )
        write_json_model(evidence_path, record)
        return parsed, evidence_path

    def _load_matrix(self, preregistration: Preregistration) -> MDBenchExperimentMatrix:
        path = Path(str(preregistration.parameter_space["matrix_path"])).resolve()
        matrix = MDBenchExperimentMatrix.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        validate_mdbench_preregistration(matrix)
        if matrix.matrix_hash != preregistration.parameter_space["matrix_hash"]:
            raise ValueError("campaign matrix hash differs from preregistration")
        return matrix

    def _current_code_hashes(self, matrix_path: Path) -> dict[str, str]:
        return {
            "campaign_adapter": file_hash(Path(__file__)),
            "competition_models": file_hash(_COMPETITION_MODELS_PATH),
            "llm_config": file_hash(Path(self.config.llm_config_path)),
            "matrix": file_hash(matrix_path),
            "official_executor": file_hash(_OFFICIAL_EXECUTOR_PATH),
            "runner": file_hash(_RUNNER_PATH),
        }

    def _mechanism(self, round_number: int) -> str:
        try:
            return self.config.round_mechanisms[str(round_number)]
        except KeyError as exc:
            raise ValueError(f"no mechanism configured for round {round_number}") from exc

    def _panel(self, round_number: int) -> tuple[str, ...]:
        try:
            return self.audit.selected_panels[str(round_number)]
        except KeyError as exc:
            raise ValueError(f"holdout audit has no panel for round {round_number}") from exc

    def _round_dir(self, round_id: str) -> Path:
        path = self.evidence_root / round_id
        path.mkdir(parents=True, exist_ok=True)
        return path


def _collect_system_names(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "system_name" and isinstance(item, str):
                found.add(item)
            else:
                found.update(_collect_system_names(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_collect_system_names(item))
    return found


def _matrix_systems(
    archive: MDBenchArchiveManifest,
    *,
    development_systems: Sequence[str],
    unseen_systems: Sequence[str],
) -> tuple[MDBenchSystemCase, ...]:
    if set(development_systems) & set(unseen_systems):
        raise ValueError("development and unseen MDBench systems overlap")
    artifacts = {
        (artifact.data_type, artifact.system_name, artifact.condition): artifact
        for artifact in archive.artifacts
    }
    cases: list[MDBenchSystemCase] = []
    for split, names in (
        ("development", development_systems),
        ("unseen_test", unseen_systems),
    ):
        evaluation_split: Literal["development", "unseen_test"] = (
            "development" if split == "development" else "unseen_test"
        )
        for system_name in names:
            selected = {
                condition: artifacts.get(("ode", system_name, condition))
                for condition in _CONDITIONS
            }
            if any(artifact is None for artifact in selected.values()):
                raise ValueError(f"official ODE clean/SNR20 artifacts missing for {system_name}")
            cases.append(
                MDBenchSystemCase(
                    data_type="ode",
                    system_name=system_name,
                    evaluation_split=evaluation_split,
                    selection_reason=(
                        "revealed development control"
                        if split == "development"
                        else "metadata-hash selected unused holdout"
                    ),
                    artifact_paths={
                        condition: artifact.relative_path
                        for condition, artifact in selected.items()
                        if artifact is not None
                    },
                    artifact_sha256={
                        condition: artifact.sha256
                        for condition, artifact in selected.items()
                        if artifact is not None
                    },
                )
            )
    return tuple(cases)


def _method_specs(mechanism: str) -> tuple[MDBenchMethodSpec, ...]:
    baseline = MDBenchMethodSpec(
        method_id="operon_gp",
        family="genetic_symbolic",
        implementation="pinned MDBench Operon with the prior official strong-baseline budget",
        applicable_data_types=("ode",),
        parameters={
            "generations": 100,
            "max_evaluations": 20_000,
            "population_size": 200,
            "pool_size": 200,
            "max_time_seconds": 75,
            "random_state": "attempt_seed",
        },
        max_seconds_per_attempt=120,
        max_cpu_cores=2,
        max_memory_mb=4096,
    )
    if mechanism == "noise_conditioned_ensemble_sindy":
        common: dict[str, Any] = {
            "campaign_candidate_kind": "noise_conditioned_ensemble",
            "mechanisms": [
                "noise_conditioned_savgol",
                "bootstrap_coefficient_ensemble",
                "median_coefficient_aggregation",
            ],
            "savgol_windows": [5, 9, 15, 21],
            "savgol_polyorder": 3,
            "optimizer_threshold": [1e-5, 1e-3, 1e-2, 1e-1],
            "poly_order": [1, 2, 3],
            "ensemble_repetitions": 9,
            "subsample_fraction": 0.8,
            "noise_conditioning": True,
            "smoothing": True,
            "ensemble": True,
        }
        variants: tuple[tuple[str, dict[str, Any], str], ...] = (
            ("noise_conditioned_ensemble_sindy", {}, "complete composite mechanism"),
            (
                "ablation_no_noise_conditioning",
                {"noise_conditioning": False},
                "ablation without train-only noise-conditioned window restriction",
            ),
            (
                "ablation_no_ensemble",
                {"ensemble": False, "ensemble_repetitions": 1},
                "ablation with one sparse fit instead of coefficient bagging",
            ),
            (
                "ablation_no_smoothing",
                {"smoothing": False, "savgol_windows": [5]},
                "ablation using finite differences without signal smoothing",
            ),
        )
    elif mechanism == "spline_group_sparse_sindy":
        common = {
            "campaign_candidate_kind": "spline_group_sparse",
            "mechanisms": [
                "cubic_smoothing_spline_derivative",
                "cross_output_group_sparse_projection",
            ],
            "spline_smoothing_scales": [0.0, 0.25, 1.0, 4.0],
            "optimizer_threshold": [1e-5, 1e-3, 1e-2, 1e-1],
            "poly_order": [1, 2, 3],
            "group_sparse": True,
            "spline_derivative": True,
            "shared_support": True,
        }
        variants = (
            ("spline_group_sparse_sindy", {}, "complete composite mechanism"),
            (
                "ablation_no_group_sparse",
                {"group_sparse": False},
                "ablation without group-norm feature removal",
            ),
            (
                "ablation_no_spline_derivative",
                {"spline_derivative": False},
                "ablation using finite-difference derivatives",
            ),
            (
                "ablation_no_shared_support",
                {"shared_support": False},
                "ablation selecting support independently per output",
            ),
        )
    else:
        raise ValueError(f"unsupported autonomous mechanism family: {mechanism}")
    candidates = tuple(
        MDBenchMethodSpec(
            method_id=method_id,
            family="agent_candidate",
            implementation=description,
            applicable_data_types=("ode",),
            parameters={**common, **overrides},
            max_seconds_per_attempt=120,
            max_cpu_cores=2,
            max_memory_mb=4096,
        )
        for method_id, overrides, description in variants
    )
    return (baseline, *candidates)


def _attempt_specs(
    systems: tuple[MDBenchSystemCase, ...],
    methods: tuple[MDBenchMethodSpec, ...],
    seeds: tuple[int, ...],
    split: MDBenchTemporalSplit,
) -> tuple[MDBenchMatrixAttemptSpec, ...]:
    attempts: list[MDBenchMatrixAttemptSpec] = []
    for case in systems:
        for condition in _CONDITIONS:
            for seed in seeds:
                for method in methods:
                    config_hash = canonical_model_hash(
                        {
                            "artifact_sha256": case.artifact_sha256[condition],
                            "condition": condition,
                            "data_type": case.data_type,
                            "method": method.model_dump(mode="json"),
                            "seed": seed,
                            "split_policy": split.model_dump(mode="json"),
                            "system_name": case.system_name,
                        }
                    )
                    attempts.append(
                        MDBenchMatrixAttemptSpec(
                            attempt_id=(
                                f"ode--{case.system_name}--{condition}--seed-{seed}--"
                                f"{method.method_id}"
                            ),
                            data_type="ode",
                            system_name=case.system_name,
                            evaluation_split=case.evaluation_split,
                            condition=condition,
                            seed=seed,
                            method_id=method.method_id,
                            artifact_path=case.artifact_paths[condition],
                            artifact_sha256=case.artifact_sha256[condition],
                            config_hash=config_hash,
                        )
                    )
    return tuple(attempts)


def _analyze_development(
    matrix: MDBenchExperimentMatrix,
    report: MDBenchExecutionReport,
    *,
    round_id: str,
    candidate_method_id: str,
    baseline_method_id: str,
    output_path: Path,
) -> tuple[MDBenchRoundAnalysis, tuple[str, ...]]:
    attempts = tuple(
        attempt for attempt in matrix.attempts if attempt.evaluation_split == "development"
    )
    selected = tuple(
        attempt
        for attempt in attempts
        if attempt.method_id in {candidate_method_id, baseline_method_id}
    )
    results, evidence = _load_selected_results(report, selected)
    effects: list[float] = []
    seed_effects: dict[int, list[float]] = {seed: [] for seed in matrix.seeds}
    all_valid = True
    for system in {attempt.system_name for attempt in selected}:
        for condition in matrix.conditions:
            for seed in matrix.seeds:
                candidate = results.get((system, condition, seed, candidate_method_id))
                baseline = results.get((system, condition, seed, baseline_method_id))
                candidate_nmse = _successful_nmse(candidate)
                baseline_nmse = _successful_nmse(baseline)
                if candidate_nmse is None or baseline_nmse is None:
                    all_valid = False
                    continue
                effect = (baseline_nmse - candidate_nmse) / max(abs(baseline_nmse), 1e-12)
                effects.append(effect)
                seed_effects[seed].append(effect)
    median_effect = statistics.median(effects) if effects else -1.0
    seed_medians = {
        str(seed): (statistics.median(values) if values else -1.0)
        for seed, values in seed_effects.items()
    }
    seed_consistent = all(value > 0.0 for value in seed_medians.values())
    checks = {
        "all_clean_noisy_cells_valid": all_valid and len(results) == len(selected),
        "median_improvement_at_least_15_percent": median_effect
        >= _DEVELOPMENT_THRESHOLD,
        "three_seed_consistent": seed_consistent,
    }
    checks["development_gate_passed"] = all(checks.values())
    failures = tuple(
        f"{name} failed" for name, passed in checks.items() if not passed and name != "development_gate_passed"
    )
    analysis = MDBenchRoundAnalysis(
        phase="development",
        round_id=round_id,
        matrix_hash=matrix.matrix_hash,
        candidate_method_id=candidate_method_id,
        baseline_method_id=baseline_method_id,
        ablation_method_ids=_ablation_ids_from_matrix(matrix, candidate_method_id),
        total_expected_attempts=len(selected),
        terminal_attempts=len(results),
        succeeded_attempts=sum(
            result.status is MDBenchAttemptState.SUCCEEDED for result in results.values()
        ),
        median_relative_improvement=median_effect,
        seed_median_improvements=seed_medians,
        checks=checks,
        failures=failures,
        output_path=output_path.resolve().as_posix(),
    )
    write_json_model(output_path, analysis)
    return analysis, tuple(dict.fromkeys((analysis.output_path, report.output_path, *evidence)))


def _analyze_unseen(
    matrix: MDBenchExperimentMatrix,
    report: MDBenchExecutionReport,
    *,
    round_id: str,
    candidate_method_id: str,
    baseline_method_id: str,
    bootstrap_resamples: int,
    output_path: Path,
) -> tuple[MDBenchRoundAnalysis, tuple[str, ...]]:
    attempts = tuple(
        attempt for attempt in matrix.attempts if attempt.evaluation_split == "unseen_test"
    )
    results, evidence = _load_selected_results(report, attempts)
    ablations = _ablation_ids_from_matrix(matrix, candidate_method_id)
    systems = tuple(
        case.system_name for case in matrix.systems if case.evaluation_split == "unseen_test"
    )
    system_effects: dict[str, float] = {}
    for system in systems:
        candidate_values = [
            _successful_nmse(results.get((system, "snr_20", seed, candidate_method_id)))
            for seed in matrix.seeds
        ]
        baseline_values = [
            _successful_nmse(results.get((system, "snr_20", seed, baseline_method_id)))
            for seed in matrix.seeds
        ]
        if any(value is None for value in candidate_values):
            effect = -1.0
        elif any(value is None for value in baseline_values):
            effect = 0.0
        else:
            candidate_median = statistics.median(
                value for value in candidate_values if value is not None
            )
            baseline_median = statistics.median(
                value for value in baseline_values if value is not None
            )
            effect = (baseline_median - candidate_median) / max(
                abs(baseline_median),
                1e-12,
            )
        system_effects[system] = float(effect)
    observed = statistics.median(system_effects.values()) if system_effects else -1.0
    lower, upper = _bootstrap_median_ci(
        tuple(system_effects.values()),
        resamples=bootstrap_resamples,
        seed=int(matrix.matrix_hash[:16], 16),
    )
    relevant_candidate_baseline = tuple(
        attempt
        for attempt in attempts
        if attempt.method_id in {candidate_method_id, baseline_method_id}
    )
    candidate_complete = _all_method_attempts_succeeded(
        relevant_candidate_baseline,
        results,
        candidate_method_id,
    )
    baseline_complete = _all_method_attempts_succeeded(
        relevant_candidate_baseline,
        results,
        baseline_method_id,
    )
    ablations_complete = len(ablations) >= 3 and all(
        _all_method_attempts_succeeded(attempts, results, method_id)
        for method_id in ablations
    )
    relevant_ids = {attempt.attempt_id for attempt in attempts}
    reused = {
        record.attempt_id: record.reused_this_invocation
        for record in report.records
        if record.attempt_id in relevant_ids
    }
    idempotent = len(reused) == len(attempts) and all(reused.values())
    evidence_complete = (
        report.complete
        and report.pending_count == 0
        and len(results) == len(attempts)
        and all(Path(path).is_file() for path in evidence)
    )
    checks = {
        "bootstrap_ci_lower_above_zero": lower > 0.0,
        "candidate_three_seed_reproducible": candidate_complete,
        "strong_baseline_complete": baseline_complete,
        "three_ablations_complete": ablations_complete,
        "idempotent_reproduction": idempotent,
        "unseen_evidence_complete": evidence_complete,
    }
    failures = tuple(f"{name} failed" for name, passed in checks.items() if not passed)
    method_medians: dict[str, float] = {}
    for method_id in (baseline_method_id, candidate_method_id, *ablations):
        values = [
            value
            for key, result in results.items()
            if key[1] == "snr_20"
            and key[3] == method_id
            and (value := _successful_nmse(result)) is not None
        ]
        method_medians[method_id] = statistics.median(values) if values else math.inf
    analysis = MDBenchRoundAnalysis(
        phase="unseen",
        round_id=round_id,
        matrix_hash=matrix.matrix_hash,
        candidate_method_id=candidate_method_id,
        baseline_method_id=baseline_method_id,
        ablation_method_ids=ablations,
        total_expected_attempts=len(attempts),
        terminal_attempts=len(results),
        succeeded_attempts=sum(
            result.status is MDBenchAttemptState.SUCCEEDED for result in results.values()
        ),
        median_relative_improvement=observed,
        bootstrap_ci95_lower=lower,
        bootstrap_ci95_upper=upper,
        system_effects=system_effects,
        method_median_nmse=method_medians,
        checks=checks,
        failures=failures,
        output_path=output_path.resolve().as_posix(),
    )
    write_json_model(output_path, analysis)
    return analysis, tuple(dict.fromkeys((analysis.output_path, report.output_path, *evidence)))


def _load_selected_results(
    report: MDBenchExecutionReport,
    attempts: Sequence[MDBenchMatrixAttemptSpec],
) -> tuple[
    dict[tuple[str, str, int, str], MDBenchAttemptResult],
    tuple[str, ...],
]:
    records = {record.attempt_id: record for record in report.records}
    results: dict[tuple[str, str, int, str], MDBenchAttemptResult] = {}
    evidence: list[str] = []
    for attempt in attempts:
        record = records.get(attempt.attempt_id)
        if record is None:
            continue
        result = load_mdbench_attempt_result(record.result_path)
        results[
            (
                attempt.system_name,
                attempt.condition,
                attempt.seed,
                attempt.method_id,
            )
        ] = result
        evidence.extend((result.output_path, result.stdout_path, result.stderr_path))
    return results, tuple(dict.fromkeys(evidence))


def _successful_nmse(result: MDBenchAttemptResult | None) -> float | None:
    if result is None or result.status is not MDBenchAttemptState.SUCCEEDED:
        return None
    value = result.metrics.derivative_nmse
    if value is None or not math.isfinite(value):
        return None
    return float(value)


def _all_method_attempts_succeeded(
    attempts: Sequence[MDBenchMatrixAttemptSpec],
    results: dict[tuple[str, str, int, str], MDBenchAttemptResult],
    method_id: str,
) -> bool:
    selected = tuple(attempt for attempt in attempts if attempt.method_id == method_id)
    return bool(selected) and all(
        _successful_nmse(
            results.get(
                (
                    attempt.system_name,
                    attempt.condition,
                    attempt.seed,
                    attempt.method_id,
                )
            )
        )
        is not None
        for attempt in selected
    )


def _bootstrap_median_ci(
    values: tuple[float, ...],
    *,
    resamples: int,
    seed: int,
) -> tuple[float, float]:
    if not values:
        return -1.0, -1.0
    generator = random.Random(seed)
    size = len(values)
    samples = sorted(
        statistics.median(generator.choice(values) for _ in range(size))
        for _ in range(resamples)
    )
    lower_index = max(0, int(0.025 * resamples) - 1)
    upper_index = min(resamples - 1, int(0.975 * resamples))
    return float(samples[lower_index]), float(samples[upper_index])


def _primary_method_id(mechanism: str) -> str:
    if mechanism in {
        "noise_conditioned_ensemble_sindy",
        "spline_group_sparse_sindy",
    }:
        return mechanism
    raise ValueError(f"unsupported mechanism: {mechanism}")


def _ablation_method_ids(mechanism: str) -> tuple[str, ...]:
    if mechanism == "noise_conditioned_ensemble_sindy":
        return (
            "ablation_no_noise_conditioning",
            "ablation_no_ensemble",
            "ablation_no_smoothing",
        )
    if mechanism == "spline_group_sparse_sindy":
        return (
            "ablation_no_group_sparse",
            "ablation_no_spline_derivative",
            "ablation_no_shared_support",
        )
    raise ValueError(f"unsupported mechanism: {mechanism}")


def _ablation_ids_from_matrix(
    matrix: MDBenchExperimentMatrix,
    candidate_method_id: str,
) -> tuple[str, ...]:
    return tuple(
        method.method_id
        for method in matrix.methods
        if method.family == "agent_candidate" and method.method_id != candidate_method_id
    )


def _adjudicator_hash(matrix_hash: str, bootstrap_resamples: int) -> str:
    return data_hash(
        {
            "policy_version": _ADJUDICATION_POLICY_VERSION,
            "matrix_hash": matrix_hash,
            "development_threshold": _DEVELOPMENT_THRESHOLD,
            "bootstrap_resamples": bootstrap_resamples,
            "bootstrap_unit": "unseen_system",
            "bootstrap_statistic": "median failure-aware relative improvement",
            "missing_candidate_policy": -1.0,
            "missing_baseline_policy": 0.0,
            "required_ci_lower": 0.0,
            "required_seed_count": 3,
            "required_ablation_count": 3,
        }
    )


def _validate_local_llm_config(config_path: Path | str) -> tuple[str, str, str]:
    config = ConfigParser().parse_file(config_path, model_type=SystemConfig)
    if not isinstance(config, SystemConfig):
        raise ValueError("local Qwen config did not parse as SystemConfig")
    llm = config.deployment.llm
    hostname = (urlparse(llm.base_url).hostname or "").lower()
    if hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("campaign LLM base URL must resolve to the local host")
    if llm.model_name != "qwen3.5:9b":
        raise ValueError("fast-ccfb campaign requires local Ollama qwen3.5:9b")
    return llm.provider, llm.base_url, llm.model_name


def _diagnosis_messages(
    context: RoundDevelopmentContext,
    observation: RoundObservation,
) -> list[dict[str, str]]:
    payload = {
        "round_id": context.round_id,
        "round_number": context.round_number,
        "parent_result_hash": context.parent_result_hash,
        "observed_failures": observation.observed_failures,
        "candidate_mechanism_families": context.candidate_mechanism_families,
        "development_data_refs": context.development_data_refs,
        "primary_metric": context.primary_metric,
    }
    return [
        {
            "role": "system",
            "content": (
                "You are a local scientific failure-diagnosis component. Return one JSON "
                "object only with failure_kind, causal_hypothesis, "
                "required_mechanism_change, observations, and constraints. Do not invent "
                "results, citations, scores, or unseen-system facts. The weak-form and "
                "support-stability families are closed."
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, sort_keys=True)},
    ]


def _proposal_messages(
    context: RoundDevelopmentContext,
    diagnosis: FailureDiagnosis,
    mechanism: str,
) -> list[dict[str, str]]:
    payload = {
        "round_id": context.round_id,
        "parent_result_hash": context.parent_result_hash,
        "diagnosis": diagnosis.model_dump(
            mode="json",
            exclude={"evidence_refs", "diagnosis_hash"},
        ),
        "required_mechanism_family": mechanism,
        "development_data_refs": context.development_data_refs,
        "primary_metric": context.primary_metric,
        "development_gate": "paired median relative improvement >= 0.15 across three seeds",
        "unseen_gate": "system-bootstrap 95% CI lower bound > 0",
    }
    return [
        {
            "role": "system",
            "content": (
                "You are a local hypothesis-proposal component. Return one JSON object only "
                "with title, statement, mechanism_family, mechanism_change, "
                "repair_rationale, predicted_effect, and falsification_conditions. Keep the "
                "required mechanism family exactly. Do not invent numerical results, papers, "
                "or unseen-system properties."
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, sort_keys=True)},
    ]


def _fallback_proposal(
    mechanism: str,
    diagnosis: FailureDiagnosis,
) -> _ProposalOutput:
    if mechanism == "noise_conditioned_ensemble_sindy":
        statement = (
            "A train-noise-conditioned Savitzky-Golay derivative estimator followed by "
            "bootstrap coefficient bagging and median sparse-regression aggregation will "
            "reduce SNR20 derivative NMSE versus the frozen Operon baseline."
        )
        change = (
            "Replace weak projection/support-frequency refitting with train-only noise "
            "conditioning and coefficient-space ensemble aggregation."
        )
    elif mechanism == "spline_group_sparse_sindy":
        statement = (
            "Cubic smoothing-spline analytic derivatives with cross-output group-sparse "
            "polynomial projection will reduce SNR20 derivative NMSE versus Operon."
        )
        change = (
            "Replace weak projection/support-frequency refitting with analytic spline "
            "derivatives and a shared group-norm sparsity objective."
        )
    else:
        raise ValueError(f"unsupported fallback mechanism: {mechanism}")
    return _ProposalOutput(
        title=mechanism.replace("_", " ").title(),
        statement=statement,
        mechanism_family=mechanism,
        mechanism_change=change,
        repair_rationale=diagnosis.causal_hypothesis,
        predicted_effect=(
            "At least 15% paired development improvement and a positive unseen "
            "system-bootstrap lower confidence bound."
        ),
        falsification_conditions=(
            "any candidate or strong-baseline clean/noisy development cell is invalid",
            "paired development median improvement is below 15 percent",
            "any unseen three-seed reproduction or ablation is incomplete",
            "unseen failure-aware bootstrap 95 percent confidence lower bound is not positive",
        ),
    )


def _design_seeds(context: RoundDevelopmentContext) -> tuple[int, ...]:
    return context.seeds


def _write_reproduction_entrypoint(
    round_dir: Path,
    *,
    matrix: MDBenchExperimentMatrix,
    archive_manifest_path: Path,
    image: str,
) -> Path:
    path = round_dir / "reproduce.ps1"
    content = "\n".join(
        (
            "$ErrorActionPreference = 'Stop'",
            (
                "poetry run airesearcher competition mdbench execute "
                f"--matrix '{Path(matrix.output_path).as_posix()}' "
                f"--archive-manifest '{archive_manifest_path.resolve().as_posix()}' "
                f"--output-dir '{(round_dir / 'execution').resolve().as_posix()}' "
                f"--image '{image}'"
            ),
            "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }",
        )
    )
    path.write_text(content + "\n", encoding="utf-8")
    return path


def _check_float(analysis: MDBenchRoundAnalysis, key: str) -> float:
    return 1.0 if analysis.checks.get(key, False) else 0.0


def _required(value: str | None) -> str:
    if value is None:
        raise ValueError("required campaign content hash is absent")
    return value
