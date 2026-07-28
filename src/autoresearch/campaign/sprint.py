"""Truthful, one-command autonomous research sprint orchestration.

This module closes three gaps left by task 260:

* topic selection must come from a live local model and cannot silently fall
  back to a code-authored topic;
* the selected topic must bind an executable analysis program;
* repeated deterministic seeds are measurements within a task, not additional
  independent experimental units.

The first sprint implementation is intentionally described as *bounded*
autonomy.  A local model chooses among several installed, executable research
programs and controls the primary comparison and generated manuscript.  The
program catalogue and the imported Route A evidence remain human-authored
boundaries, so the resulting audit cannot claim open-ended autonomous science.
"""

from __future__ import annotations

import json
import math
import os
import random
import re
import statistics
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal, TypeVar
from urllib.parse import urlparse

from pydantic import Field, ValidationError, model_validator

from autoresearch.campaign.models import StrictCampaignModel
from autoresearch.campaign.sprint_migration import (
    SprintMigrationCoordinator,
    SprintMigrationError,
    SprintMigrationMode,
    resolve_sprint_formal_run_id,
    resolve_sprint_migration_mode,
)
from autoresearch.campaign.systems import (
    SystemsBenchmarkResult,
    SystemsCellResult,
    SystemsMode,
    SystemsPreregistration,
    build_task260_systems_preregistration,
    load_systems_benchmark_result,
    run_systems_benchmark,
)
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.literature import AcademicPaper, ArxivClient, deduplicate_papers
from autoresearch.llm.client import (
    LLMClientError,
    LLMJsonCompletionResult,
    run_llm_json_completion,
)
from autoresearch.reports.figures import FigureArtifact, generate_metric_bar_figure
from autoresearch.reports.latex_templates import (
    LatexTemplateDependencyResolution,
    LatexTemplateDependencyStatus,
    LatexTemplateSourceKind,
    LatexTemplateSpec,
)
from autoresearch.reports.paper_build import (
    LatexPaperBuildArtifact,
    LatexPaperBuildStatus,
    LatexPaperQualityReport,
    build_latex_paper_from_markdown,
)
from autoresearch.schemas import data_hash, file_hash

_BOOTSTRAP_RESAMPLES = 20_000
_BOOTSTRAP_SEED = 2611
_MIN_LITERATURE_ITEMS = 3
_MIN_TOPIC_CANDIDATES = 3
_MIN_MANUSCRIPT_WORDS = 2_200
_MAX_MANUSCRIPT_WORDS = 2_500
_PATH_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_PROHIBITED_MANUSCRIPT_CLAIMS = (
    "guaranteed acceptance",
    "guaranteed to be accepted",
    "ccf-b ready",
    "accepted at a ccf",
    "state-of-the-art",
    "state of the art",
    "state-of-the-art performance",
)

JsonCompletion = Callable[..., LLMJsonCompletionResult]
LiteratureSearch = Callable[[str, int], Sequence[AcademicPaper]]
SystemsPreregister = Callable[..., SystemsPreregistration]
SystemsRun = Callable[..., SystemsBenchmarkResult]
PaperBuild = Callable[..., LatexPaperBuildArtifact]
FigureBuild = Callable[..., FigureArtifact]
ModelT = TypeVar("ModelT", bound=StrictCampaignModel)


class SprintStage(str, Enum):
    """Persisted next-action stages for one sprint."""

    LITERATURE = "literature"
    TOPIC_SELECTION = "topic_selection"
    EXPERIMENT = "experiment"
    TASK_LEVEL_ADJUDICATION = "task_level_adjudication"
    MANUSCRIPT = "manuscript"
    PAPER_BUILD = "paper_build"
    COMPLETE = "complete"


class SprintOutcome(str, Enum):
    """Top-level sprint outcome."""

    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"


class DecisionOrigin(str, Enum):
    """Who or what made one recorded sprint decision."""

    OPERATOR_PRELAUNCH = "operator_prelaunch"
    CODE_TEMPLATE = "code_template"
    EXTERNAL_SOURCE = "external_source"
    LOCAL_LLM = "local_llm"
    DETERMINISTIC_POLICY = "deterministic_policy"
    MANUAL_RUNTIME = "manual_runtime"


class AutonomyLevel(str, Enum):
    """Audited autonomy labels with deliberately narrow semantics."""

    ASSISTED = "assisted"
    BOUNDED_AUTONOMOUS = "bounded_autonomous"
    OPEN_ENDED_AUTONOMOUS = "open_ended_autonomous"


class SprintProgram(StrictCampaignModel):
    """One installed executable research program exposed to topic selection."""

    program_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]+$")
    title: str = Field(min_length=1)
    research_scope: str = Field(min_length=1)
    candidate_mode: SystemsMode
    baseline_mode: SystemsMode
    endpoint: Literal["task_success", "unsupported_claim"]
    direction: Literal["candidate_minus_baseline", "baseline_minus_candidate"]
    independent_unit: Literal["task"] = "task"
    minimum_independent_units: int = Field(default=10, ge=2)
    executable: bool = True


class SprintSpec(StrictCampaignModel):
    """Immutable high-level sprint boundary supplied before runtime."""

    schema_version: str = "autonomous-research-sprint-spec-v1"
    sprint_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    project_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    high_level_brief: str = Field(min_length=20)
    deadline: datetime
    route_a_campaign_path: str
    route_a_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    llm_config_path: str
    llm_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    program_ids: tuple[str, ...] = Field(min_length=_MIN_TOPIC_CANDIDATES)
    compile_pdf: bool = True
    live_literature_required: bool = True
    created_at: datetime
    local_execution_only: bool = True
    external_submission_authorized: bool = False

    @model_validator(mode="after")
    def _validate_sprint_boundary(self) -> SprintSpec:
        if self.deadline.tzinfo is None or self.deadline.utcoffset() is None:
            raise ValueError("sprint deadline must be timezone-aware")
        if len(set(self.program_ids)) != len(self.program_ids):
            raise ValueError("sprint program IDs must be unique")
        if not self.local_execution_only:
            raise ValueError("sprint must remain local-execution-only")
        if self.external_submission_authorized:
            raise ValueError("sprint cannot authorize external submission")
        return self


class SprintLiteratureItem(StrictCampaignModel):
    """Compact source record visible to the topic-selection model."""

    evidence_id: str = Field(pattern=r"^L[0-9]{3}$")
    title: str = Field(min_length=1)
    authors: tuple[str, ...]
    abstract: str
    publication_date: date | None = None
    venue: str | None = None
    doi: str | None = None
    url: str
    source: str = Field(min_length=1)
    retrieval_query: str = Field(min_length=1)


class SprintLiteratureSnapshot(StrictCampaignModel):
    """Hash-bound live literature evidence for topic selection."""

    schema_version: str = "autonomous-research-literature-snapshot-v1"
    sprint_id: str
    retrieved_at: datetime
    queries: tuple[str, ...] = Field(min_length=1)
    items: tuple[SprintLiteratureItem, ...] = Field(min_length=_MIN_LITERATURE_ITEMS)
    source_errors: tuple[str, ...] = ()
    snapshot_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class SprintTopicCandidate(StrictCampaignModel):
    """One local-model research candidate bound to executable code."""

    candidate_id: str = Field(pattern=r"^C[0-9]{3}$")
    title: str = Field(min_length=8)
    research_question: str = Field(min_length=20)
    hypothesis: str = Field(min_length=20)
    program_id: str = Field(min_length=1)
    mechanism_rationale: str = Field(min_length=20)
    novelty_risk: str = Field(min_length=10)
    falsification_conditions: tuple[str, ...] = Field(min_length=2)
    literature_refs: tuple[str, ...] = Field(min_length=1)


class _TopicSelectionOutput(StrictCampaignModel):
    candidates: tuple[SprintTopicCandidate, ...] = Field(
        min_length=_MIN_TOPIC_CANDIDATES,
        max_length=6,
    )
    selected_candidate_id: str = Field(pattern=r"^C[0-9]{3}$")
    selection_rationale: str = Field(min_length=20)


class SprintTopicSelection(StrictCampaignModel):
    """Auditable live local-model topic-selection evidence."""

    schema_version: str = "autonomous-research-topic-selection-v1"
    sprint_id: str
    brief_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    literature_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    program_catalog_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidates: tuple[SprintTopicCandidate, ...] = Field(
        min_length=_MIN_TOPIC_CANDIDATES
    )
    selected_candidate_id: str
    selection_rationale: str
    provider: str
    base_url: str
    model_name: str
    response_text: str
    usage: dict[str, Any]
    attempt_count: int = Field(default=1, ge=1, le=2)
    used_fallback: bool = False
    created_at: datetime
    selection_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_selected_candidate(self) -> SprintTopicSelection:
        candidate_ids = {candidate.candidate_id for candidate in self.candidates}
        if self.selected_candidate_id not in candidate_ids:
            raise ValueError("selected candidate is absent from candidate set")
        if self.used_fallback:
            raise ValueError("topic selection cannot use a fallback")
        return self

    @property
    def selected_candidate(self) -> SprintTopicCandidate:
        """Return the selected candidate."""

        return next(
            candidate
            for candidate in self.candidates
            if candidate.candidate_id == self.selected_candidate_id
        )


class TaskLevelEndpointResult(StrictCampaignModel):
    """Primary comparison with one independent observation per task."""

    schema_version: str = "autonomous-research-task-level-endpoint-v1"
    sprint_id: str
    benchmark_result_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    topic_selection_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_id: str
    program_id: str
    endpoint: str
    candidate_mode: SystemsMode
    baseline_mode: SystemsMode
    statistical_unit: Literal["task"] = "task"
    independent_unit_count: int = Field(ge=1)
    repeated_seed_count_per_task: int = Field(ge=1)
    paired_task_differences: dict[str, float]
    paired_mean_gain: float
    bootstrap_resamples: int = Field(ge=1_000)
    bootstrap_ci95_lower: float
    bootstrap_ci95_upper: float
    checks: dict[str, bool]
    passed: bool
    failures: tuple[str, ...]
    warnings: tuple[str, ...]
    created_at: datetime
    endpoint_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    external_submission_authorized: bool = False


class ManuscriptGenerationEvidence(StrictCampaignModel):
    """Local-model provenance for an automatically generated manuscript."""

    schema_version: str = "autonomous-research-manuscript-generation-v1"
    sprint_id: str
    candidate_id: str
    endpoint_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    literature_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: str
    base_url: str
    model_name: str
    response_text: str
    usage: dict[str, Any]
    attempt_count: int = Field(ge=1, le=2)
    used_fallback: bool = False
    manuscript_path: str
    manuscript_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    generated_word_count: int = Field(ge=1)
    created_at: datetime
    evidence_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class _ManuscriptOutput(StrictCampaignModel):
    title: str = Field(min_length=12)
    abstract: str = Field(min_length=300)
    introduction: str = Field(min_length=600)
    related_work: str = Field(min_length=600)
    method: str = Field(min_length=800)
    experiments: str = Field(min_length=800)
    result_disposition: Literal["gate_passed", "gate_failed"]
    citation_ids: tuple[str, ...] = Field(min_length=1)


class AutonomyEvent(StrictCampaignModel):
    """One hash-linked provenance event."""

    schema_version: str = "autonomous-research-autonomy-event-v1"
    sequence: int = Field(ge=1)
    recorded_at: datetime
    stage: SprintStage
    action: str = Field(min_length=1)
    origin: DecisionOrigin
    pre_start: bool
    research_decision: bool
    fallback_used: bool
    input_hashes: dict[str, str]
    output_hashes: dict[str, str]
    note: str
    parent_event_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    event_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class AutonomyLedger(StrictCampaignModel):
    """Append-only logical ledger persisted as one hash-bound JSON object."""

    schema_version: str = "autonomous-research-autonomy-ledger-v1"
    sprint_id: str
    events: tuple[AutonomyEvent, ...]
    ledger_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class SprintAutonomyAudit(StrictCampaignModel):
    """Truthful autonomy classification for the completed sprint."""

    schema_version: str = "autonomous-research-autonomy-audit-v1"
    sprint_id: str
    checked_at: datetime
    autonomy_level: AutonomyLevel
    checks: dict[str, bool]
    prelaunch_operator_research_decisions: int = Field(ge=0)
    post_start_manual_research_decisions: int = Field(ge=0)
    local_model_fallback_count: int = Field(ge=0)
    limitations: tuple[str, ...]
    allowed_claim: str
    prohibited_claims: tuple[str, ...]
    audit_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    external_submission_authorized: bool = False


class SprintManifest(StrictCampaignModel):
    """Durable state and artifact index for one sprint."""

    schema_version: str = "autonomous-research-sprint-manifest-v1"
    sprint_id: str
    spec_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    stage: SprintStage
    outcome: SprintOutcome
    selected_candidate_id: str | None = None
    selected_program_id: str | None = None
    artifact_paths: dict[str, str]
    artifact_sha256: dict[str, str]
    failure: str | None = None
    updated_at: datetime
    manifest_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    external_submission_authorized: bool = False


class SprintResult(StrictCampaignModel):
    """User-facing result from run, resume, or status."""

    sprint_dir: str
    outcome: SprintOutcome
    stage: SprintStage
    selected_candidate_id: str | None
    selected_program_id: str | None
    endpoint_passed: bool | None
    autonomy_level: AutonomyLevel | None
    manuscript_path: str | None
    manuscript_pdf_path: str | None
    manifest_path: str
    external_submission_authorized: bool = False


def installed_sprint_programs() -> tuple[SprintProgram, ...]:
    """Return the bounded executable topic catalogue for sprint v1."""

    return (
        SprintProgram(
            program_id="systems-success-recovery-task-v2",
            title="Task-level success recovery from evidence-bound iteration",
            research_scope=(
                "Compare the full evidence-bound loop with plan-then-execute once "
                "using task success as the primary endpoint."
            ),
            candidate_mode=SystemsMode.FULL_LOOP,
            baseline_mode=SystemsMode.EXECUTE_ONCE,
            endpoint="task_success",
            direction="candidate_minus_baseline",
        ),
        SprintProgram(
            program_id="systems-failure-feedback-task-v2",
            title="Task-level causal value of failure feedback",
            research_scope=(
                "Compare the full loop with the no-failure-feedback ablation using "
                "task success as the primary endpoint."
            ),
            candidate_mode=SystemsMode.FULL_LOOP,
            baseline_mode=SystemsMode.NO_FAILURE_FEEDBACK,
            endpoint="task_success",
            direction="candidate_minus_baseline",
        ),
        SprintProgram(
            program_id="systems-evidence-gate-claims-task-v2",
            title="Task-level claim-error reduction from deterministic evidence gates",
            research_scope=(
                "Compare unsupported-claim incidence in the full loop and the "
                "no-evidence-gate ablation, where positive gain means fewer errors."
            ),
            candidate_mode=SystemsMode.FULL_LOOP,
            baseline_mode=SystemsMode.NO_EVIDENCE_GATE,
            endpoint="unsupported_claim",
            direction="baseline_minus_candidate",
        ),
    )


def build_sprint_spec(
    *,
    sprint_id: str,
    project_id: str,
    high_level_brief: str,
    deadline: datetime,
    route_a_campaign_path: Path | str,
    llm_config_path: Path | str,
    compile_pdf: bool = True,
    live_literature_required: bool = True,
) -> SprintSpec:
    """Resolve and hash all prelaunch inputs for a sprint."""

    if not _PATH_SAFE_ID.fullmatch(sprint_id):
        raise ValueError("sprint_id must be path-safe")
    if not _PATH_SAFE_ID.fullmatch(project_id):
        raise ValueError("project_id must be path-safe")
    route_root = Path(route_a_campaign_path).resolve()
    route_manifest = route_root / "campaign-manifest.json"
    if not route_manifest.is_file():
        raise ValueError(f"Route A campaign manifest is missing: {route_manifest}")
    llm_path = Path(llm_config_path).resolve()
    if not llm_path.is_file():
        raise ValueError(f"local LLM config is missing: {llm_path}")
    programs = installed_sprint_programs()
    return SprintSpec(
        sprint_id=sprint_id,
        project_id=project_id,
        high_level_brief=high_level_brief,
        deadline=deadline,
        route_a_campaign_path=route_root.as_posix(),
        route_a_manifest_sha256=file_hash(route_manifest),
        llm_config_path=llm_path.as_posix(),
        llm_config_sha256=file_hash(llm_path),
        program_ids=tuple(program.program_id for program in programs),
        compile_pdf=compile_pdf,
        live_literature_required=live_literature_required,
        created_at=datetime.now(timezone.utc),
    )


class AutonomousResearchSprint:
    """Run or resume the complete bounded-autonomous sprint."""

    def __init__(
        self,
        *,
        output_root: Path | str = Path("runs/autonomous-sprints"),
        vault_root: Path | str = Path("autoresearch-vault"),
        completion: JsonCompletion = run_llm_json_completion,
        literature_search: LiteratureSearch | None = None,
        preregister: SystemsPreregister = build_task260_systems_preregistration,
        systems_run: SystemsRun | None = None,
        paper_build: PaperBuild = build_latex_paper_from_markdown,
        figure_build: FigureBuild = generate_metric_bar_figure,
        migration_mode: SprintMigrationMode | str | None = None,
        migration_root: Path | str | None = None,
        migration_formal_run_id: str | None = None,
    ) -> None:
        self.output_root = Path(output_root).resolve()
        self.vault_root = Path(vault_root).resolve()
        self.completion = completion
        self._arxiv = ArxivClient()
        self.literature_search = literature_search or self._search_arxiv
        self.preregister = preregister
        self.systems_run = systems_run or self._run_systems_without_reasoning
        self.paper_build = paper_build
        self.figure_build = figure_build
        self.migration_mode = resolve_sprint_migration_mode(migration_mode)
        formal_run_id = resolve_sprint_formal_run_id(migration_formal_run_id)
        if self.migration_mode is SprintMigrationMode.LEGACY:
            if formal_run_id is not None:
                raise SprintMigrationError(
                    "formal Sprint runs require shadow migration mode"
                )
            self._migration: SprintMigrationCoordinator | None = None
        else:
            root = (
                Path(migration_root)
                if migration_root is not None
                else self.output_root / ".vnext-migration" / "sprint"
            )
            self._migration = SprintMigrationCoordinator(
                root=root,
                mode=self.migration_mode,
                formal_run_id=formal_run_id,
                vault_root=self.vault_root,
            )

    def run(self, spec: SprintSpec) -> SprintResult:
        """Start or idempotently resume one sprint."""

        self._assert_migration_mode_allowed()
        sprint_dir = self.output_root / spec.sprint_id
        spec_path = sprint_dir / "sprint-spec.json"
        if spec_path.is_file():
            persisted = SprintSpec.model_validate_json(
                spec_path.read_text(encoding="utf-8")
            )
            persisted_boundary = persisted.model_dump(
                mode="json",
                exclude={"created_at"},
            )
            requested_boundary = spec.model_dump(
                mode="json",
                exclude={"created_at"},
            )
            if persisted_boundary != requested_boundary:
                raise ValueError("existing sprint ID belongs to a different spec")
            return self.resume(sprint_dir)
        try:
            if sprint_dir.exists() and any(sprint_dir.iterdir()):
                raise ValueError("sprint directory exists without a valid spec")
            sprint_dir.mkdir(parents=True, exist_ok=True)
            write_json_model(spec_path, spec)
            ledger = _stamp_ledger(
                AutonomyLedger(sprint_id=spec.sprint_id, events=())
            )
            write_json_model(sprint_dir / "autonomy-ledger.json", ledger)
            manifest = SprintManifest(
                sprint_id=spec.sprint_id,
                spec_hash=data_hash(spec),
                stage=SprintStage.LITERATURE,
                outcome=SprintOutcome.RUNNING,
                artifact_paths={"spec": spec_path.as_posix()},
                artifact_sha256={"spec": file_hash(spec_path)},
                updated_at=datetime.now(timezone.utc),
            )
            _write_manifest(sprint_dir / "sprint-manifest.json", manifest)
            self._append_event(
                sprint_dir,
                stage=SprintStage.LITERATURE,
                action="freeze_high_level_brief_and_runtime_boundary",
                origin=DecisionOrigin.OPERATOR_PRELAUNCH,
                pre_start=True,
                research_decision=True,
                fallback_used=False,
                input_hashes={},
                output_hashes={"spec": data_hash(spec)},
                note=(
                    "The operator supplied the high-level brief, deadline, local-compute "
                    "boundary, and imported Route A evidence before autonomous runtime."
                ),
            )
            self._append_event(
                sprint_dir,
                stage=SprintStage.LITERATURE,
                action="expose_installed_research_program_catalog",
                origin=DecisionOrigin.CODE_TEMPLATE,
                pre_start=True,
                research_decision=True,
                fallback_used=False,
                input_hashes={"spec": data_hash(spec)},
                output_hashes={"program_catalog": _program_catalog_hash()},
                note=(
                    "The executable program catalogue is code-authored and therefore "
                    "bounds topic autonomy."
                ),
            )
            result = self._resume_legacy(sprint_dir)
        except Exception as exc:
            self._record_migration_failure(
                sprint_dir=sprint_dir,
                sprint_id=spec.sprint_id,
                invocation_kind="run",
                error=exc,
            )
            raise
        return self._record_migration_result(
            sprint_dir=sprint_dir,
            result=result,
            invocation_kind="run",
        )

    def resume(self, sprint_dir: Path | str) -> SprintResult:
        """Resume without rerunning completed stages."""

        root = Path(sprint_dir).resolve()
        self._assert_migration_mode_allowed()
        try:
            result = self._resume_legacy(root)
        except Exception as exc:
            self._record_migration_failure(
                sprint_dir=root,
                sprint_id=root.name,
                invocation_kind="resume",
                error=exc,
            )
            raise
        return self._record_migration_result(
            sprint_dir=root,
            result=result,
            invocation_kind="resume",
        )

    def _resume_legacy(self, root: Path) -> SprintResult:
        """Execute the unchanged legacy resume path."""

        spec = _load_and_verify_spec(root)
        _load_manifest(root / "sprint-manifest.json", spec=spec)
        _load_ledger(root / "autonomy-ledger.json", sprint_id=spec.sprint_id)
        _verify_prelaunch_inputs(spec)
        if datetime.now(timezone.utc) > spec.deadline:
            return self._block(root, spec, "sprint deadline has passed")
        try:
            snapshot = self._ensure_literature(root, spec)
            selection = self._ensure_topic_selection(root, spec, snapshot)
            benchmark = self._ensure_experiment(root, spec, selection)
            endpoint = self._ensure_task_level_adjudication(
                root,
                spec,
                snapshot,
                selection,
                benchmark,
            )
            manuscript_evidence = self._ensure_manuscript(
                root,
                spec,
                snapshot,
                selection,
                endpoint,
            )
            paper = self._ensure_paper_build(
                root,
                spec,
                selection,
                endpoint,
                manuscript_evidence,
            )
            audit = self._ensure_autonomy_audit(
                root,
                spec,
                selection,
                endpoint,
                manuscript_evidence,
                paper,
            )
            self._write_completion_note(
                root,
                spec,
                selection,
                endpoint,
                manuscript_evidence,
                paper,
                audit,
            )
            manifest = _load_manifest(root / "sprint-manifest.json", spec=spec)
            if manifest.outcome is not SprintOutcome.COMPLETED:
                manifest = manifest.model_copy(
                    update={
                        "stage": SprintStage.COMPLETE,
                        "outcome": SprintOutcome.COMPLETED,
                        "failure": None,
                        "updated_at": datetime.now(timezone.utc),
                    }
                )
                _write_manifest(root / "sprint-manifest.json", manifest)
            return _result_from_root(root)
        except (
            LLMClientError,
            OSError,
            RuntimeError,
            ValidationError,
            ValueError,
        ) as exc:
            return self._block(root, spec, f"{type(exc).__name__}: {exc}")

    def _assert_migration_mode_allowed(self) -> None:
        if self._migration is not None:
            self._migration.assert_mode_allowed()

    def _record_migration_result(
        self,
        *,
        sprint_dir: Path,
        result: SprintResult,
        invocation_kind: Literal["run", "resume"],
    ) -> SprintResult:
        if self._migration is None:
            return result
        return self._migration.record_result(
            sprint_dir=sprint_dir,
            result=result,
            invocation_kind=invocation_kind,
        )

    def _record_migration_failure(
        self,
        *,
        sprint_dir: Path,
        sprint_id: str,
        invocation_kind: Literal["run", "resume"],
        error: Exception,
    ) -> None:
        if self._migration is None:
            return
        required = (
            sprint_dir / "sprint-spec.json",
            sprint_dir / "sprint-manifest.json",
            sprint_dir / "autonomy-ledger.json",
        )
        if not all(path.is_file() for path in required):
            return
        self._migration.record_failure(
            sprint_dir=sprint_dir,
            sprint_id=sprint_id,
            invocation_kind=invocation_kind,
            error=error,
        )

    def status(self, sprint_dir: Path | str) -> SprintResult:
        """Validate persisted hashes and return status without advancing work."""

        root = Path(sprint_dir).resolve()
        spec = _load_and_verify_spec(root)
        manifest = _load_manifest(root / "sprint-manifest.json", spec=spec)
        _load_ledger(root / "autonomy-ledger.json", sprint_id=spec.sprint_id)
        _verify_manifest_artifacts(manifest)
        return _result_from_root(root)

    def _ensure_literature(
        self,
        root: Path,
        spec: SprintSpec,
    ) -> SprintLiteratureSnapshot:
        path = root / "literature" / "snapshot.json"
        if path.is_file():
            snapshot = _load_stamped_model(
                path,
                SprintLiteratureSnapshot,
                "snapshot_hash",
            )
            if snapshot.sprint_id != spec.sprint_id:
                raise ValueError("literature snapshot belongs to another sprint")
            return snapshot
        queries = _literature_queries(spec.high_level_brief)
        papers: list[tuple[str, AcademicPaper]] = []
        errors: list[str] = []
        for query in queries:
            try:
                papers.extend(
                    (query, paper)
                    for paper in self.literature_search(query, 6)
                )
            except Exception as exc:  # noqa: BLE001 - external source boundary.
                errors.append(f"{query}: {type(exc).__name__}: {exc}")
        deduplicated = deduplicate_papers([paper for _, paper in papers])
        query_by_title = {
            _normalize_title(paper.title): query
            for query, paper in papers
        }
        items = tuple(
            SprintLiteratureItem(
                evidence_id=f"L{index:03d}",
                title=paper.title,
                authors=tuple(paper.authors),
                abstract=(paper.abstract or "No abstract returned.")[:2_400],
                publication_date=paper.publication_date,
                venue=paper.venue,
                doi=paper.doi,
                url=paper.url or _fallback_paper_url(paper),
                source=paper.source,
                retrieval_query=query_by_title.get(
                    _normalize_title(paper.title),
                    queries[0],
                ),
            )
            for index, paper in enumerate(deduplicated[:12], start=1)
        )
        if len(items) < _MIN_LITERATURE_ITEMS:
            raise ValueError(
                f"live literature returned {len(items)} items; "
                f"at least {_MIN_LITERATURE_ITEMS} are required"
            )
        draft = SprintLiteratureSnapshot(
            sprint_id=spec.sprint_id,
            retrieved_at=datetime.now(timezone.utc),
            queries=queries,
            items=items,
            source_errors=tuple(errors),
        )
        snapshot = _stamp_model(draft, "snapshot_hash")
        write_json_model(path, snapshot)
        self._append_event(
            root,
            stage=SprintStage.LITERATURE,
            action="retrieve_live_topic_prior_work",
            origin=DecisionOrigin.EXTERNAL_SOURCE,
            pre_start=False,
            research_decision=False,
            fallback_used=False,
            input_hashes={"brief": data_hash(spec.high_level_brief)},
            output_hashes={"literature_snapshot": _required_hash(snapshot.snapshot_hash)},
            note=(
                f"Retrieved {len(items)} distinct source records. Source errors are "
                "retained rather than hidden."
            ),
        )
        self._advance(
            root,
            spec,
            stage=SprintStage.TOPIC_SELECTION,
            artifacts={"literature_snapshot": path},
        )
        return snapshot

    def _ensure_topic_selection(
        self,
        root: Path,
        spec: SprintSpec,
        snapshot: SprintLiteratureSnapshot,
    ) -> SprintTopicSelection:
        path = root / "topic" / "selection.json"
        if path.is_file():
            selection = _load_stamped_model(
                path,
                SprintTopicSelection,
                "selection_hash",
            )
            _validate_topic_selection(selection, snapshot, spec)
            return selection
        programs = _programs_for_spec(spec)
        messages = _topic_selection_messages(spec, snapshot, programs)
        os.environ.setdefault("AUTORESEARCH_LOCAL_OLLAMA_API_KEY", "ollama-local")
        _, selection = self._generate_topic_selection(
            spec,
            snapshot,
            programs,
            messages,
        )
        write_json_model(path, selection)
        self._append_event(
            root,
            stage=SprintStage.TOPIC_SELECTION,
            action="select_primary_research_question_and_executable_program",
            origin=DecisionOrigin.LOCAL_LLM,
            pre_start=False,
            research_decision=True,
            fallback_used=False,
            input_hashes={
                "literature_snapshot": _required_hash(snapshot.snapshot_hash),
                "program_catalog": _program_catalog_hash(programs),
            },
            output_hashes={"topic_selection": _required_hash(selection.selection_hash)},
            note=(
                "The live local model selected the primary question. A malformed or "
                "unavailable model response blocks the sprint; no topic fallback exists."
                f" Structured local-model attempts: {selection.attempt_count}."
            ),
        )
        self._advance(
            root,
            spec,
            stage=SprintStage.EXPERIMENT,
            artifacts={"topic_selection": path},
            selection=selection,
        )
        return selection

    def _generate_topic_selection(
        self,
        spec: SprintSpec,
        snapshot: SprintLiteratureSnapshot,
        programs: Sequence[SprintProgram],
        messages: list[dict[str, str]],
    ) -> tuple[LLMJsonCompletionResult, SprintTopicSelection]:
        response: LLMJsonCompletionResult | None = None
        try:
            response = self.completion(
                messages=messages,
                config_path=spec.llm_config_path,
                env_path=Path("__no_sprint_env_file__"),
                timeout_seconds=180,
                max_tokens=1_800,
                temperature=0.0,
                reasoning_effort="none",
                response_schema=_TopicSelectionOutput.model_json_schema(),
                response_schema_name="sprint_topic_selection",
            )
            return response, _topic_selection_from_response(
                spec,
                snapshot,
                programs,
                response,
                attempt_count=1,
            )
        except (LLMClientError, ValidationError, ValueError) as first_error:
            repaired_messages = [
                *messages,
                *(
                    [{"role": "assistant", "content": response.response_text}]
                    if response is not None
                    else []
                ),
                {
                    "role": "user",
                    "content": (
                        "Repair the JSON structure and return the complete object again. "
                        "Do not add prose outside JSON. Return exactly three candidate "
                        "objects, one for each supplied program_id. Every candidate needs "
                        "at least two falsification_conditions and at least one supplied "
                        "literature_ref. selected_candidate_id and selection_rationale "
                        "must be top-level fields. Validator error: "
                        f"{first_error}"
                    ),
                },
            ]
            repaired = self.completion(
                messages=repaired_messages,
                config_path=spec.llm_config_path,
                env_path=Path("__no_sprint_env_file__"),
                timeout_seconds=180,
                max_tokens=2_400,
                temperature=0.05,
                reasoning_effort="none",
                response_schema=_TopicSelectionOutput.model_json_schema(),
                response_schema_name="sprint_topic_selection",
            )
            selection = _topic_selection_from_response(
                spec,
                snapshot,
                programs,
                repaired,
                attempt_count=2,
            )
            return repaired, selection

    def _ensure_experiment(
        self,
        root: Path,
        spec: SprintSpec,
        selection: SprintTopicSelection,
    ) -> SystemsBenchmarkResult:
        benchmark_root = root / "experiment" / "systems-benchmark"
        result_path = benchmark_root / "benchmark-result.json"
        if result_path.is_file():
            result = load_systems_benchmark_result(benchmark_root)
        else:
            self.preregister(
                benchmark_root,
                project_id=spec.project_id,
                deadline=spec.deadline,
                route_a_campaign_dir=spec.route_a_campaign_path,
                llm_config_path=spec.llm_config_path,
            )
            result = self.systems_run(benchmark_root)
        if result.local_model_fallback_count:
            raise ValueError(
                "systems benchmark used a local-model fallback; it cannot count as "
                "autonomous sprint evidence"
            )
        self._append_event_once(
            root,
            action="execute_frozen_multimode_systems_matrix",
            stage=SprintStage.EXPERIMENT,
            origin=DecisionOrigin.DETERMINISTIC_POLICY,
            research_decision=False,
            input_hashes={
                "topic_selection": _required_hash(selection.selection_hash),
                "route_a_manifest": spec.route_a_manifest_sha256,
            },
            output_hashes={"systems_result": _required_hash(result.result_hash)},
            note=(
                "The selected program does not change source truth or controller cells; "
                "it binds the primary comparison evaluated after the full frozen matrix."
            ),
        )
        self._advance(
            root,
            spec,
            stage=SprintStage.TASK_LEVEL_ADJUDICATION,
            artifacts={"systems_result": result_path},
            selection=selection,
        )
        return result

    def _ensure_task_level_adjudication(
        self,
        root: Path,
        spec: SprintSpec,
        snapshot: SprintLiteratureSnapshot,
        selection: SprintTopicSelection,
        benchmark: SystemsBenchmarkResult,
    ) -> TaskLevelEndpointResult:
        del snapshot
        path = root / "analysis" / "task-level-endpoint.json"
        if path.is_file():
            endpoint = _load_stamped_model(
                path,
                TaskLevelEndpointResult,
                "endpoint_hash",
            )
            if endpoint.topic_selection_hash != selection.selection_hash:
                raise ValueError("task-level endpoint belongs to another topic selection")
            return endpoint
        benchmark_root = Path(benchmark.matrix_manifest_path).resolve().parent
        prereg = SystemsPreregistration.model_validate_json(
            (benchmark_root / "preregistration.json").read_text(encoding="utf-8")
        )
        cells = _load_benchmark_cells(benchmark)
        program = _program_by_id(selection.selected_candidate.program_id)
        endpoint = compute_task_level_endpoint(
            sprint_id=spec.sprint_id,
            benchmark=benchmark,
            preregistration=prereg,
            cells=cells,
            selection=selection,
            program=program,
        )
        write_json_model(path, endpoint)
        _write_task_level_report(root / "analysis" / "research-report.md", endpoint)
        self._append_event(
            root,
            stage=SprintStage.TASK_LEVEL_ADJUDICATION,
            action="adjudicate_selected_endpoint_over_independent_tasks",
            origin=DecisionOrigin.DETERMINISTIC_POLICY,
            pre_start=False,
            research_decision=False,
            fallback_used=False,
            input_hashes={
                "systems_result": _required_hash(benchmark.result_hash),
                "topic_selection": _required_hash(selection.selection_hash),
            },
            output_hashes={"task_level_endpoint": _required_hash(endpoint.endpoint_hash)},
            note=(
                "Each task contributes one paired value. Three seed reruns are retained "
                "inside each task and are not counted as independent observations."
            ),
        )
        self._advance(
            root,
            spec,
            stage=SprintStage.MANUSCRIPT,
            artifacts={
                "task_level_endpoint": path,
                "research_report": root / "analysis" / "research-report.md",
            },
            selection=selection,
        )
        return endpoint

    def _ensure_manuscript(
        self,
        root: Path,
        spec: SprintSpec,
        snapshot: SprintLiteratureSnapshot,
        selection: SprintTopicSelection,
        endpoint: TaskLevelEndpointResult,
    ) -> ManuscriptGenerationEvidence:
        evidence_path = root / "manuscript" / "generation-evidence.json"
        if evidence_path.is_file():
            evidence = _load_stamped_model(
                evidence_path,
                ManuscriptGenerationEvidence,
                "evidence_hash",
            )
            manuscript_path = Path(evidence.manuscript_path)
            if (
                not manuscript_path.is_file()
                or file_hash(manuscript_path) != evidence.manuscript_sha256
            ):
                raise ValueError("generated manuscript changed after generation")
            return evidence
        messages = _manuscript_messages(spec, snapshot, selection, endpoint)
        response, draft, attempt_count, final_messages = self._generate_manuscript(
            spec,
            snapshot,
            endpoint,
            messages,
        )
        manuscript_dir = root / "manuscript"
        manuscript_dir.mkdir(parents=True, exist_ok=True)
        metrics_path = manuscript_dir / "endpoint-metrics.json"
        write_json_model(
            metrics_path,
            {
                "metrics": {
                    "paired_mean_gain": endpoint.paired_mean_gain,
                    "bootstrap_ci95_lower": endpoint.bootstrap_ci95_lower,
                    "bootstrap_ci95_upper": endpoint.bootstrap_ci95_upper,
                    "independent_task_count": float(endpoint.independent_unit_count),
                    "endpoint_passed": float(endpoint.passed),
                }
            },
        )
        figure = self.figure_build(
            metrics_path,
            manuscript_dir / "figures",
            title="Selected task-level endpoint",
            figure_id="selected-task-level-endpoint",
        )
        manuscript_path = manuscript_dir / "manuscript-v1.md"
        _write_text_atomic(
            manuscript_path,
            _render_manuscript_markdown(
                draft,
                snapshot,
                selection,
                endpoint,
                figure,
                manuscript_path.parent,
            ),
        )
        draft_word_count = _word_count(_draft_text(draft))
        generation = ManuscriptGenerationEvidence(
            sprint_id=spec.sprint_id,
            candidate_id=selection.selected_candidate_id,
            endpoint_hash=_required_hash(endpoint.endpoint_hash),
            literature_snapshot_hash=_required_hash(snapshot.snapshot_hash),
            prompt_hash=data_hash({"messages": final_messages}),
            provider=response.provider,
            base_url=response.base_url,
            model_name=response.model_name,
            response_text=response.response_text,
            usage=response.usage,
            attempt_count=attempt_count,
            used_fallback=False,
            manuscript_path=manuscript_path.as_posix(),
            manuscript_sha256=file_hash(manuscript_path),
            generated_word_count=draft_word_count,
            created_at=datetime.now(timezone.utc),
        )
        stamped = _stamp_model(generation, "evidence_hash")
        write_json_model(evidence_path, stamped)
        self._append_event(
            root,
            stage=SprintStage.MANUSCRIPT,
            action="generate_evidence_bound_manuscript_from_selected_result",
            origin=DecisionOrigin.LOCAL_LLM,
            pre_start=False,
            research_decision=False,
            fallback_used=False,
            input_hashes={
                "endpoint": _required_hash(endpoint.endpoint_hash),
                "literature": _required_hash(snapshot.snapshot_hash),
            },
            output_hashes={
                "manuscript": file_hash(manuscript_path),
                "generation_evidence": _required_hash(stamped.evidence_hash),
            },
            note=(
                "The local model generated the prose inside the running sprint. "
                "Exact numerical results, tables, figure, and references were rendered "
                "deterministically from frozen evidence."
            ),
        )
        self._advance(
            root,
            spec,
            stage=SprintStage.PAPER_BUILD,
            artifacts={
                "manuscript": manuscript_path,
                "manuscript_generation": evidence_path,
                "endpoint_figure": Path(figure.pdf_path),
            },
            selection=selection,
        )
        return stamped

    def _ensure_paper_build(
        self,
        root: Path,
        spec: SprintSpec,
        selection: SprintTopicSelection,
        endpoint: TaskLevelEndpointResult,
        manuscript: ManuscriptGenerationEvidence,
    ) -> LatexPaperBuildArtifact:
        paper_dir = root / "paper"
        build_json = paper_dir / "paper-build.json"
        if build_json.is_file():
            payload = json.loads(build_json.read_text(encoding="utf-8"))
            artifact = _paper_artifact_from_payload(payload)
        else:
            artifact = self.paper_build(
                manuscript.manuscript_path,
                paper_dir,
                template_id="acm-acmart-sigconf",
                title=None,
                authors=("AutoResearch Local Sprint",),
                compile_pdf=spec.compile_pdf,
                require_complete_sections=True,
                vault_root=self.vault_root,
                project_id=spec.project_id,
                timeout_seconds=180,
            )
        if spec.compile_pdf and artifact.status is not LatexPaperBuildStatus.COMPILED:
            raise ValueError(
                "automatic paper build did not pass the physical PDF gate: "
                f"{artifact.status.value}; {artifact.reason or 'no reason'}"
            )
        if spec.compile_pdf and (
            artifact.pdf_path is None or not Path(artifact.pdf_path).is_file()
        ):
            raise ValueError("automatic paper build reported no readable PDF")
        output_hashes = {"paper_build": file_hash(Path(artifact.json_path))}
        if artifact.pdf_path is not None:
            output_hashes["paper_pdf"] = file_hash(Path(artifact.pdf_path))
        self._append_event_once(
            root,
            action="compile_selected_manuscript_to_pdf",
            stage=SprintStage.PAPER_BUILD,
            origin=DecisionOrigin.DETERMINISTIC_POLICY,
            research_decision=False,
            input_hashes={
                "manuscript": manuscript.manuscript_sha256,
                "endpoint": _required_hash(endpoint.endpoint_hash),
            },
            output_hashes=output_hashes,
            note=(
                "PDF compilation was invoked automatically by the same sprint run; "
                "there was no separate paper-generation command."
            ),
        )
        artifacts = {"paper_build": Path(artifact.json_path)}
        if artifact.pdf_path is not None:
            artifacts["paper_pdf"] = Path(artifact.pdf_path)
        self._advance(
            root,
            spec,
            stage=SprintStage.COMPLETE,
            artifacts=artifacts,
            selection=selection,
        )
        return artifact

    def _ensure_autonomy_audit(
        self,
        root: Path,
        spec: SprintSpec,
        selection: SprintTopicSelection,
        endpoint: TaskLevelEndpointResult,
        manuscript: ManuscriptGenerationEvidence,
        paper: LatexPaperBuildArtifact,
    ) -> SprintAutonomyAudit:
        path = root / "audit" / "autonomy-audit.json"
        if path.is_file():
            return _load_stamped_model(
                path,
                SprintAutonomyAudit,
                "audit_hash",
            )
        ledger = _load_ledger(
            root / "autonomy-ledger.json",
            sprint_id=spec.sprint_id,
        )
        audit = build_sprint_autonomy_audit(
            spec=spec,
            selection=selection,
            endpoint=endpoint,
            manuscript=manuscript,
            paper=paper,
            ledger=ledger,
            sprint_root=root,
        )
        write_json_model(path, audit)
        self._advance(
            root,
            spec,
            stage=SprintStage.COMPLETE,
            artifacts={"autonomy_audit": path},
            selection=selection,
        )
        return audit

    def _generate_manuscript(
        self,
        spec: SprintSpec,
        snapshot: SprintLiteratureSnapshot,
        endpoint: TaskLevelEndpointResult,
        messages: list[dict[str, str]],
    ) -> tuple[
        LLMJsonCompletionResult,
        _ManuscriptOutput,
        int,
        list[dict[str, str]],
    ]:
        try:
            response = self.completion(
                messages=messages,
                config_path=spec.llm_config_path,
                env_path=Path("__no_sprint_env_file__"),
                timeout_seconds=240,
                max_tokens=4_800,
                temperature=0.15,
                reasoning_effort="none",
                response_schema=_ManuscriptOutput.model_json_schema(),
                response_schema_name="sprint_manuscript",
            )
            draft = _ManuscriptOutput.model_validate(response.parsed_json)
            _validate_manuscript_draft(draft, snapshot, endpoint)
            if _word_count(_draft_text(draft)) < _MIN_MANUSCRIPT_WORDS:
                raise ValueError("generated manuscript prose is below the sprint word floor")
            return response, draft, 1, messages
        except (LLMClientError, ValidationError, ValueError) as first_error:
            feedback = _manuscript_repair_feedback(first_error)
            repaired_messages = [
                *messages,
                {
                    "role": "user",
                    "content": (
                        "Regenerate the complete JSON manuscript from the frozen evidence. "
                        "The previous response is omitted to preserve context capacity. "
                        "Preserve the evidence boundary. The deterministic validator reported: "
                        f"{feedback}. Ensure {_MIN_MANUSCRIPT_WORDS}-"
                        f"{_MAX_MANUSCRIPT_WORDS} English words across the prose fields, "
                        "retain only supplied citation IDs, and do not invent numerical "
                        "results."
                    ),
                },
            ]
            repaired = self.completion(
                messages=repaired_messages,
                config_path=spec.llm_config_path,
                env_path=Path("__no_sprint_env_file__"),
                timeout_seconds=240,
                max_tokens=4_800,
                temperature=0.05,
                reasoning_effort="none",
                response_schema=_ManuscriptOutput.model_json_schema(),
                response_schema_name="sprint_manuscript",
            )
            draft = _ManuscriptOutput.model_validate(repaired.parsed_json)
            _validate_manuscript_draft(draft, snapshot, endpoint)
            if _word_count(_draft_text(draft)) < _MIN_MANUSCRIPT_WORDS:
                raise ValueError(
                    "repaired manuscript prose is below the sprint word floor"
                ) from first_error
            return repaired, draft, 2, repaired_messages

    def _advance(
        self,
        root: Path,
        spec: SprintSpec,
        *,
        stage: SprintStage,
        artifacts: Mapping[str, Path],
        selection: SprintTopicSelection | None = None,
    ) -> None:
        manifest_path = root / "sprint-manifest.json"
        manifest = _load_manifest(manifest_path, spec=spec)
        paths = dict(manifest.artifact_paths)
        hashes = dict(manifest.artifact_sha256)
        for name, path in artifacts.items():
            resolved = path.resolve()
            if not resolved.is_file():
                raise ValueError(f"sprint artifact is missing: {resolved}")
            paths[name] = resolved.as_posix()
            hashes[name] = file_hash(resolved)
        updates: dict[str, Any] = {
            "stage": stage,
            "outcome": SprintOutcome.RUNNING,
            "artifact_paths": paths,
            "artifact_sha256": hashes,
            "failure": None,
            "updated_at": datetime.now(timezone.utc),
        }
        if selection is not None:
            updates.update(
                {
                    "selected_candidate_id": selection.selected_candidate_id,
                    "selected_program_id": selection.selected_candidate.program_id,
                }
            )
        _write_manifest(manifest_path, manifest.model_copy(update=updates))

    def _append_event(
        self,
        root: Path,
        *,
        stage: SprintStage,
        action: str,
        origin: DecisionOrigin,
        pre_start: bool,
        research_decision: bool,
        fallback_used: bool,
        input_hashes: Mapping[str, str],
        output_hashes: Mapping[str, str],
        note: str,
    ) -> AutonomyEvent:
        path = root / "autonomy-ledger.json"
        ledger = _load_ledger(path, sprint_id=root.name)
        parent = ledger.events[-1].event_hash if ledger.events else None
        draft = AutonomyEvent(
            sequence=len(ledger.events) + 1,
            recorded_at=datetime.now(timezone.utc),
            stage=stage,
            action=action,
            origin=origin,
            pre_start=pre_start,
            research_decision=research_decision,
            fallback_used=fallback_used,
            input_hashes=dict(input_hashes),
            output_hashes=dict(output_hashes),
            note=note,
            parent_event_hash=parent,
        )
        event = _stamp_model(draft, "event_hash")
        updated = _stamp_ledger(
            ledger.model_copy(update={"events": (*ledger.events, event)})
        )
        write_json_model(path, updated)
        return event

    def _append_event_once(
        self,
        root: Path,
        *,
        action: str,
        stage: SprintStage,
        origin: DecisionOrigin,
        research_decision: bool,
        input_hashes: Mapping[str, str],
        output_hashes: Mapping[str, str],
        note: str,
    ) -> None:
        ledger = _load_ledger(root / "autonomy-ledger.json", sprint_id=root.name)
        if any(event.action == action for event in ledger.events):
            return
        self._append_event(
            root,
            stage=stage,
            action=action,
            origin=origin,
            pre_start=False,
            research_decision=research_decision,
            fallback_used=False,
            input_hashes=input_hashes,
            output_hashes=output_hashes,
            note=note,
        )

    def _block(
        self,
        root: Path,
        spec: SprintSpec,
        failure: str,
    ) -> SprintResult:
        manifest_path = root / "sprint-manifest.json"
        manifest = _load_manifest(manifest_path, spec=spec)
        blocked = manifest.model_copy(
            update={
                "outcome": SprintOutcome.BLOCKED,
                "failure": failure,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        _write_manifest(manifest_path, blocked)
        return _result_from_root(root)

    def _search_arxiv(self, query: str, limit: int) -> Sequence[AcademicPaper]:
        return self._arxiv.search(query, limit=limit)

    def _run_systems_without_reasoning(
        self,
        benchmark_dir: Path | str,
    ) -> SystemsBenchmarkResult:
        def completion_without_reasoning(**kwargs: Any) -> LLMJsonCompletionResult:
            return self.completion(**kwargs, reasoning_effort="none")

        return run_systems_benchmark(
            benchmark_dir,
            completion=completion_without_reasoning,
        )

    def _write_completion_note(
        self,
        root: Path,
        spec: SprintSpec,
        selection: SprintTopicSelection,
        endpoint: TaskLevelEndpointResult,
        manuscript: ManuscriptGenerationEvidence,
        paper: LatexPaperBuildArtifact,
        audit: SprintAutonomyAudit,
    ) -> None:
        note_path = (
            self.vault_root
            / "projects"
            / spec.project_id
            / "campaign"
            / spec.sprint_id
            / "sprint-report.md"
        )
        pdf_text = paper.pdf_path or "not compiled"
        _write_text_atomic(
            note_path,
            "\n".join(
                [
                    f"# Sprint {spec.sprint_id}",
                    "",
                    f"- Selected candidate: `{selection.selected_candidate_id}`",
                    f"- Program: `{selection.selected_candidate.program_id}`",
                    f"- Task-level gate: `{'passed' if endpoint.passed else 'failed'}`",
                    f"- Autonomy level: `{audit.autonomy_level.value}`",
                    f"- Manuscript: `{manuscript.manuscript_path}`",
                    f"- PDF: `{pdf_text}`",
                    f"- Sprint directory: `{root.as_posix()}`",
                    "- External submission authorized: `false`",
                    "",
                    "The autonomy audit is authoritative. This run may claim bounded "
                    "autonomous topic selection and artifact generation, but not open-ended "
                    "independent scientific discovery.",
                    "",
                ]
            ),
        )


def compute_task_level_endpoint(
    *,
    sprint_id: str,
    benchmark: SystemsBenchmarkResult,
    preregistration: SystemsPreregistration,
    cells: Sequence[SystemsCellResult],
    selection: SprintTopicSelection,
    program: SprintProgram,
) -> TaskLevelEndpointResult:
    """Aggregate repeated seed measurements inside each independent task."""

    if selection.selected_candidate.program_id != program.program_id:
        raise ValueError("selected candidate does not bind the supplied program")
    index = {
        (cell.mode, cell.task_id, cell.seed): cell
        for cell in cells
    }
    task_differences: dict[str, float] = {}
    for task in preregistration.tasks:
        repeated: list[float] = []
        for seed in preregistration.seeds:
            try:
                candidate = index[(program.candidate_mode, task.task_id, seed)]
                baseline = index[(program.baseline_mode, task.task_id, seed)]
            except KeyError as exc:
                raise ValueError(
                    f"missing paired cell for task {task.task_id}, seed {seed}"
                ) from exc
            candidate_value = _endpoint_value(candidate, program.endpoint)
            baseline_value = _endpoint_value(baseline, program.endpoint)
            difference = (
                candidate_value - baseline_value
                if program.direction == "candidate_minus_baseline"
                else baseline_value - candidate_value
            )
            repeated.append(difference)
        task_differences[task.task_id] = statistics.fmean(repeated)
    values = tuple(task_differences.values())
    mean = statistics.fmean(values)
    ci_lower, ci_upper = _bootstrap_mean_interval(
        values,
        resamples=_BOOTSTRAP_RESAMPLES,
        seed=_BOOTSTRAP_SEED,
    )
    selected_cells = [
        cell
        for cell in cells
        if cell.mode in {program.candidate_mode, program.baseline_mode}
    ]
    checks = {
        "statistical_unit_is_task": True,
        "minimum_independent_task_count": (
            len(values) >= program.minimum_independent_units
        ),
        "paired_task_coverage_complete": (
            len(selected_cells)
            == len(preregistration.tasks)
            * len(preregistration.seeds)
            * 2
        ),
        "bootstrap_ci_lower_above_zero": ci_lower > 0.0,
        "selected_modes_exactly_reproduce": all(
            cell.exact_reproduction for cell in selected_cells
        ),
        "local_model_fallback_count_zero": (
            benchmark.local_model_fallback_count == 0
        ),
        "post_start_human_research_decisions_zero": (
            benchmark.campaign_research_decision_human_interventions == 0
        ),
    }
    failures = tuple(name for name, passed in checks.items() if not passed)
    draft = TaskLevelEndpointResult(
        sprint_id=sprint_id,
        benchmark_result_hash=_required_hash(benchmark.result_hash),
        topic_selection_hash=_required_hash(selection.selection_hash),
        candidate_id=selection.selected_candidate_id,
        program_id=program.program_id,
        endpoint=program.endpoint,
        candidate_mode=program.candidate_mode,
        baseline_mode=program.baseline_mode,
        independent_unit_count=len(values),
        repeated_seed_count_per_task=len(preregistration.seeds),
        paired_task_differences=task_differences,
        paired_mean_gain=mean,
        bootstrap_resamples=_BOOTSTRAP_RESAMPLES,
        bootstrap_ci95_lower=ci_lower,
        bootstrap_ci95_upper=ci_upper,
        checks=checks,
        passed=all(checks.values()),
        failures=failures,
        warnings=(
            "Seed reruns are repeated measurements within tasks and do not increase n.",
            "The controlled fault suite evaluates system behaviour, not arbitrary "
            "open-ended scientific discovery.",
            "An internal endpoint gate does not authorize external submission.",
        ),
        created_at=datetime.now(timezone.utc),
    )
    return _stamp_model(draft, "endpoint_hash")


def build_sprint_autonomy_audit(
    *,
    spec: SprintSpec,
    selection: SprintTopicSelection,
    endpoint: TaskLevelEndpointResult,
    manuscript: ManuscriptGenerationEvidence,
    paper: LatexPaperBuildArtifact,
    ledger: AutonomyLedger,
    sprint_root: Path,
) -> SprintAutonomyAudit:
    """Classify autonomy without allowing bounded runs to claim open-ended autonomy."""

    prelaunch_operator = sum(
        event.pre_start
        and event.research_decision
        and event.origin is DecisionOrigin.OPERATOR_PRELAUNCH
        for event in ledger.events
    )
    post_start_manual = sum(
        not event.pre_start
        and event.research_decision
        and event.origin is DecisionOrigin.MANUAL_RUNTIME
        for event in ledger.events
    )
    fallbacks = sum(event.fallback_used for event in ledger.events)
    selected_programs = {candidate.program_id for candidate in selection.candidates}
    local_selection = _is_local_base_url(selection.base_url)
    local_manuscript = _is_local_base_url(manuscript.base_url)
    pdf_exists = paper.pdf_path is not None and Path(paper.pdf_path).is_file()
    checks = {
        "live_local_model_selected_topic": (
            local_selection and not selection.used_fallback
        ),
        "multiple_executable_programs_considered": (
            len(selected_programs) >= _MIN_TOPIC_CANDIDATES
            and selected_programs.issubset(set(spec.program_ids))
        ),
        "selected_topic_controls_primary_analysis": (
            endpoint.candidate_id == selection.selected_candidate_id
            and endpoint.program_id == selection.selected_candidate.program_id
        ),
        "independent_statistical_unit_is_task": (
            endpoint.statistical_unit == "task"
            and endpoint.independent_unit_count >= 10
        ),
        "experiment_executed_inside_sprint": (
            (
                sprint_root
                / "experiment"
                / "systems-benchmark"
                / "benchmark-result.json"
            ).is_file()
        ),
        "paper_prose_generated_by_live_local_model": (
            local_manuscript and not manuscript.used_fallback
        ),
        "paper_build_automatic_in_same_ledger": any(
            event.action == "compile_selected_manuscript_to_pdf"
            for event in ledger.events
        ),
        "paper_pdf_exists": pdf_exists if spec.compile_pdf else True,
        "post_start_manual_research_decisions_zero": post_start_manual == 0,
        "external_submission_blocked": not spec.external_submission_authorized,
        "route_a_generated_inside_same_sprint": False,
        "open_ended_experiment_code_generation": False,
    }
    bounded_required = (
        "live_local_model_selected_topic",
        "multiple_executable_programs_considered",
        "selected_topic_controls_primary_analysis",
        "independent_statistical_unit_is_task",
        "experiment_executed_inside_sprint",
        "paper_prose_generated_by_live_local_model",
        "paper_build_automatic_in_same_ledger",
        "paper_pdf_exists",
        "post_start_manual_research_decisions_zero",
        "external_submission_blocked",
    )
    open_required = (
        *bounded_required,
        "route_a_generated_inside_same_sprint",
        "open_ended_experiment_code_generation",
    )
    if all(checks[name] for name in open_required):
        level = AutonomyLevel.OPEN_ENDED_AUTONOMOUS
    elif all(checks[name] for name in bounded_required):
        level = AutonomyLevel.BOUNDED_AUTONOMOUS
    else:
        level = AutonomyLevel.ASSISTED
    draft = SprintAutonomyAudit(
        sprint_id=spec.sprint_id,
        checked_at=datetime.now(timezone.utc),
        autonomy_level=level,
        checks=checks,
        prelaunch_operator_research_decisions=int(prelaunch_operator),
        post_start_manual_research_decisions=int(post_start_manual),
        local_model_fallback_count=int(fallbacks),
        limitations=(
            "The high-level brief, executable program catalogue, and compute/deadline "
            "bounds were fixed by humans before runtime.",
            "Route A evidence was imported from a prior campaign rather than generated "
            "inside this sprint invocation.",
            "The selected program controls a real primary analysis and manuscript, but "
            "does not generate arbitrary new experiment code.",
            "The systems matrix uses controlled workflow faults; generalization to "
            "unconstrained research projects remains unproven.",
        ),
        allowed_claim=(
            "The sprint performed bounded autonomous topic selection among installed "
            "executable programs, ran the selected task-level analysis, generated the "
            "manuscript, and invoked PDF compilation without post-start manual research "
            "decisions."
        ),
        prohibited_claims=(
            "The sprint independently invented an unrestricted research field and method.",
            "The sprint generated Route A and Route B from one completely human-free run.",
            "The paper is accepted, guaranteed CCF-B quality, or externally submitted.",
        ),
    )
    return _stamp_model(draft, "audit_hash")


def _validate_topic_selection(
    selection: SprintTopicSelection,
    snapshot: SprintLiteratureSnapshot,
    spec: SprintSpec,
) -> None:
    if selection.brief_hash != data_hash(spec.high_level_brief):
        raise ValueError("topic selection brief hash mismatch")
    if selection.literature_snapshot_hash != snapshot.snapshot_hash:
        raise ValueError("topic selection literature hash mismatch")
    programs = _programs_for_spec(spec)
    if selection.program_catalog_hash != _program_catalog_hash(programs):
        raise ValueError("topic selection program catalogue hash mismatch")
    program_ids = {program.program_id for program in programs if program.executable}
    candidate_programs = [candidate.program_id for candidate in selection.candidates]
    if len(set(candidate_programs)) < _MIN_TOPIC_CANDIDATES:
        raise ValueError("topic candidates must span at least three executable programs")
    if not set(candidate_programs).issubset(program_ids):
        raise ValueError("topic selection referenced a non-executable program")
    evidence_ids = {item.evidence_id for item in snapshot.items}
    for candidate in selection.candidates:
        if not set(candidate.literature_refs).issubset(evidence_ids):
            raise ValueError(
                f"candidate {candidate.candidate_id} invented a literature reference"
            )
    if not _is_local_base_url(selection.base_url):
        raise ValueError("topic selection did not use a loopback local model endpoint")


def _topic_selection_from_response(
    spec: SprintSpec,
    snapshot: SprintLiteratureSnapshot,
    programs: Sequence[SprintProgram],
    response: LLMJsonCompletionResult,
    *,
    attempt_count: int,
) -> SprintTopicSelection:
    parsed = _TopicSelectionOutput.model_validate(response.parsed_json)
    draft = SprintTopicSelection(
        sprint_id=spec.sprint_id,
        brief_hash=data_hash(spec.high_level_brief),
        literature_snapshot_hash=_required_hash(snapshot.snapshot_hash),
        program_catalog_hash=_program_catalog_hash(programs),
        candidates=parsed.candidates,
        selected_candidate_id=parsed.selected_candidate_id,
        selection_rationale=parsed.selection_rationale,
        provider=response.provider,
        base_url=response.base_url,
        model_name=response.model_name,
        response_text=response.response_text,
        usage=response.usage,
        attempt_count=attempt_count,
        used_fallback=False,
        created_at=datetime.now(timezone.utc),
    )
    selection = _stamp_model(draft, "selection_hash")
    _validate_topic_selection(selection, snapshot, spec)
    return selection


def _topic_selection_messages(
    spec: SprintSpec,
    snapshot: SprintLiteratureSnapshot,
    programs: Sequence[SprintProgram],
) -> list[dict[str, str]]:
    literature = [
        {
            "evidence_id": item.evidence_id,
            "title": item.title,
            "abstract": item.abstract[:600],
            "publication_date": (
                item.publication_date.isoformat()
                if item.publication_date is not None
                else None
            ),
            "venue": item.venue,
            "url": item.url,
        }
        for item in snapshot.items
    ]
    catalogue = [program.model_dump(mode="json") for program in programs]
    return [
        {
            "role": "system",
            "content": (
                "/no_think\n"
                "You are the local topic-selection controller for an evidence-first "
                "research sprint. Return only one JSON object. Do not invent papers, "
                "results, adapter IDs, or numerical outcomes. Candidates are hypotheses, "
                "not findings. You must choose among the executable programs supplied."
            ),
        },
        {
            "role": "user",
            "content": (
                f"High-level brief:\n{spec.high_level_brief}\n\n"
                "Executable program catalogue:\n"
                f"{json.dumps(catalogue, ensure_ascii=False, sort_keys=True)}\n\n"
                "Live literature evidence:\n"
                f"{json.dumps(literature, ensure_ascii=False, sort_keys=True)}\n\n"
                "Return exactly three candidates spanning three distinct program_id "
                "values, then select one. Schema: "
                '{"candidates":[{"candidate_id":"C001","title":"...",'
                '"research_question":"...","hypothesis":"...",'
                '"program_id":"one supplied ID","mechanism_rationale":"...",'
                '"novelty_risk":"...","falsification_conditions":["...","..."],'
                '"literature_refs":["L001"]}],"selected_candidate_id":"C001",'
                '"selection_rationale":"..."}. The selection rationale must weigh novelty '
                "risk, falsifiability, independent task count, and the deadline."
            ),
        },
    ]


def _manuscript_messages(
    spec: SprintSpec,
    snapshot: SprintLiteratureSnapshot,
    selection: SprintTopicSelection,
    endpoint: TaskLevelEndpointResult,
) -> list[dict[str, str]]:
    candidate = selection.selected_candidate
    result_disposition = "gate_passed" if endpoint.passed else "gate_failed"
    prioritized_items = sorted(
        snapshot.items,
        key=lambda item: (
            item.evidence_id not in set(candidate.literature_refs),
            item.evidence_id,
        ),
    )[:6]
    evidence = {
        "candidate": candidate.model_dump(mode="json"),
        "endpoint": {
            "program_id": endpoint.program_id,
            "endpoint": endpoint.endpoint,
            "candidate_mode": endpoint.candidate_mode.value,
            "baseline_mode": endpoint.baseline_mode.value,
            "statistical_unit": endpoint.statistical_unit,
            "independent_unit_count": endpoint.independent_unit_count,
            "repeated_seed_count_per_task": endpoint.repeated_seed_count_per_task,
            "paired_mean_gain": endpoint.paired_mean_gain,
            "bootstrap_ci95_lower": endpoint.bootstrap_ci95_lower,
            "bootstrap_ci95_upper": endpoint.bootstrap_ci95_upper,
            "passed": endpoint.passed,
            "failures": endpoint.failures,
            "warnings": endpoint.warnings,
        },
        "literature": [
            {
                "evidence_id": item.evidence_id,
                "title": item.title,
                "authors": item.authors,
                "abstract": item.abstract[:240],
                "publication_date": (
                    item.publication_date.isoformat()
                    if item.publication_date is not None
                    else None
                ),
                "venue": item.venue,
                "url": item.url,
            }
            for item in prioritized_items
        ],
    }
    return [
        {
            "role": "system",
            "content": (
                "/no_think\n"
                "You are a local scientific manuscript composer. Return only JSON. "
                "Use only supplied evidence. Avoid any claim of comparative superiority, "
                "guaranteed publication, venue suitability, acceptance, or external "
                "submission. Do not repeat such claims even in a negated disclaimer. "
                "Do not invent metrics, task "
                "counts, citations, ablations, human studies, or experiments. Treat the "
                "task—not seed—as the independent statistical unit. Cite supplied work "
                "with tokens such as [@L001]. Explicitly distinguish controlled workflow "
                "faults from open-ended scientific discovery."
            ),
        },
        {
            "role": "user",
            "content": (
                f"High-level brief:\n{spec.high_level_brief}\n\n"
                "Frozen evidence:\n"
                f"{json.dumps(evidence, ensure_ascii=False, sort_keys=True)}\n\n"
                f"Write {_MIN_MANUSCRIPT_WORDS}-{_MAX_MANUSCRIPT_WORDS} English words "
                "across the prose fields. Keep the abstract at 180-210 words, "
                "introduction at 500-550, related work at 450-500, method at 620-680, "
                "and experiments at 520-570. Results, limitations, and conclusion are "
                "rendered by deterministic code and must not be included. "
                "Return: "
                '{"title":"...","abstract":"...","introduction":"...",'
                '"related_work":"...","method":"...","experiments":"...",'
                f'"result_disposition":"{result_disposition}",'
                '"citation_ids":["L001"]}. Do not repeat exact numerical endpoint values '
                "in the prose; deterministic code will insert the authoritative result "
                "table and figure. Discuss what a positive or negative frozen gate means."
            ),
        },
    ]


def _validate_manuscript_draft(
    draft: _ManuscriptOutput,
    snapshot: SprintLiteratureSnapshot,
    endpoint: TaskLevelEndpointResult,
) -> None:
    allowed = {item.evidence_id for item in snapshot.items}
    if not set(draft.citation_ids).issubset(allowed):
        raise ValueError("manuscript invented citation IDs")
    text = _draft_text(draft).casefold()
    prohibited = [claim for claim in _PROHIBITED_MANUSCRIPT_CLAIMS if claim in text]
    if prohibited:
        raise ValueError(f"manuscript contains prohibited claims: {prohibited}")
    expected_disposition = "gate_passed" if endpoint.passed else "gate_failed"
    if draft.result_disposition != expected_disposition:
        raise ValueError(
            "manuscript result disposition contradicts deterministic adjudication"
        )
    inline_refs = {
        match.upper()
        for match in re.findall(r"\[@?(L[0-9]{3})\]", _draft_text(draft), flags=re.I)
    }
    if not inline_refs.issubset(allowed):
        unknown = sorted(inline_refs - allowed)
        raise ValueError(f"manuscript invented inline citation IDs: {unknown}")


def _manuscript_repair_feedback(
    error: LLMClientError | ValidationError | ValueError,
) -> str:
    text = str(error)
    if "prohibited claims" in text:
        return (
            "a forbidden publication-status or comparative-superiority phrase appeared; "
            "do not emit that phrase again, including inside a negated disclaimer"
        )
    return text


def _render_manuscript_markdown(
    draft: _ManuscriptOutput,
    snapshot: SprintLiteratureSnapshot,
    selection: SprintTopicSelection,
    endpoint: TaskLevelEndpointResult,
    figure: FigureArtifact,
    manuscript_dir: Path,
) -> str:
    figure_path = os.path.relpath(
        Path(figure.pdf_path),
        start=manuscript_dir,
    ).replace("\\", "/")
    task_rows = "\n".join(
        f"| T{index:02d} | {difference:.6f} |"
        for index, difference in enumerate(
            endpoint.paired_task_differences.values(),
            start=1,
        )
    )
    resolved_citation_ids = _resolved_citation_ids(draft)
    references = "\n".join(
        (
            f"- [@{item.evidence_id}] "
            f"{', '.join(item.authors) or 'Unknown authors'}. "
            f"{item.title}. "
            f"{item.publication_date.isoformat() if item.publication_date else 'n.d.'}. "
            f"{item.url}"
        )
        for item in snapshot.items
        if item.evidence_id in resolved_citation_ids
    )
    citation_bindings = " ".join(
        f"[@{citation_id}]" for citation_id in resolved_citation_ids
    )
    gate_text = "passed" if endpoint.passed else "failed"
    result_interpretation = _deterministic_result_interpretation(endpoint)
    audit_appendix = _deterministic_audit_appendix(endpoint, selection)
    return "\n".join(
        [
            f"# {draft.title}",
            "",
            "## Abstract",
            "",
            _normalize_citation_tokens(draft.abstract),
            "",
            "## Introduction",
            "",
            _normalize_citation_tokens(draft.introduction),
            "",
            "## Related Work",
            "",
            _normalize_citation_tokens(draft.related_work),
            "",
            f"Frozen source bindings: {citation_bindings}",
            "",
            "## Method",
            "",
            _normalize_citation_tokens(draft.method),
            "",
            "### Autonomy and analysis contract",
            "",
            (
                f"The local topic selector chose candidate "
                f"`{selection.selected_candidate_id}` and executable program "
                f"`{endpoint.program_id}`. The program fixes `{endpoint.candidate_mode.value}` "
                f"as the candidate mode, `{endpoint.baseline_mode.value}` as the baseline, "
                f"and `{endpoint.endpoint}` as the endpoint. The independent unit is the "
                "task. Seed reruns are averaged within task before resampling."
            ),
            "",
            "## Experiments",
            "",
            _normalize_citation_tokens(draft.experiments),
            "",
            "### Frozen statistical protocol",
            "",
            (
                f"The benchmark contains {endpoint.independent_unit_count} independent "
                f"tasks and {endpoint.repeated_seed_count_per_task} repeated deterministic "
                "seed measurements per task. The paired bootstrap resamples the task-level "
                f"differences {_BOOTSTRAP_RESAMPLES} times with frozen seed "
                f"{_BOOTSTRAP_SEED}. No seed-level row is treated as an independent unit."
            ),
            "",
            "## Results",
            "",
            result_interpretation,
            "",
            "### Deterministic primary result",
            "",
            (
                f"The task-level mean gain is `{endpoint.paired_mean_gain:.6f}` and the "
                f"95% paired bootstrap interval is "
                f"`[{endpoint.bootstrap_ci95_lower:.6f}, "
                f"{endpoint.bootstrap_ci95_upper:.6f}]`. The frozen endpoint gate "
                f"`{gate_text}`. These values are rendered directly from "
                f"endpoint artifact `{_required_hash(endpoint.endpoint_hash)[:12]}`."
            ),
            "",
            "| Independent task | Paired gain |",
            "|---|---:|",
            task_rows,
            "",
            f"![Task-level endpoint with frozen mean and interval]({figure_path})",
            "",
            "## Limitations",
            "",
            (
                "This sprint is bounded autonomous research. Humans fixed the high-level "
                "brief, installed program catalogue, deadline, and compute boundary before "
                "runtime. Route A evidence was imported. The selected program controlled "
                "the primary analysis and manuscript, but arbitrary experiment code was "
                "not synthesized. External submission remains unauthorized."
            ),
            "",
            *audit_appendix,
            "",
            "## Conclusion",
            "",
            _deterministic_conclusion(endpoint),
            "",
            "## References",
            "",
            references,
            "",
        ]
    )


def _resolved_citation_ids(draft: _ManuscriptOutput) -> tuple[str, ...]:
    inline = {
        match.upper()
        for match in re.findall(r"\[@?(L[0-9]{3})\]", _draft_text(draft), flags=re.I)
    }
    return tuple(sorted(set(draft.citation_ids) | inline))


def _normalize_citation_tokens(text: str) -> str:
    return re.sub(
        r"\[@?(L[0-9]{3})\]",
        lambda match: f"[@{match.group(1).upper()}]",
        text,
        flags=re.I,
    )


def _deterministic_conclusion(endpoint: TaskLevelEndpointResult) -> str:
    if endpoint.passed:
        disposition = (
            "The frozen endpoint gate passed, supporting only the registered claim on "
            "this controlled task panel."
        )
    else:
        disposition = (
            "The frozen endpoint gate failed because its paired bootstrap lower bound "
            "did not exceed zero. The run therefore does not establish the selected "
            "improvement claim; it neither proves the mechanism ineffective in general "
            "nor licenses a broader negative conclusion."
        )
    return (
        f"{disposition} The contribution of this artifact is the auditable process: "
        "task-level inference, retained negative evidence, a hash-linked autonomy ledger, "
        "and automatic manuscript/PDF production from frozen inputs. The deterministic "
        "adjudicator, rather than model prose, fixes the interpretation. A future round "
        "must introduce a new mechanism hypothesis and an unrevealed evaluation unit "
        "without lowering the registered threshold. External submission remains a human "
        "decision, and this bounded sprint is not evidence of unrestricted autonomous "
        "scientific discovery or guaranteed venue readiness. The retained negative "
        "evidence remains the authoritative scientific outcome of this sprint."
    )


def _deterministic_result_interpretation(
    endpoint: TaskLevelEndpointResult,
) -> str:
    values = tuple(endpoint.paired_task_differences.values())
    positive_count = sum(value > 0 for value in values)
    zero_count = sum(value == 0 for value in values)
    negative_count = sum(value < 0 for value in values)
    distribution = (
        f"At task level, {positive_count} paired differences are positive, "
        f"{zero_count} are zero, and {negative_count} are negative. "
        "The T01--T10 labels in the table preserve the endpoint artifact's registered "
        "task order while avoiding long machine identifiers in the typeset layout. "
        "These counts describe the frozen sample and are not additional hypothesis tests. "
        "Seed reruns remain within-task measurements throughout this summary. "
    )
    checks_passed = sum(endpoint.checks.values())
    check_summary = (
        f"The adjudicator evaluated {len(endpoint.checks)} registered checks; "
        f"{checks_passed} passed and {len(endpoint.checks) - checks_passed} failed. "
        "Those checks cover the minimum independent-task count, the frozen comparison, "
        "exact reproduction, absence of local-model fallback, and absence of post-start "
        "human research decisions. They are conjunctive: a favorable mean cannot "
        "compensate for a failed confidence-bound, reproduction, provenance, or autonomy "
        "condition. This ordering was fixed before the paper narrative was rendered, so "
        "the result section cannot select a more favorable endpoint after inspection. "
    )
    if endpoint.passed:
        return (
            "The frozen contribution gate passed for the selected endpoint: the paired "
            "task-level interval has a lower bound strictly above zero and every other "
            "registered check passed. This supports a narrow claim about the controlled "
            "ten-task suite only. It does not establish performance on open-ended "
            "scientific discovery, a broader task population, or an external venue."
            f" {distribution}{check_summary}"
        )
    return (
        "The frozen contribution gate failed for the selected endpoint. Although the "
        "observed mean gain is positive in the registered direction, the paired "
        "task-level bootstrap interval includes zero at its lower boundary. The run "
        "therefore does not support a reliable reduction in unsupported claims over "
        "the registered comparison. No qualitative trend, seed-level repetition, or "
        "manuscript wording overrides this negative adjudication. "
        f"{distribution}{check_summary}"
    )


def _deterministic_audit_appendix(
    endpoint: TaskLevelEndpointResult,
    selection: SprintTopicSelection,
) -> list[str]:
    return [
        "### Reproducibility and audit protocol",
        "",
        (
            "The reproducibility unit is the complete hash-bound sprint directory. A "
            "review begins with the sprint specification, verifies the imported Route A "
            "manifest and local-model configuration hashes, then checks that the live "
            "literature snapshot, topic selection, preregistration, matrix manifest, "
            "cell results, endpoint report, manuscript evidence, and paper build all "
            "match their recorded digests. The configuration fixes the model endpoint "
            "to loopback execution and records external cost as zero. The topic record "
            f"binds candidate {selection.selected_candidate_id} to one executable "
            "program before the primary analysis is rendered. Re-running status "
            "validation does not regenerate completed artifacts; it checks their "
            "content hashes and rejects mutation."
        ),
        "",
        (
            "To recompute the primary statistic, a reproducer loads every registered "
            "cell, groups observations by independent task and comparison mode, averages "
            "the three deterministic seed measurements within each task, and forms one "
            "paired difference per task. The bootstrap samples those task differences "
            f"with replacement {_BOOTSTRAP_RESAMPLES} times using seed "
            f"{_BOOTSTRAP_SEED}. The mean and percentile interval are then compared with "
            "the preregistered zero threshold. This algorithm prevents repeated seeds "
            "from inflating the nominal sample size. The matrix, configuration, dataset "
            "references, validation artifacts, and result hashes remain available for "
            "an exact reproduction audit."
        ),
        "",
        "### Failure-aware interpretation",
        "",
        (
            f"The registered endpoint uses `{endpoint.endpoint}` with "
            f"`{endpoint.candidate_mode.value}` as candidate and "
            f"`{endpoint.baseline_mode.value}` as baseline. The independent task count "
            f"is {endpoint.independent_unit_count}; the seed count is a repeated-measure "
            f"count of {endpoint.repeated_seed_count_per_task}, not an additional sample "
            "size. A positive point estimate is insufficient: the lower confidence "
            "bound must be strictly positive, exact reproduction must hold, local-model "
            "fallbacks must be zero, and post-start human research decisions must remain "
            "zero. When any check fails, the artifact is a retained negative result. "
            "This failure-aware rule blocks selective reporting, threshold relaxation, "
            "and unsupported novelty or robustness claims."
        ),
        "",
        "### Threats to validity",
        "",
        (
            "Internal validity is limited by the controlled fault injection and by the "
            "fact that several workflow outcomes are deterministic once task, mode, and "
            "seed are fixed. Construct validity is limited because an unsupported-claim "
            "indicator captures evidence discipline but not scientific creativity, "
            "theoretical importance, or expert judgment. External validity is limited "
            "to four UCI-derived tasks and six MDBench-derived tasks in the frozen suite; "
            "these tasks do not represent the population of open-ended research "
            "problems. Statistical precision is limited by ten independent tasks, so "
            "the bootstrap interval is necessarily coarse. Literature retrieval is a "
            "live snapshot rather than an exhaustive systematic review, and citation "
            "coverage should be expanded before any venue submission."
        ),
        "",
        (
            "The systems comparison also inherits implementation choices from the "
            "installed benchmark harness. A different fault distribution, evaluator, "
            "model, configuration, or stopping rule could change the result. The current "
            "experiment does not provide an ablation of every gate component, a human "
            "study, or evidence about long-running scientific programs. Those missing "
            "analyses are explicit limitations, not evidence that the selected mechanism "
            "is ineffective in all settings. Conversely, they cannot be used to rescue "
            "a failed frozen gate."
        ),
        "",
        "### Autonomy boundary",
        "",
        (
            "Autonomy is bounded. Before runtime, a human supplied the high-level brief, "
            "deadline, local-compute restriction, imported Route A evidence, and an "
            "installed catalogue of executable programs. After start, the live local "
            "model selected among those programs and generated manuscript prose; "
            "deterministic code executed the benchmark, validation, statistical "
            "adjudication, figure, table, citation binding, and PDF compilation. The "
            "sprint did not synthesize arbitrary experiment code or independently invent "
            "the full research field. The autonomy ledger separates prelaunch operator "
            "decisions from runtime model and algorithm events, records fallback use, "
            "and keeps external submission unauthorized."
        ),
        "",
        "### Artifact-level review checklist",
        "",
        (
            "A reviewer should confirm that the hypothesis references a known literature "
            "item, the selected program is executable, the preregistration predates the "
            "matrix result, every cell points to source evidence, the analysis uses task "
            "rather than seed as its statistical unit, and all paper numbers originate "
            "from the endpoint JSON. The reviewer should also inspect failure reports, "
            "configuration locks, reproduction commands, figure metadata, bibliography "
            "entries, and the autonomy audit. Passing the mechanical checklist indicates "
            "artifact consistency; it does not imply novelty, acceptance, or scientific "
            "importance. Those judgments remain outside the automated gate."
        ),
        "",
        "### Data lineage and configuration control",
        "",
        (
            "Every reported quantity has a bounded lineage. Source evidence identifies "
            "the frozen task input; the preregistration identifies task family, fault, "
            "comparison modes, seeds, metric, stopping rule, evaluator code, and deadline; "
            "the matrix manifest identifies each cell result; and the endpoint artifact "
            "identifies the ordered task differences and bootstrap configuration. The "
            "manuscript renderer consumes that endpoint rather than retyping values from "
            "model prose. Figure metadata records the plotted metric names and source "
            "file, while the LaTeX build records template, compiler, command, log, page "
            "count, section depth, bibliography coverage, and layout diagnostics. Hash "
            "validation turns later mutation into a visible error instead of silently "
            "changing the scientific record."
        ),
        "",
        (
            "Configuration control is equally narrow. The local model may propose and "
            "compose structured text, but it does not decide whether a confidence "
            "interval passes, whether a task counts as independent, or whether a claim "
            "has adequate support. The deterministic evaluator owns those decisions. "
            "No cloud model or external GPU is part of the recorded run, and fallback "
            "models are disabled. A resume operation reuses completed hash-verified "
            "artifacts and only retries the first missing stage; changing the brief, "
            "model configuration, imported campaign, program catalogue, or deadline "
            "creates a specification mismatch rather than an unnoticed continuation."
        ),
        "",
        "### Scope of the negative result",
        "",
        (
            "A negative gate has a precise scope. It says that this frozen task panel, "
            "comparison, estimator, and decision threshold did not establish the selected "
            "claim with the required uncertainty bound. It does not show that evidence "
            "gates are useless, that another implementation would fail, or that the "
            "observed point estimate is fabricated. It also does not justify searching "
            "the same revealed panel for a better threshold. A scientifically valid next "
            "round would require a new mechanism hypothesis, a new preregistration, and "
            "an unrevealed evaluation unit. Preserving this distinction is central to the "
            "campaign's failure library and prevents a research loop from converting "
            "ordinary uncertainty into a publication claim."
        ),
        "",
        "### Registered estimand and decision rule",
        "",
        (
            "The estimand is the mean paired change in the selected binary endpoint over "
            "the frozen task population represented by the panel. For each task, the "
            "candidate-mode measurements are averaged across registered seeds, the "
            "baseline-mode measurements are averaged in the same way, and the signed "
            "difference is oriented so that a positive value favors the candidate "
            "program. Resampling operates on the resulting task vector. This choice "
            "answers a system-level question about expected task behavior; it is not an "
            "estimate of token-level, run-level, or paper-level quality. The percentile "
            "interval is descriptive of the registered panel and resampling procedure, "
            "not a substitute for a larger independent task sample."
        ),
        "",
        (
            "The decision rule is intentionally stricter than observing a positive mean. "
            "The lower 95% bound must exceed zero, every selected cell must reproduce, "
            "the model-fallback count must remain zero, and runtime human research "
            "intervention must remain zero. Because these conditions are conjunctive, "
            "failure of one condition fixes the verdict even if the others pass. No "
            "multiple-comparison correction is needed for the paper's single selected "
            "primary endpoint, but the topic selector considered several executable "
            "programs before selection. That bounded selection process is part of the "
            "reported autonomy design and limits confirmatory interpretation."
        ),
        "",
        "### Reproduction failure modes",
        "",
        (
            "A reproduction can fail for scientific or operational reasons, and the "
            "audit keeps them separate. Scientific mismatch occurs when recomputed cell "
            "outcomes, task differences, confidence bounds, or gate decisions differ "
            "despite matching inputs and evaluator code. Operational mismatch includes "
            "missing source artifacts, unavailable local model configuration, compiler "
            "failure, an altered environment, or an incomplete matrix. Hash mismatch "
            "indicates that an artifact changed after its parent recorded it. Schema "
            "failure indicates that a model response or manifest does not satisfy the "
            "machine-readable contract. Each condition blocks completion and remains a "
            "failure report; none authorizes substituting cached metrics or manually "
            "editing a result into compliance."
        ),
        "",
        (
            "Exact reproduction in this sprint means equality of the registered "
            "scientific result hashes and deterministic adjudication under the frozen "
            "environment. It does not mean that another model version, hardware stack, "
            "task sample, or future dependency release must produce identical prose or "
            "wall-clock time. The paper therefore separates scientific hashes from "
            "presentation artifacts and reports compute cost independently. This "
            "separation allows a reviewer to diagnose whether a discrepancy affects the "
            "claim, the execution environment, or only the rendered document."
        ),
        "",
        "### Requirements for a subsequent research round",
        "",
        (
            "A subsequent round must begin from the retained negative result rather than "
            "silently reopening it. The new hypothesis must identify a mechanism-level "
            "change, bind its parent failure hash, state why the change could address the "
            "observed limitation, and define a falsification condition. Code, parameter "
            "space, seeds, metrics, stopping rule, evaluator, and unseen task panel must "
            "be frozen before evaluation. Once the new panel is revealed, within-round "
            "tuning is prohibited. Reusing this panel for candidate search would turn it "
            "into development evidence and require another untouched panel for a "
            "confirmatory claim."
        ),
        "",
        (
            "The next round should also broaden the evidence base: add independent tasks, "
            "measure latency and intervention cost, separate pre-execution from "
            "post-execution gates through ablation, and compare against a stronger "
            "one-pass and plan-then-execute baseline. These are proposed requirements, "
            "not completed experiments. Until such evidence exists, the current report "
            "remains a bounded negative result with a reproducible artifact package, not "
            "a claim of general scientific autonomy or publication readiness."
        ),
    ]


def _load_benchmark_cells(
    benchmark: SystemsBenchmarkResult,
) -> tuple[SystemsCellResult, ...]:
    manifest_path = Path(benchmark.matrix_manifest_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    cells: list[SystemsCellResult] = []
    for item in payload.get("cells", []):
        path = Path(str(item["path"]))
        cell = SystemsCellResult.model_validate_json(path.read_text(encoding="utf-8"))
        expected = canonical_model_hash(cell.model_copy(update={"result_hash": None}))
        if cell.result_hash != expected or cell.result_hash != item.get("result_hash"):
            raise ValueError(f"systems cell hash mismatch: {path}")
        cells.append(cell)
    if len(cells) != benchmark.cell_count:
        raise ValueError("systems matrix manifest has incomplete cell coverage")
    return tuple(cells)


def _endpoint_value(
    cell: SystemsCellResult,
    endpoint: str,
) -> float:
    if endpoint == "task_success":
        return float(cell.task_success)
    if endpoint == "unsupported_claim":
        return float(cell.unsupported_claim_count > 0)
    raise ValueError(f"unsupported sprint endpoint: {endpoint}")


def _bootstrap_mean_interval(
    values: Sequence[float],
    *,
    resamples: int,
    seed: int,
) -> tuple[float, float]:
    if not values:
        raise ValueError("bootstrap requires independent task observations")
    rng = random.Random(seed)
    count = len(values)
    samples = sorted(
        statistics.fmean(values[rng.randrange(count)] for _ in range(count))
        for _ in range(resamples)
    )
    return _quantile(samples, 0.025), _quantile(samples, 0.975)


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


def _write_task_level_report(
    path: Path,
    endpoint: TaskLevelEndpointResult,
) -> None:
    rows = [
        "| Task | Paired gain |",
        "|---|---:|",
        *[
            f"| {task_id} | {difference:.6f} |"
            for task_id, difference in endpoint.paired_task_differences.items()
        ],
    ]
    _write_text_atomic(
        path,
        "\n".join(
            [
                f"# Task-Level Endpoint Report: {endpoint.candidate_id}",
                "",
                f"- Program: `{endpoint.program_id}`",
                f"- Statistical unit: `{endpoint.statistical_unit}`",
                f"- Independent units: `{endpoint.independent_unit_count}`",
                f"- Seed repetitions per task: `{endpoint.repeated_seed_count_per_task}`",
                f"- Mean gain: `{endpoint.paired_mean_gain:.6f}`",
                (
                    f"- Bootstrap 95% CI: `[{endpoint.bootstrap_ci95_lower:.6f}, "
                    f"{endpoint.bootstrap_ci95_upper:.6f}]`"
                ),
                f"- Gate: `{'passed' if endpoint.passed else 'failed'}`",
                "",
                *rows,
                "",
                "Seeds are not independent experimental units. External submission is "
                "not authorized.",
                "",
            ]
        ),
    )


def _literature_queries(brief: str) -> tuple[str, ...]:
    del brief
    return (
        'all:"autonomous research" AND all:evidence',
        'all:"AI scientist" AND all:benchmark',
        'all:"scientific discovery" AND all:agent',
    )


def _programs_for_spec(spec: SprintSpec) -> tuple[SprintProgram, ...]:
    by_id = {program.program_id: program for program in installed_sprint_programs()}
    missing = [program_id for program_id in spec.program_ids if program_id not in by_id]
    if missing:
        raise ValueError(f"sprint program catalogue changed; missing={missing}")
    return tuple(by_id[program_id] for program_id in spec.program_ids)


def _program_by_id(program_id: str) -> SprintProgram:
    for program in installed_sprint_programs():
        if program.program_id == program_id:
            return program
    raise ValueError(f"research program is not installed: {program_id}")


def _program_catalog_hash(
    programs: Sequence[SprintProgram] | None = None,
) -> str:
    selected = tuple(programs or installed_sprint_programs())
    return data_hash(
        {"programs": [program.model_dump(mode="json") for program in selected]}
    )


def _load_and_verify_spec(root: Path) -> SprintSpec:
    spec_path = root / "sprint-spec.json"
    spec = SprintSpec.model_validate_json(spec_path.read_text(encoding="utf-8"))
    if root.name != spec.sprint_id:
        raise ValueError("sprint directory name does not match spec")
    return spec


def _verify_prelaunch_inputs(spec: SprintSpec) -> None:
    route_manifest = Path(spec.route_a_campaign_path) / "campaign-manifest.json"
    if (
        not route_manifest.is_file()
        or file_hash(route_manifest) != spec.route_a_manifest_sha256
    ):
        raise ValueError("imported Route A manifest changed after sprint start")
    llm_path = Path(spec.llm_config_path)
    if not llm_path.is_file() or file_hash(llm_path) != spec.llm_config_sha256:
        raise ValueError("local LLM config changed after sprint start")


def _write_manifest(path: Path, manifest: SprintManifest) -> SprintManifest:
    stamped = _stamp_model(
        manifest.model_copy(update={"manifest_hash": None}),
        "manifest_hash",
    )
    write_json_model(path, stamped)
    return stamped


def _load_manifest(path: Path, *, spec: SprintSpec) -> SprintManifest:
    manifest = _load_stamped_model(path, SprintManifest, "manifest_hash")
    if manifest.sprint_id != spec.sprint_id or manifest.spec_hash != data_hash(spec):
        raise ValueError("sprint manifest does not match spec")
    return manifest


def _verify_manifest_artifacts(manifest: SprintManifest) -> None:
    for name, expected in manifest.artifact_sha256.items():
        raw_path = manifest.artifact_paths.get(name)
        if raw_path is None:
            raise ValueError(f"manifest hash has no path for {name}")
        path = Path(raw_path)
        if not path.is_file() or file_hash(path) != expected:
            raise ValueError(f"sprint artifact changed: {name}")


def _stamp_model(model: ModelT, hash_field: str) -> ModelT:
    unstamped = model.model_copy(update={hash_field: None})
    digest = canonical_model_hash(unstamped)
    return unstamped.model_copy(update={hash_field: digest})


def _load_stamped_model(
    path: Path,
    model_type: type[ModelT],
    hash_field: str,
) -> ModelT:
    model = model_type.model_validate_json(path.read_text(encoding="utf-8"))
    expected = canonical_model_hash(model.model_copy(update={hash_field: None}))
    if getattr(model, hash_field) != expected:
        raise ValueError(f"{model_type.__name__} hash mismatch: {path}")
    return model


def _stamp_ledger(ledger: AutonomyLedger) -> AutonomyLedger:
    return _stamp_model(ledger, "ledger_hash")


def _load_ledger(path: Path, *, sprint_id: str) -> AutonomyLedger:
    ledger = _load_stamped_model(path, AutonomyLedger, "ledger_hash")
    if ledger.sprint_id != sprint_id:
        raise ValueError("autonomy ledger belongs to another sprint")
    parent: str | None = None
    for index, event in enumerate(ledger.events, start=1):
        expected = canonical_model_hash(event.model_copy(update={"event_hash": None}))
        if event.sequence != index or event.parent_event_hash != parent:
            raise ValueError("autonomy event sequence or parent hash mismatch")
        if event.event_hash != expected:
            raise ValueError("autonomy event hash mismatch")
        parent = event.event_hash
    return ledger


def _result_from_root(root: Path) -> SprintResult:
    spec = _load_and_verify_spec(root)
    manifest = _load_manifest(root / "sprint-manifest.json", spec=spec)
    endpoint_path = manifest.artifact_paths.get("task_level_endpoint")
    endpoint_passed: bool | None = None
    if endpoint_path and Path(endpoint_path).is_file():
        endpoint = _load_stamped_model(
            Path(endpoint_path),
            TaskLevelEndpointResult,
            "endpoint_hash",
        )
        endpoint_passed = endpoint.passed
    audit_path = manifest.artifact_paths.get("autonomy_audit")
    autonomy_level: AutonomyLevel | None = None
    if audit_path and Path(audit_path).is_file():
        audit = _load_stamped_model(
            Path(audit_path),
            SprintAutonomyAudit,
            "audit_hash",
        )
        autonomy_level = audit.autonomy_level
    paper_build_path = manifest.artifact_paths.get("paper_build")
    pdf_path: str | None = None
    if paper_build_path and Path(paper_build_path).is_file():
        payload = json.loads(Path(paper_build_path).read_text(encoding="utf-8"))
        raw_pdf = payload.get("pdf_path")
        pdf_path = str(raw_pdf) if isinstance(raw_pdf, str) else None
    return SprintResult(
        sprint_dir=root.as_posix(),
        outcome=manifest.outcome,
        stage=manifest.stage,
        selected_candidate_id=manifest.selected_candidate_id,
        selected_program_id=manifest.selected_program_id,
        endpoint_passed=endpoint_passed,
        autonomy_level=autonomy_level,
        manuscript_path=manifest.artifact_paths.get("manuscript"),
        manuscript_pdf_path=pdf_path,
        manifest_path=(root / "sprint-manifest.json").as_posix(),
    )


def _paper_artifact_from_payload(payload: Mapping[str, Any]) -> LatexPaperBuildArtifact:
    template_payload = payload["template"]
    dependency_payload = payload["dependency_resolution"]
    quality_payload = payload["paper_quality"]
    template = LatexTemplateSpec(
        id=str(template_payload["id"]),
        display_name=str(template_payload["display_name"]),
        source_kind=LatexTemplateSourceKind(str(template_payload["source_kind"])),
        document_class=str(template_payload["document_class"]),
        class_options=tuple(template_payload.get("class_options", ())),
        class_file=template_payload.get("class_file"),
        preamble_lines=tuple(template_payload.get("preamble_lines", ())),
        abstract_before_maketitle=bool(
            template_payload.get("abstract_before_maketitle", False)
        ),
        source_url=template_payload.get("source_url"),
        texlive_package=template_payload.get("texlive_package"),
        source_archive_url=template_payload.get("source_archive_url"),
        source_archive_member=template_payload.get("source_archive_member"),
        license_note=str(template_payload.get("license_note", "")),
    )
    dependency = LatexTemplateDependencyResolution(
        status=LatexTemplateDependencyStatus(str(dependency_payload["status"])),
        checked_at=str(dependency_payload["checked_at"]),
        class_file=dependency_payload.get("class_file"),
        message=str(dependency_payload["message"]),
        command=tuple(dependency_payload.get("command", ())),
        returncode=dependency_payload.get("returncode"),
        artifact_path=dependency_payload.get("artifact_path"),
        stdout_tail=dependency_payload.get("stdout_tail"),
        stderr_tail=dependency_payload.get("stderr_tail"),
        error=dependency_payload.get("error"),
    )
    quality = LatexPaperQualityReport(
        passed=bool(quality_payload["passed"]),
        page_count=quality_payload.get("page_count"),
        min_pages=int(quality_payload["min_pages"]),
        word_count=int(quality_payload["word_count"]),
        min_word_count=int(quality_payload["min_word_count"]),
        technical_term_count=int(quality_payload["technical_term_count"]),
        min_technical_terms=int(quality_payload["min_technical_terms"]),
        section_word_counts={
            str(key): int(value)
            for key, value in quality_payload["section_word_counts"].items()
        },
        section_min_words={
            str(key): int(value)
            for key, value in quality_payload["section_min_words"].items()
        },
        short_sections=tuple(quality_payload["short_sections"]),
        overfull_hbox_count=int(quality_payload["overfull_hbox_count"]),
        max_overfull_hbox_count=int(quality_payload["max_overfull_hbox_count"]),
        max_overfull_hbox_points=float(quality_payload["max_overfull_hbox_points"]),
        max_allowed_overfull_hbox_points=float(
            quality_payload["max_allowed_overfull_hbox_points"]
        ),
        figure_count=int(quality_payload["figure_count"]),
        min_figures=int(quality_payload["min_figures"]),
        table_count=int(quality_payload["table_count"]),
        min_tables=int(quality_payload["min_tables"]),
        bibliography_item_count=int(quality_payload["bibliography_item_count"]),
        min_bibliography_items=int(quality_payload["min_bibliography_items"]),
        invalid_reference_label_count=int(
            quality_payload["invalid_reference_label_count"]
        ),
        figure_readability_issue_count=int(
            quality_payload["figure_readability_issue_count"]
        ),
        figure_readability_issues=tuple(
            quality_payload["figure_readability_issues"]
        ),
        failures=tuple(quality_payload["failures"]),
    )
    return LatexPaperBuildArtifact(
        status=LatexPaperBuildStatus(str(payload["status"])),
        generated_at=str(payload["generated_at"]),
        template=template,
        source_markdown_path=str(payload["source_markdown_path"]),
        tex_path=(
            str(payload["tex_path"]) if payload.get("tex_path") is not None else None
        ),
        pdf_path=(
            str(payload["pdf_path"]) if payload.get("pdf_path") is not None else None
        ),
        log_path=str(payload["log_path"]),
        markdown_path=str(payload["markdown_path"]),
        json_path=str(payload["json_path"]),
        vault_markdown_path=(
            str(payload["vault_markdown_path"])
            if payload.get("vault_markdown_path") is not None
            else None
        ),
        missing_sections=tuple(payload.get("missing_sections", ())),
        engine=str(payload["engine"]) if payload.get("engine") is not None else None,
        command=tuple(payload.get("command", ())),
        dependency_resolution=dependency,
        quality=quality,
        reason=str(payload["reason"]) if payload.get("reason") is not None else None,
    )


def _fallback_paper_url(paper: AcademicPaper) -> str:
    if paper.doi:
        return f"https://doi.org/{paper.doi}"
    return f"urn:autoresearch:literature:{data_hash(paper.title)[:16]}"


def _normalize_title(title: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", title.casefold()).split())


def _required_hash(value: str | None) -> str:
    if value is None:
        raise ValueError("required artifact has no content hash")
    return value


def _is_local_base_url(value: str) -> bool:
    host = (urlparse(value).hostname or "").casefold()
    return host in {"127.0.0.1", "localhost", "::1"}


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _draft_text(draft: _ManuscriptOutput) -> str:
    return "\n".join(
        (
            draft.title,
            draft.abstract,
            draft.introduction,
            draft.related_work,
            draft.method,
            draft.experiments,
        )
    )


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[A-Za-z][A-Za-z0-9-]*\b", text))


def _write_text_atomic(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
    return path
