"""Distributed, model-authored opportunity cells under one finite stage authority.

The implementation authors no scientific claim.  It projects each routing binding
into one bounded worker payload, runs seven one-shot authors and seven distinct
one-shot reviewers, then mechanically validates and assembles their exact JSON.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from autoresearch.agents.temporary import (
    StageControllerBinding,
    StageDispatchCapability,
    TemporaryAgentInputRef,
    TemporaryAgentSkillRef,
    TemporaryAgentTaskKind,
)
from autoresearch.competition.manifest import write_json_model
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.competition.system_plan_methodology import (
    SystemPlanMethodSkillSelectionBinding,
)
from autoresearch.competition.system_plan_opportunity_map import (
    OpportunityCellAssessment,
    ResearchFeasibilityEnvelope,
    ResearchOpportunityCell,
    ResearchOpportunityMap,
    ResearchOpportunityMapBinding,
    ResearchOpportunityMapReview,
)
from autoresearch.competition.system_plan_opportunity_routing import (
    OpportunityWorkerBinding,
    SystemPlanOpportunityRoutingArtifact,
)
from autoresearch.competition.temporary_qwen_pool import (
    CompletionCallable,
    TemporaryQwenBatchArtifact,
    TemporaryQwenBatchError,
    TemporaryQwenContentTask,
    TemporaryQwenPhaseManifest,
    TemporaryQwenSkillContext,
    TemporaryQwenStagePhaseBinding,
    TemporaryQwenStagePhaseSession,
    run_temporary_qwen_content_batch,
)
from autoresearch.kernel.contracts import Sha256, canonical_sha256
from autoresearch.llm.client import run_llm_json_completion

_OUTPUT_NAME = "system-plan-opportunity-distributed.json"
_AUTHOR_PHASE = "opportunity-author"
_REVIEWER_PHASE = "opportunity-review"
_CELL_IDS = tuple(f"O{index:02d}" for index in range(1, 8))
_AUTHOR_CHINESE_FIELDS = (
    "unresolved_contradiction",
    "operational_construct",
    "mechanism_preconditions",
    "manipulable_factor",
    "measurable_outcome",
    "alternative_explanation",
    "single_component_counterfactual",
    "negative_control",
    "sensitivity_control",
    "orthogonal_diagnostic",
    "independent_analysis_unit",
    "result_blind_decision_rule",
    "resource_bounded_minimal_diagnostic",
    "discriminating_observation",
    "expected_directional_pattern",
    "refuting_observation",
    "why_not_component_composition",
    "feasibility_risk",
    "method_application_trace",
)
_ESTIMAND_WORKER_KEYS = (
    "cell_loss",
    "paired_effect",
    "independent_unit",
    "repeated_measure_aggregation",
    "system_aggregation",
    "uncertainty",
    "minimum_overall_log_effect",
    "ode_stratum_median_minimum",
    "pde_stratum_median_minimum",
    "all_candidate_full_cells_must_succeed",
    "all_domain_baseline_cells_must_succeed",
    "all_scientific_contract_gates_must_pass",
    "receipt_if_and_only_if_all_checks_pass",
)
_SEARCH_BUDGET_WORKER_KEYS = (
    "maximum_mechanism_candidate_cell_budget",
    "maximum_mechanism_cycles",
    "maximum_model_interactions",
    "maximum_parallel_cells",
    "maximum_cpu_cores_per_cell",
    "maximum_memory_mb_per_cell",
    "maximum_seconds_per_cell",
    "maximum_generations",
    "maximum_total_candidate_count",
    "minimum_mechanism_family_count",
)
_STAGE_BREADTH_WORKER_KEYS = (
    "available_ode_count",
    "available_pde_count",
    "pilot_ode_count",
    "pilot_pde_count",
    "pilot_system_count",
    "breadth_reduced",
    "pilot_enters_estimand",
    "frozen_parent_budget_modified",
    "baseline_policy_hash",
    "breadth_hash",
    "contradiction_package_hash",
)
_DATA_PROFILE_WORKER_KEYS = (
    "array_shapes",
    "channel_count",
    "channels",
    "conditions_profiled",
    "coordinates",
    "data_type",
    "derivative_channel_max_abs_correlation",
    "sample_axis_count",
    "state_channel_max_abs_correlation",
    "system_name",
)
_SYSTEM_EFFECT_WORKER_KEYS = (
    "baseline_available",
    "candidate_cell_count",
    "candidate_success_count",
    "data_type",
    "lineage_id",
    "package_hash",
    "paired_log_effect",
    "selected_candidate_id",
    "system_name",
)
_JSON_SCHEMA_ANNOTATION_KEYS = frozenset(
    {
        "$comment",
        "default",
        "deprecated",
        "description",
        "examples",
        "readOnly",
        "title",
        "writeOnly",
    }
)
_TASK_ROUTE_KEYS = (
    "cell_id",
    "target_systems",
    "evidence_fact_ids",
    "literature_indices",
    "component_atom_id",
    "single_component_assignment",
)


class DistributedOpportunityPipelineError(RuntimeError):
    """Fail-closed error with any terminal batch/artifact already available."""

    def __init__(
        self,
        message: str,
        *,
        phase: str,
        batch_artifact: TemporaryQwenBatchArtifact | None = None,
        distributed_artifact: DistributedSystemPlanOpportunityMapArtifact | None = None,
    ) -> None:
        self.phase = phase
        self.batch_artifact = batch_artifact
        self.distributed_artifact = distributed_artifact
        super().__init__(message)


class DistributedSystemPlanOpportunityMapArtifact(StrictFrozenModel):
    """Exact 14-call provenance plus deterministic opportunity/review assembly."""

    schema_version: Literal["distributed-system-plan-opportunity-map-v1"] = (
        "distributed-system-plan-opportunity-map-v1"
    )
    lineage_id: str = Field(min_length=1)
    routing_artifact_hash: Sha256
    routing_context_hash: Sha256
    feasibility_envelope: ResearchFeasibilityEnvelope
    method_skill_selection: SystemPlanMethodSkillSelectionBinding
    worker_bindings: tuple[OpportunityWorkerBinding, ...] = Field(min_length=7, max_length=7)
    stage_phase_binding: TemporaryQwenStagePhaseBinding
    author_phase_manifest: TemporaryQwenPhaseManifest
    author_batch: TemporaryQwenBatchArtifact
    opportunity_map: ResearchOpportunityMap
    opportunity_map_hash: Sha256
    reviewer_phase_manifest: TemporaryQwenPhaseManifest
    reviewer_batch: TemporaryQwenBatchArtifact
    review: ResearchOpportunityMapReview
    review_hash: Sha256
    accepted_cells: tuple[ResearchOpportunityCell, ...]
    authored_by_temporary_models: Literal[True] = True
    hand_written_scientific_prose_count: Literal[0] = 0
    all_runtime_identities_inactive: Literal[True] = True
    execution_authorized: Literal[False] = False
    is_scientific_evidence: Literal[False] = False
    approval_granted: Literal[False] = False
    release_authorized: Literal[False] = False
    independent_review_bypassed: Literal[False] = False
    created_at: datetime
    output_relative_path: Literal["system-plan-opportunity-distributed.json"] = (
        "system-plan-opportunity-distributed.json"
    )
    artifact_hash: Sha256

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise DistributedOpportunityPipelineError(
                "distributed opportunity timestamp must be UTC",
                phase="assembly",
            )
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _validate_artifact(
        self,
    ) -> DistributedSystemPlanOpportunityMapArtifact:
        binding_ids = tuple(item.route.cell_id for item in self.worker_bindings)
        if binding_ids != _CELL_IDS:
            raise ValueError("distributed worker bindings must cover O01..O07")
        if any(
            item.routing_artifact_hash != self.routing_artifact_hash
            or item.routing_context_hash != self.routing_context_hash
            for item in self.worker_bindings
        ):
            raise ValueError("distributed worker binding provenance mismatch")
        if (
            self.author_phase_manifest.phase_sequence_binding != self.stage_phase_binding
            or self.reviewer_phase_manifest.phase_sequence_binding != self.stage_phase_binding
        ):
            raise ValueError("distributed phases do not share one stage binding")
        if (
            self.author_phase_manifest.phase_id != _AUTHOR_PHASE
            or self.author_phase_manifest.phase_index != 1
            or not self.author_phase_manifest.capability_retained_for_next_phase
            or self.author_phase_manifest.capability_finalized
        ):
            raise ValueError("distributed author phase is not a non-final phase")
        if (
            self.reviewer_phase_manifest.phase_id != _REVIEWER_PHASE
            or self.reviewer_phase_manifest.phase_index != 2
            or not self.reviewer_phase_manifest.capability_finalized
            or not self.reviewer_phase_manifest.phase_sequence_completed
        ):
            raise ValueError("distributed reviewer phase is not terminal")
        for phase_manifest, batch in (
            (self.author_phase_manifest, self.author_batch),
            (self.reviewer_phase_manifest, self.reviewer_batch),
        ):
            if (
                phase_manifest.batch_artifact_hash != batch.artifact_hash
                or phase_manifest.batch_artifact_relative_path != batch.output_relative_path
            ):
                raise ValueError("distributed phase/batch binding mismatch")
            if batch.dispatched_count != 7 or batch.failed_count != 0:
                raise ValueError("distributed phase must contain seven successes")
        if (
            self.author_batch.controller_binding_hash
            != self.stage_phase_binding.controller_binding_hash
            or self.reviewer_batch.controller_binding_hash
            != self.stage_phase_binding.controller_binding_hash
        ):
            raise ValueError("distributed batches changed stage controller")
        author_runtime_ids = {item.temporary_agent_id for item in self.author_batch.task_records}
        reviewer_runtime_ids = {
            item.temporary_agent_id for item in self.reviewer_batch.task_records
        }
        if author_runtime_ids & reviewer_runtime_ids:
            raise ValueError("distributed reviewer reused an author runtime identity")
        cells = _cells_from_batch(self.author_batch, self.worker_bindings)
        if self.opportunity_map.opportunities != cells:
            raise ValueError("distributed opportunity map changed author outputs")
        assessments = _assessments_from_batch(self.reviewer_batch, self.worker_bindings)
        if self.review.assessments != assessments:
            raise ValueError("distributed review changed reviewer outputs")
        expected_accepted = tuple(
            cell for cell in cells if cell.cell_id in self.review.accepted_cell_ids
        )
        if self.accepted_cells != expected_accepted:
            raise ValueError("distributed accepted cells differ from strict gates")
        if self.opportunity_map_hash != canonical_sha256(
            self.opportunity_map.model_dump(mode="json")
        ):
            raise ValueError("distributed opportunity map hash mismatch")
        if self.review_hash != canonical_sha256(self.review.model_dump(mode="json")):
            raise ValueError("distributed opportunity review hash mismatch")
        expected_hash = canonical_sha256(self.model_dump(mode="json", exclude={"artifact_hash"}))
        if self.artifact_hash != expected_hash:
            raise ValueError("distributed opportunity artifact hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> DistributedSystemPlanOpportunityMapArtifact:
        payload = dict(values)
        unhashed = cls.model_construct(**payload, artifact_hash="0" * 64)
        payload["artifact_hash"] = canonical_sha256(
            unhashed.model_dump(mode="json", exclude={"artifact_hash"})
        )
        return cls.model_validate(payload)

    def binding(self) -> ResearchOpportunityMapBinding:
        """Return the existing ideation input type only after strict acceptance."""

        if not self.review.map_ready or not self.accepted_cells:
            raise DistributedOpportunityPipelineError(
                "distributed opportunity map has no strictly accepted cell",
                phase="assembly",
                distributed_artifact=self,
            )
        return ResearchOpportunityMapBinding(
            opportunity_map_hash=self.artifact_hash,
            feasibility_envelope=self.feasibility_envelope,
            accepted_cells=self.accepted_cells,
            method_skill_selection=self.method_skill_selection,
        )


def run_distributed_system_plan_opportunity_map(
    *,
    routing_artifact: SystemPlanOpportunityRoutingArtifact,
    controller: StageControllerBinding,
    capability: StageDispatchCapability,
    output_dir: Path | str,
    author_completion: CompletionCallable = run_llm_json_completion,
    reviewer_completion: CompletionCallable = run_llm_json_completion,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    max_workers: int = 7,
    thinking_budget: int = 4_000,
    temperature: float = 0.2,
    clock: datetime | None = None,
) -> DistributedSystemPlanOpportunityMapArtifact:
    """Run seven independent authors, then seven distinct independent reviewers."""

    capability.require_valid(controller)
    if controller.lineage_id != routing_artifact.lineage_id:
        capability.revoke()
        raise DistributedOpportunityPipelineError(
            "stage controller lineage differs from routing artifact",
            phase="preflight",
        )
    if controller.stage_input_hash != routing_artifact.artifact_hash:
        capability.revoke()
        raise DistributedOpportunityPipelineError(
            "stage controller input hash is not the routing artifact",
            phase="preflight",
        )
    if controller.max_parallel_agents < 7 or not 1 <= max_workers <= 7:
        capability.revoke()
        raise DistributedOpportunityPipelineError(
            "distributed opportunity stage requires bounded capacity for seven workers",
            phase="preflight",
        )
    output_root = Path(output_dir).resolve()
    now = clock or datetime.now(timezone.utc)
    try:
        output_root.mkdir(parents=True, exist_ok=True)
        worker_bindings = routing_artifact.worker_bindings()
        skill_contexts = _skill_contexts(worker_bindings[0])
        session = TemporaryQwenStagePhaseSession(
            sequence_id=(f"opportunity-distributed-{routing_artifact.artifact_hash[:24]}"),
            controller=controller,
            capability=capability,
            phase_ids=(_AUTHOR_PHASE, _REVIEWER_PHASE),
            created_at=now,
        )
    except Exception as exc:
        capability.revoke()
        raise DistributedOpportunityPipelineError(
            f"distributed opportunity preflight failed: {exc}",
            phase="preflight",
        ) from exc
    phase_marker = _AUTHOR_PHASE
    try:
        with session:
            author_tasks = tuple(
                _author_task(binding, skill_contexts) for binding in worker_bindings
            )
            try:
                author_batch = run_temporary_qwen_content_batch(
                    batch_id=f"opportunity-authors-{routing_artifact.artifact_hash[:24]}",
                    controller=controller,
                    capability=capability,
                    tasks=author_tasks,
                    output_dir=output_root,
                    completion=author_completion,
                    config_path=config_path,
                    env_path=env_path,
                    max_workers=max_workers,
                    thinking_budget=thinking_budget,
                    temperature=temperature,
                    clock=now,
                    phase_session=session,
                    phase_id=_AUTHOR_PHASE,
                )
            except TemporaryQwenBatchError as exc:
                raise DistributedOpportunityPipelineError(
                    "distributed opportunity author phase failed after archival",
                    phase=_AUTHOR_PHASE,
                    batch_artifact=exc.artifact,
                ) from exc
            author_phase = session.phase_manifest(_AUTHOR_PHASE)
            cells = _cells_from_batch(author_batch, worker_bindings)
            opportunity_map = ResearchOpportunityMap(opportunities=cells)
            reviewer_tasks = tuple(
                _reviewer_task(binding, cell, author_batch, skill_contexts)
                for binding, cell in zip(worker_bindings, cells, strict=True)
            )
            phase_marker = _REVIEWER_PHASE
            try:
                reviewer_batch = run_temporary_qwen_content_batch(
                    batch_id=f"opportunity-reviewers-{routing_artifact.artifact_hash[:24]}",
                    controller=controller,
                    capability=capability,
                    tasks=reviewer_tasks,
                    output_dir=output_root,
                    completion=reviewer_completion,
                    config_path=config_path,
                    env_path=env_path,
                    max_workers=max_workers,
                    thinking_budget=thinking_budget,
                    temperature=temperature,
                    clock=now,
                    phase_session=session,
                    phase_id=_REVIEWER_PHASE,
                )
            except TemporaryQwenBatchError as exc:
                raise DistributedOpportunityPipelineError(
                    "distributed opportunity reviewer phase failed after archival",
                    phase=_REVIEWER_PHASE,
                    batch_artifact=exc.artifact,
                ) from exc
            reviewer_phase = session.phase_manifest(_REVIEWER_PHASE)
            assessments = _assessments_from_batch(reviewer_batch, worker_bindings)
            accepted_ids = tuple(item.cell_id for item in assessments if item.qualifies())
            review = ResearchOpportunityMapReview(
                assessments=assessments,
                accepted_cell_ids=accepted_ids,
                review_summary=(
                    "机器仅按七份独立逐格评审的七项布尔门禁汇总："
                    f"通过{len(accepted_ids)}格，拒绝{7 - len(accepted_ids)}格；"
                    "未增加、删除或改写任何科学判断。"
                ),
                map_ready=bool(accepted_ids),
            )
    except DistributedOpportunityPipelineError:
        raise
    except Exception as exc:
        raise DistributedOpportunityPipelineError(
            f"distributed opportunity pipeline failed closed: {exc}",
            phase=phase_marker,
        ) from exc

    accepted_cells = tuple(cell for cell in cells if cell.cell_id in review.accepted_cell_ids)
    artifact = DistributedSystemPlanOpportunityMapArtifact.create(
        schema_version="distributed-system-plan-opportunity-map-v1",
        lineage_id=routing_artifact.lineage_id,
        routing_artifact_hash=routing_artifact.artifact_hash,
        routing_context_hash=routing_artifact.compact_routing_context.context_hash,
        feasibility_envelope=routing_artifact.feasibility_envelope,
        method_skill_selection=routing_artifact.method_skill_selection,
        worker_bindings=worker_bindings,
        stage_phase_binding=session.binding,
        author_phase_manifest=author_phase,
        author_batch=author_batch,
        opportunity_map=opportunity_map,
        opportunity_map_hash=canonical_sha256(opportunity_map.model_dump(mode="json")),
        reviewer_phase_manifest=reviewer_phase,
        reviewer_batch=reviewer_batch,
        review=review,
        review_hash=canonical_sha256(review.model_dump(mode="json")),
        accepted_cells=accepted_cells,
        created_at=now,
        output_relative_path=_OUTPUT_NAME,
    )
    _write_immutable(output_root, artifact)
    if not review.map_ready:
        raise DistributedOpportunityPipelineError(
            "all distributed opportunity cells failed independent review",
            phase="assembly",
            distributed_artifact=artifact,
        )
    return artifact


def _skill_contexts(
    binding: OpportunityWorkerBinding,
) -> tuple[TemporaryQwenSkillContext, ...]:
    return tuple(
        TemporaryQwenSkillContext(
            skill_ref=TemporaryAgentSkillRef(
                skill_id=skill.skill_id,
                source_ref=skill.source_relative_path,
                content_sha256=skill.content_sha256,
            ),
            content=skill.content,
        )
        for skill in binding.method_skill_selection.selected_skills
    )


def _binding_payload(binding: OpportunityWorkerBinding) -> dict[str, Any]:
    """Project one complete routed fact bundle while keeping SKILL bytes separate."""

    return {
        "schema_version": binding.schema_version,
        "binding_hash": binding.binding_hash,
        "routing_artifact_hash": binding.routing_artifact_hash,
        "feasibility_envelope_hash": binding.feasibility_envelope_hash,
        "routing_context_hash": binding.routing_context_hash,
        "route": binding.route.model_dump(mode="json"),
        "evidence_facts": [
            _worker_evidence_fact_view(
                item.model_dump(mode="json"),
                target_systems=binding.route.target_systems,
            )
            for item in binding.evidence_facts
        ],
        "literature_records": [item.model_dump(mode="json") for item in binding.literature_records],
        "component_source": binding.component_source.model_dump(mode="json"),
        "frozen_budget": _worker_budget_view(binding.frozen_budget),
        "method_skill_selection_ref": {
            "selection_artifact_hash": (binding.method_skill_selection.selection_artifact_hash),
            "selected_skill_ids": list(binding.method_skill_selection.selection.selected_skill_ids),
            "selected_skill_content_hashes": [
                item.content_sha256 for item in binding.method_skill_selection.selected_skills
            ],
        },
        "is_scientific_evidence": False,
        "execution_authorized": False,
    }


def _model_task_binding_payload(
    binding: OpportunityWorkerBinding,
) -> dict[str, Any]:
    """Keep every scientific value while avoiding repeated commitment metadata.

    The immutable input refs already carry both the complete routing-artifact hash
    and the complete worker-binding hash.  Repeating per-fact hashes, intermediate
    context hashes, a closed-vocabulary routing rationale, and SKILL hashes inside
    the model-facing JSON adds no scientific information.  The independently
    supplied SKILL system messages retain their own exact identifiers and hashes.
    """

    complete = _binding_payload(binding)
    route = complete["route"]
    if not isinstance(route, Mapping):
        raise ValueError("worker route projection is not an object")
    task_facts: list[dict[str, Any]] = []
    for fact in complete["evidence_facts"]:
        if not isinstance(fact, Mapping):
            raise ValueError("worker evidence projection is not an object")
        task_fact = dict(fact)
        task_fact.pop("full_fact_sha256", None)
        task_facts.append(task_fact)
    return {
        "binding_hash": binding.binding_hash,
        "route": {key: route[key] for key in _TASK_ROUTE_KEYS},
        "evidence_facts": task_facts,
        "literature_records": complete["literature_records"],
        "component_source": complete["component_source"],
        "frozen_budget": complete["frozen_budget"],
        "is_scientific_evidence": False,
        "execution_authorized": False,
    }


def _compact_expected_output_schema(
    model: type[StrictFrozenModel],
) -> dict[str, Any]:
    """Remove JSON-Schema annotations without changing validation semantics."""

    def without_annotations(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                str(key): without_annotations(item)
                for key, item in value.items()
                if key not in _JSON_SCHEMA_ANNOTATION_KEYS
            }
        if isinstance(value, list):
            return [without_annotations(item) for item in value]
        return value

    compact = without_annotations(model.model_json_schema())
    if not isinstance(compact, dict):
        raise ValueError("compact response schema is not an object")
    return compact


def _reviewer_cell_payload(cell: ResearchOpportunityCell) -> dict[str, Any]:
    """Retain scientific prose once; route-bound copies were already validated."""

    content = cell.model_dump(mode="json")
    for field_name in (
        "cell_id",
        "evidence_fact_ids",
        "literature_indices",
        "eligible_target_systems",
    ):
        content.pop(field_name)
    trace = content.get("method_application_trace")
    if not isinstance(trace, dict):
        raise ValueError("opportunity method trace is not an object")
    trace.pop("verified_fact_ids")
    trace.pop("closest_prior_reference_indices")
    return {
        "full_cell_sha256": canonical_sha256(cell.model_dump(mode="json")),
        "route_bound_copies_prevalidated": True,
        "scientific_content": content,
    }


def _worker_evidence_fact_view(
    fact: dict[str, Any], *, target_systems: Sequence[str]
) -> dict[str, Any]:
    """Project only routed rows from a large matrix while binding the full fact."""

    fact_kind = fact.get("fact_kind")
    if fact_kind in {"data_profile", "system_effect"}:
        value = fact.get("value")
        if not isinstance(value, Mapping):
            raise ValueError(f"{fact_kind} fact value is not an object")
        keys = (
            _DATA_PROFILE_WORKER_KEYS if fact_kind == "data_profile" else _SYSTEM_EFFECT_WORKER_KEYS
        )
        return {
            "fact_id": fact.get("fact_id"),
            "fact_kind": fact_kind,
            "full_fact_sha256": canonical_sha256(fact),
            "value": {key: value[key] for key in keys if key in value},
        }
    if fact_kind != "cross_lineage_effect_matrix":
        return fact
    value = fact.get("value")
    if not isinstance(value, Mapping):
        raise ValueError("cross-lineage matrix fact value is not an object")
    candidates = value.get("candidates")
    rows = value.get("comparable_system_rows")
    coverage_ledger = value.get("coverage_ledger")
    if (
        not isinstance(candidates, list)
        or not isinstance(rows, list)
        or not isinstance(coverage_ledger, list)
    ):
        raise ValueError("cross-lineage matrix lacks candidates, rows, or coverage")
    candidate_refs: list[dict[str, Any]] = []
    candidate_lineages: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise ValueError("cross-lineage matrix candidate is not an object")
        lineage_id = str(candidate.get("lineage_id") or "")
        package_hash = str(candidate.get("package_hash") or "")
        selected_candidate_id = str(candidate.get("selected_candidate_id") or "")
        if not lineage_id or not package_hash or not selected_candidate_id:
            raise ValueError("cross-lineage matrix candidate identity is incomplete")
        candidate_lineages.append(lineage_id)
        candidate_refs.append(
            {
                "lineage_id": lineage_id,
                "package_hash": package_hash,
                "selected_candidate_id": selected_candidate_id,
            }
        )
    if len(set(candidate_lineages)) != len(candidate_lineages):
        raise ValueError("cross-lineage matrix candidate lineages repeat")
    rows_by_system: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("cross-lineage matrix row is not an object")
        system_name = str(row.get("system_name") or "")
        if system_name in target_systems:
            rows_by_system[system_name] = dict(row)
    if set(rows_by_system) != set(target_systems):
        raise ValueError("cross-lineage matrix does not cover every routed target")
    projected_rows = [rows_by_system[name] for name in target_systems]
    for row in projected_rows:
        observations = row.get("observations")
        if (
            not isinstance(observations, list)
            or [
                str(item.get("lineage_id") or "")
                for item in observations
                if isinstance(item, Mapping)
            ]
            != candidate_lineages
        ):
            raise ValueError("cross-lineage projected row does not retain every candidate")
    projected_value = {
        "schema_version": value.get("schema_version"),
        "matrix_hash": value.get("matrix_hash"),
        "comparability_rule": value.get("comparability_rule"),
        "candidate_differences_jointly_confounded": value.get(
            "candidate_differences_jointly_confounded"
        ),
        "component_attribution_authorized": value.get("component_attribution_authorized"),
        "confirmatory_use_requires_model_authored_component_ablation": value.get(
            "confirmatory_use_requires_model_authored_component_ablation"
        ),
        "candidate_records_sha256": canonical_sha256(candidates),
        "coverage_ledger_sha256": canonical_sha256(coverage_ledger),
        "candidate_refs": candidate_refs,
        "comparable_system_rows": projected_rows,
    }
    return {
        "fact_id": fact.get("fact_id"),
        "fact_kind": fact.get("fact_kind"),
        "scope": fact.get("scope"),
        "source_locator": fact.get("source_locator"),
        "full_fact_sha256": canonical_sha256(fact),
        "projection_rule": (
            "保留路由指定全部目标系统、每个目标的全部候选观测及完整矩阵哈希；"
            "候选元数据与覆盖账本只下发哈希，完整事实由 worker binding 哈希保留"
        ),
        "value": projected_value,
    }


def _worker_budget_view(budget: Mapping[str, Any]) -> dict[str, Any]:
    """Expose resource and estimand limits without repeated archival metadata."""

    def selected(section_name: str, keys: Sequence[str]) -> dict[str, Any]:
        section = budget.get(section_name)
        if not isinstance(section, Mapping):
            return {}
        return {key: section[key] for key in keys if key in section}

    stage_breadth = selected("stage_breadth", _STAGE_BREADTH_WORKER_KEYS)
    full_stage_breadth = budget.get("stage_breadth")
    if isinstance(full_stage_breadth, Mapping) and full_stage_breadth.get("power_cost_statement"):
        stage_breadth["power_cost_statement_sha256"] = canonical_sha256(
            full_stage_breadth["power_cost_statement"]
        )
    return {
        "full_budget_sha256": canonical_sha256(dict(budget)),
        "conditions": budget.get("conditions"),
        "seeds": budget.get("seeds"),
        "estimand": selected("estimand", _ESTIMAND_WORKER_KEYS),
        "official_development_cell_budget": budget.get("official_development_cell_budget"),
        "search_budget": selected("search_budget", _SEARCH_BUDGET_WORKER_KEYS),
        "stage_breadth": stage_breadth,
    }


def _author_task(
    binding: OpportunityWorkerBinding,
    skill_contexts: tuple[TemporaryQwenSkillContext, ...],
) -> TemporaryQwenContentTask:
    cell_id = binding.route.cell_id
    return TemporaryQwenContentTask(
        dispatch_id=f"opportunity-author-{cell_id}",
        temporary_agent_id=f"temporary-opportunity-author-{cell_id}",
        parent_task_id="distributed-opportunity-authoring",
        task_kind=TemporaryAgentTaskKind.OPPORTUNITY_MEMO,
        task_instruction=(
            "仅根据短任务输入中的派工绑定生成一个研究机会格；所有编号、目标、"
            "事实与文献必须逐字段一致。evidence_fact_ids 与 method_application_trace."
            "verified_fact_ids 都必须完整、同序逐字复制 route.evidence_fact_ids，不能"
            "只列实际引用的子集；literature_indices 与 method_application_trace."
            "closest_prior_reference_indices 同样必须完整、同序逐字复制 route."
            "literature_indices。method_application_trace.changed_component 必须逐字"
            "复制 route.single_component_assignment。中文叙述字段不要重复英文系统名、"
            "谱系标识或英文 Schema 字段名：这些只放在专用结构化字段中；必须提及时用"
            "‘目标系统’‘实验条件’‘随机种子’‘估计目标’‘自助法’等中文表述。除方法"
            "缩写和不可改标识外，每个叙述字段的汉字必须多于拉丁字母。不得补充输入外"
            "事实或执行任何实验。"
        ),
        input_refs=(
            TemporaryAgentInputRef(
                artifact_id="opportunity-routing-artifact",
                source_ref="system-plan-opportunity-routing.json",
                sha256=binding.routing_artifact_hash,
            ),
            TemporaryAgentInputRef(
                artifact_id=f"opportunity-worker-binding-{cell_id}",
                source_ref=f"system-plan-opportunity-routing.json#worker/{cell_id}",
                sha256=binding.binding_hash,
            ),
        ),
        input_payload={"worker_binding": _model_task_binding_payload(binding)},
        expected_output_schema=_compact_expected_output_schema(ResearchOpportunityCell),
        chinese_output_fields=_AUTHOR_CHINESE_FIELDS,
        skill_contexts=skill_contexts,
        max_tokens=18_000,
        timeout_seconds=600,
    )


def _reviewer_task(
    binding: OpportunityWorkerBinding,
    cell: ResearchOpportunityCell,
    author_batch: TemporaryQwenBatchArtifact,
    skill_contexts: tuple[TemporaryQwenSkillContext, ...],
) -> TemporaryQwenContentTask:
    author_output = next(
        item
        for item in author_batch.stable_outputs
        if item.dispatch_id == f"opportunity-author-{cell.cell_id}"
    )
    return TemporaryQwenContentTask(
        dispatch_id=f"opportunity-review-{cell.cell_id}",
        temporary_agent_id=f"temporary-opportunity-reviewer-{cell.cell_id}",
        parent_task_id="distributed-opportunity-review",
        task_kind=TemporaryAgentTaskKind.ADVERSARIAL_CRITIQUE,
        task_instruction=(
            "仅根据短任务输入中的派工绑定与他人生成的机会格独立执行七项硬门禁；"
            "机会格中已由编排器逐字核验的编号、目标和文献机械副本不重复下发，"
            "但完整机会格哈希仍被绑定；必须核对 scientific_content."
            "method_application_trace.changed_component 是否逐字等于 route 的单组件"
            "派工，并从 route 完整"
            "复制 supporting_fact_ids 与 supporting_literature_indices；不得自审、"
            "补写机会或放宽证据、预算、安全和审批边界。critical_findings 只能"
            "记录导致某项硬门禁为 false 的中文关键问题：七项硬门禁全部为 true 时"
            "必须返回空列表，不得把通过理由写入其中；任一硬门禁为 false 时必须"
            "返回至少一条与该失败门对应的中文关键问题。"
        ),
        input_refs=(
            TemporaryAgentInputRef(
                artifact_id=f"opportunity-worker-binding-{cell.cell_id}",
                source_ref=("system-plan-opportunity-routing.json#worker/" f"{cell.cell_id}"),
                sha256=binding.binding_hash,
            ),
            TemporaryAgentInputRef(
                artifact_id=f"opportunity-author-result-{cell.cell_id}",
                source_ref=(f"{author_batch.output_relative_path}#result/{cell.cell_id}"),
                sha256=author_output.result_hash,
            ),
        ),
        input_payload={
            "worker_binding": _model_task_binding_payload(binding),
            "opportunity_cell": _reviewer_cell_payload(cell),
        },
        expected_output_schema=_compact_expected_output_schema(OpportunityCellAssessment),
        chinese_output_fields=("critical_findings",),
        skill_contexts=skill_contexts,
        max_tokens=5_000,
        timeout_seconds=600,
    )


def _cells_from_batch(
    batch: TemporaryQwenBatchArtifact,
    bindings: Sequence[OpportunityWorkerBinding],
) -> tuple[ResearchOpportunityCell, ...]:
    expected_dispatches = tuple(f"opportunity-author-{item.route.cell_id}" for item in bindings)
    if tuple(item.dispatch_id for item in batch.stable_outputs) != expected_dispatches:
        raise ValueError("author outputs do not cover routed cells in stable order")
    cells: list[ResearchOpportunityCell] = []
    for output, binding in zip(batch.stable_outputs, bindings, strict=True):
        route = binding.route
        payload = json.loads(json.dumps(output.output_payload, ensure_ascii=False, allow_nan=False))
        if not isinstance(payload, dict):
            raise ValueError(f"{route.cell_id} author output is not an object")
        raw_cell_id = payload.get("cell_id")
        if raw_cell_id is not None and raw_cell_id != route.cell_id:
            raise ValueError(f"{route.cell_id} author changed its cell identity")
        payload["cell_id"] = route.cell_id
        for field_name, expected in (
            ("evidence_fact_ids", route.evidence_fact_ids),
            ("literature_indices", route.literature_indices),
            ("eligible_target_systems", route.target_systems),
        ):
            # These are route-owned provenance coordinates, not scientific choices.
            # Qwen may omit them or render schema placeholders; the orchestrator
            # always projects the already-frozen route instead of asking the model
            # to reproduce machine metadata.
            payload[field_name] = list(expected)
        trace = payload.get("method_application_trace")
        if not isinstance(trace, dict):
            raise ValueError(f"{route.cell_id} author omitted its method trace")
        for field_name, expected in (
            ("verified_fact_ids", route.evidence_fact_ids),
            ("closest_prior_reference_indices", route.literature_indices),
        ):
            trace[field_name] = list(expected)
        cell = ResearchOpportunityCell.model_validate(payload)
        if cell.method_application_trace.changed_component != route.single_component_assignment:
            raise ValueError(f"{route.cell_id} author output escaped its route binding")
        cells.append(cell)
    return tuple(cells)


def _assessments_from_batch(
    batch: TemporaryQwenBatchArtifact,
    bindings: Sequence[OpportunityWorkerBinding],
) -> tuple[OpportunityCellAssessment, ...]:
    expected_dispatches = tuple(f"opportunity-review-{item.route.cell_id}" for item in bindings)
    if tuple(item.dispatch_id for item in batch.stable_outputs) != expected_dispatches:
        raise ValueError("review outputs do not cover routed cells in stable order")
    assessments: list[OpportunityCellAssessment] = []
    for output, binding in zip(batch.stable_outputs, bindings, strict=True):
        route = binding.route
        payload = json.loads(json.dumps(output.output_payload, ensure_ascii=False, allow_nan=False))
        if not isinstance(payload, dict):
            raise ValueError(f"{route.cell_id} reviewer output is not an object")
        raw_cell_id = payload.get("cell_id")
        if raw_cell_id is not None and raw_cell_id != route.cell_id:
            raise ValueError(f"{route.cell_id} reviewer output escaped its route binding")
        payload["cell_id"] = route.cell_id
        for field_name, expected in (
            ("supporting_fact_ids", route.evidence_fact_ids),
            ("supporting_literature_indices", route.literature_indices),
        ):
            # Reviewer prose and gate decisions remain model-authored; the route
            # evidence coordinates are deterministically attached by the stage.
            payload[field_name] = list(expected)
        assessment = OpportunityCellAssessment.model_validate(payload)
        assessments.append(assessment)
    return tuple(assessments)


def _write_immutable(
    output_root: Path,
    artifact: DistributedSystemPlanOpportunityMapArtifact,
) -> Path:
    target = (output_root / _OUTPUT_NAME).resolve()
    target.relative_to(output_root)
    payload = artifact.model_dump(mode="json")
    if target.exists():
        if not target.is_file():
            raise DistributedOpportunityPipelineError(
                "distributed opportunity output path is not a file",
                phase="assembly",
            )
        existing = json.loads(target.read_text(encoding="utf-8"))
        if existing != payload:
            raise DistributedOpportunityPipelineError(
                "refusing to overwrite a different distributed opportunity artifact",
                phase="assembly",
            )
        return target
    return write_json_model(target, payload)


__all__ = [
    "DistributedOpportunityPipelineError",
    "DistributedSystemPlanOpportunityMapArtifact",
    "run_distributed_system_plan_opportunity_map",
]
