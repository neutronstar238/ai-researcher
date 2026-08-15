"""Generic complete fixtures for the scientific-cycle validation bridge."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import cast

from pydantic import JsonValue

from autoresearch.kernel import (
    Activity,
    ActivityKind,
    Agent,
    Association,
    Claim,
    ContentAddressedRef,
    ContextPolicy,
    CostPolicy,
    Counterevidence,
    Decision,
    Entity,
    EntityKind,
    EntropyInterventionPolicy,
    EnvironmentOutcome,
    EpisodeCostRecord,
    EpisodeEvaluationProjection,
    EpisodeOutcomeStatus,
    EpisodePackage,
    EvaluationPolicy,
    EvaluationReport,
    EvaluationTaskRecord,
    EvaluationVerdict,
    Evidence,
    EvidenceDirection,
    FailureAttributionPolicy,
    FaultMatrixRunner,
    Generation,
    GraderIndependence,
    GraderKind,
    GraderResult,
    GraderSpec,
    HarnessSpec,
    HoldoutAccessStage,
    HoldoutState,
    HypothesisAssessment,
    HypothesisAssessmentRecord,
    JsonFieldType,
    LocalRegressionRunner,
    LoopBudgetPolicy,
    LoopEdgeKind,
    LoopEdgeSpec,
    LoopGuardKind,
    LoopGuardSpec,
    LoopHoldoutPolicy,
    LoopNodeKind,
    LoopNodeOutcome,
    LoopNodeSpec,
    LoopPermissionPolicy,
    LoopRunSnapshot,
    LoopRunState,
    LoopRunStatus,
    LoopSpec,
    LoopUsage,
    MemoryPolicy,
    ModelPolicy,
    ObservabilityPolicy,
    PermissionPolicy,
    Plan,
    PromotionPolicy,
    ProvenanceAgentKind,
    ProvenanceBinding,
    ProvenanceBundle,
    RegressionCase,
    RegressionDimension,
    ResearchEvaluation,
    ResearchHypothesis,
    ResearchObservation,
    ResearchProblem,
    RubricCriterion,
    RubricRecord,
    ScientificCycleSnapshot,
    ScientificIntervention,
    SourceSnapshot,
    StatePolicy,
    StepOutcome,
    StructuredField,
    StructuredOutputContract,
    TaskContract,
    ToolPolicy,
    TrajectoryKind,
    TrajectoryStep,
    TrialRecord,
    UnifiedEvaluationEngine,
    Usage,
    Validation,
    VerificationPolicy,
    canonical_sha256,
    default_agentic_fault_cases,
    evaluation_subject_hash,
    project_episode_for_evaluation,
    scientific_record_semantic_hash,
)
from autoresearch.schemas import ValidationStatus

BASE_TIME = datetime(2026, 8, 14, 2, 0, tzinfo=timezone.utc)
ZERO_HASH = "0" * 64
TASK_ID = "task.cycle.validation"
PROTOCOL_HASH = canonical_sha256("protocol.plan")


@dataclass(frozen=True)
class ScientificCycleValidationFixture:
    """All exact objects consumed by one successful bridge validation."""

    cycle: ScientificCycleSnapshot
    provenance_bundle: ProvenanceBundle
    harness_spec: HarnessSpec
    loop_spec: LoopSpec
    episodes: tuple[EpisodePackage, ...]
    loop_snapshots: tuple[LoopRunSnapshot, ...]
    evaluation_report: EvaluationReport


def build_scientific_cycle_validation_fixture(
    grader_independence: GraderIndependence = GraderIndependence.INDEPENDENT,
    omit_loop_binding_key: str | None = None,
    assessment: HypothesisAssessment = HypothesisAssessment.SUPPORTED,
    evidence_validation_status: ValidationStatus = ValidationStatus.PASSED,
) -> ScientificCycleValidationFixture:
    """Build one complete, provider-neutral, three-repeat validation fixture."""

    if assessment not in {
        HypothesisAssessment.SUPPORTED,
        HypothesisAssessment.CONTRADICTED,
    }:
        raise ValueError("the complete fixture requires a decisive assessment")

    harness = _build_harness_spec()
    loop_spec = _build_loop_spec()
    episodes = tuple(_build_episode(harness, index) for index in range(1, 4))
    loop_snapshots = tuple(
        _build_loop_snapshot(
            loop_spec,
            episode,
            index,
            omit_binding_key=omit_loop_binding_key,
        )
        for index, episode in enumerate(episodes, start=1)
    )
    provisional_report = _build_evaluation_report(
        harness,
        episodes,
        loop_snapshots,
        evidence_bundle_hash=ZERO_HASH,
        grader_independence=grader_independence,
    )
    provisional = _build_cycle_records(
        bundle_hash=ZERO_HASH,
        harness=harness,
        loop_spec=loop_spec,
        report=provisional_report,
        assessment=assessment,
    )
    bundle = _build_provenance_bundle(
        provisional,
        episodes,
        provisional_report,
        assessment=assessment,
        evidence_validation_status=evidence_validation_status,
    )
    report = _build_evaluation_report(
        harness,
        episodes,
        loop_snapshots,
        evidence_bundle_hash=bundle.bundle_hash,
        grader_independence=grader_independence,
    )
    if evaluation_subject_hash(report) != evaluation_subject_hash(provisional_report):
        raise AssertionError("binding the evidence bundle changed the evaluation subject")
    records = _build_cycle_records(
        bundle_hash=bundle.bundle_hash,
        harness=harness,
        loop_spec=loop_spec,
        report=report,
        assessment=assessment,
    )
    if any(
        scientific_record_semantic_hash(cast(ScientificRecord, before))
        != scientific_record_semantic_hash(cast(ScientificRecord, after))
        for before, after in zip(provisional, records, strict=True)
    ):
        raise AssertionError("binding the exact bundle changed lifecycle semantics")

    observation, problem, hypothesis, intervention, evaluation = records
    cycle = ScientificCycleSnapshot.create(
        cycle_id="cycle.validation.fixture",
        version=1,
        observations=[observation],
        problems=[problem],
        hypotheses=[hypothesis],
        interventions=[intervention],
        evaluations=[evaluation],
    )
    return ScientificCycleValidationFixture(
        cycle=cycle,
        provenance_bundle=bundle,
        harness_spec=harness,
        loop_spec=loop_spec,
        episodes=episodes,
        loop_snapshots=loop_snapshots,
        evaluation_report=report,
    )


def _build_harness_spec() -> HarnessSpec:
    task = TaskContract(
        policy_id="policy.task.fixture",
        version="1",
        task_id=TASK_ID,
        instructions="Produce one bounded, schema-valid local record.",
        output_contract=StructuredOutputContract(
            fields=[
                StructuredField(name="replicate", value_type=JsonFieldType.INTEGER),
                StructuredField(name="status", value_type=JsonFieldType.STRING),
            ]
        ),
        success_criteria=["The local record satisfies the frozen output contract."],
        forbidden_actions=["Do not access an external service."],
        stop_conditions=["Stop after one bounded record."],
    )
    return HarnessSpec.create(
        spec_id="harness.cycle.validation",
        version="1",
        task_contract=task,
        context_policy=ContextPolicy(
            policy_id="policy.context.fixture",
            version="1",
            allowed_source_ids=["source.fixture"],
            max_context_tokens=256,
            max_context_bytes=2048,
        ),
        model_policy=ModelPolicy(
            policy_id="policy.model.fixture",
            version="1",
            adapter_id="adapter.fixture",
            model_ref="model.fixture",
            required_capabilities=["structured_output"],
            max_output_tokens=64,
            temperature=0.0,
            deliberation="disabled",
        ),
        tool_policy=ToolPolicy(
            policy_id="policy.tools.fixture",
            version="1",
            max_tool_calls=0,
        ),
        memory_policy=MemoryPolicy(
            policy_id="policy.memory.fixture",
            version="1",
            allowed_vault_prefixes=["projects/fixture"],
        ),
        state_policy=StatePolicy(
            policy_id="policy.state.fixture",
            version="1",
            max_mutable_state_bytes=2048,
        ),
        permission_policy=PermissionPolicy(
            policy_id="policy.permission.fixture",
            version="1",
        ),
        verification_policy=VerificationPolicy(
            policy_id="policy.verification.fixture",
            version="1",
            required_grader_ids=["agent.grader"],
            require_output_artifact_hashes=False,
        ),
        observability_policy=ObservabilityPolicy(
            policy_id="policy.observability.fixture",
            version="1",
        ),
        failure_attribution_policy=FailureAttributionPolicy(
            policy_id="policy.failure.fixture",
            version="1",
        ),
        cost_policy=CostPolicy(
            policy_id="policy.cost.fixture",
            version="1",
            max_total_tokens=0,
            max_estimated_cost_usd=0.0,
            max_wall_time_seconds=10.0,
            max_tool_calls=0,
        ),
        entropy_intervention_policy=EntropyInterventionPolicy(
            policy_id="policy.entropy.fixture",
            version="1",
        ),
        evaluation_policy=EvaluationPolicy(
            policy_id="policy.evaluation.fixture",
            version="1",
            trial_count=1,
            graders=[
                GraderSpec(
                    grader_id="agent.grader",
                    version="1",
                    kind=GraderKind.DETERMINISTIC,
                    threshold=1.0,
                )
            ],
        ),
        change_prediction="The frozen contract produces an attributable local record.",
        evaluation_scope="One provider-neutral contract fixture.",
    )


def _build_episode(harness: HarnessSpec, index: int) -> EpisodePackage:
    started_at = BASE_TIME + timedelta(minutes=10 + index * 2)
    completed_at = started_at + timedelta(minutes=1)
    trial_id = f"trial.source.{index}"
    step_id = f"step.verify.{index}"
    output: dict[str, JsonValue] = {"replicate": index, "status": "accepted"}
    output_hash = canonical_sha256(output)
    return EpisodePackage.create(
        episode_id=f"episode.fixture.{index}",
        run_id=f"run.fixture.{index}",
        harness_spec_id=harness.spec_id,
        harness_spec_hash=harness.spec_hash,
        task_contract=harness.task_contract,
        task_input_hash=canonical_sha256({"replicate": index}),
        started_at=started_at,
        completed_at=completed_at,
        trials=[
            TrialRecord(
                trial_id=trial_id,
                sequence=1,
                status=EpisodeOutcomeStatus.SUCCEEDED,
                started_at=started_at,
                completed_at=completed_at,
                trajectory_step_ids=[step_id],
                grader_ids=["agent.grader"],
                cost_id=f"cost.episode.{index}",
                output_hash=output_hash,
            )
        ],
        trajectory=[
            TrajectoryStep(
                step_id=step_id,
                sequence=1,
                trial_id=trial_id,
                kind=TrajectoryKind.VERIFICATION,
                outcome=StepOutcome.SUCCEEDED,
                actor_id="agent.executor",
                occurred_at=completed_at,
                summary="A deterministic local verification completed.",
            )
        ],
        final_outcome=EnvironmentOutcome(
            status=EpisodeOutcomeStatus.SUCCEEDED,
            summary="The frozen local record was accepted.",
            structured_output=output,
            output_hash=output_hash,
        ),
        graders=[
            GraderResult(
                grader_id="agent.grader",
                grader_version="1",
                kind=GraderKind.DETERMINISTIC,
                score=1.0,
                passed=True,
                reason="The frozen contract was satisfied.",
            )
        ],
        costs=[
            EpisodeCostRecord(
                cost_id=f"cost.episode.{index}",
                trial_id=trial_id,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                estimated_cost_usd=0.0,
                cost_known=True,
                wall_time_seconds=0.01,
                tool_calls=0,
            )
        ],
        journal_terminal_event_id=f"event.episode.{index}.terminal",
        journal_terminal_event_hash=canonical_sha256(f"terminal:{index}"),
        journal_lineage_hash=canonical_sha256(f"lineage:{index}"),
        journal_seal_hash=canonical_sha256(f"seal:{index}"),
    )


def _build_loop_spec() -> LoopSpec:
    return LoopSpec.create(
        spec_id="loop.cycle.validation",
        version="1",
        graph_version=1,
        task_id=TASK_ID,
        entry_node_id="node.start",
        nodes=[
            LoopNodeSpec(
                node_id="node.start",
                version="1",
                kind=LoopNodeKind.START,
            ),
            LoopNodeSpec(
                node_id="node.action",
                version="1",
                kind=LoopNodeKind.ACTION,
                handler_id="handler.fixture",
            ),
            LoopNodeSpec(
                node_id="node.terminal",
                version="1",
                kind=LoopNodeKind.TERMINAL,
                terminal_status=LoopRunStatus.SUCCEEDED,
            ),
        ],
        edges=[
            LoopEdgeSpec(
                edge_id="edge.start.action",
                version="1",
                kind=LoopEdgeKind.NEXT,
                source_node_id="node.start",
                target_node_id="node.action",
                guards=[
                    LoopGuardSpec(
                        guard_id="guard.start.action",
                        kind=LoopGuardKind.ALWAYS,
                    )
                ],
            ),
            LoopEdgeSpec(
                edge_id="edge.action.terminal",
                version="1",
                kind=LoopEdgeKind.NEXT,
                source_node_id="node.action",
                target_node_id="node.terminal",
                guards=[
                    LoopGuardSpec(
                        guard_id="guard.action.succeeded",
                        kind=LoopGuardKind.OUTCOME,
                        outcomes=[LoopNodeOutcome.SUCCEEDED],
                    )
                ],
            ),
        ],
        budget_policy=LoopBudgetPolicy(
            policy_id="policy.loop.budget.fixture",
            version="1",
            max_steps=3,
            max_tokens=0,
            max_estimated_cost_usd=0.0,
            max_wall_time_seconds=10.0,
            max_tool_calls=0,
            max_total_retries=0,
            max_failures=0,
            max_human_interventions=0,
        ),
        permission_policy=LoopPermissionPolicy(
            policy_id="policy.loop.permission.fixture",
            version="1",
        ),
        holdout_policy=LoopHoldoutPolicy(
            policy_id="policy.loop.holdout.fixture",
            version="1",
        ),
    )


def _build_loop_snapshot(
    spec: LoopSpec,
    episode: EpisodePackage,
    index: int,
    *,
    omit_binding_key: str | None,
) -> LoopRunSnapshot:
    variables: dict[str, JsonValue] = {
        "harness_episode_id": episode.episode_id,
        "harness_episode_hash": episode.episode_hash,
        "harness_episode_status": episode.final_outcome.status.value,
        "harness_journal_lineage_hash": episode.journal_lineage_hash,
        "harness_journal_seal_hash": episode.journal_seal_hash,
        "harness_spec_hash": episode.harness_spec_hash,
    }
    if omit_binding_key is not None:
        variables.pop(omit_binding_key, None)
    state = LoopRunState(
        run_id=episode.run_id,
        task_id=TASK_ID,
        spec_id=spec.spec_id,
        spec_hash=spec.spec_hash,
        start_request_hash=canonical_sha256(f"start:{index}"),
        revision=1,
        status=LoopRunStatus.SUCCEEDED,
        current_node_id=None,
        step_count=1,
        attempts_by_node={"node.action": 1},
        edge_traversals={"edge.action.terminal": 1, "edge.start.action": 1},
        completed_node_ids=["node.start", "node.action", "node.terminal"],
        consumed_usage=LoopUsage(),
        mechanism_family="generic contract fixture",
        holdout_state=HoldoutState.SEALED,
        variables=variables,
        last_outcome=LoopNodeOutcome.SUCCEEDED,
        terminal_reason="The bounded local action completed.",
    )
    payload = {
        "schema_version": 1,
        "run_id": episode.run_id,
        "task_id": TASK_ID,
        "spec_id": spec.spec_id,
        "spec_hash": spec.spec_hash,
        "state": state.model_dump(mode="json"),
        "event_count": 1,
        "lineage_hash": canonical_sha256(f"loop-lineage:{index}"),
        "terminal_event_id": f"event.loop.{index}.terminal",
        "terminal_event_hash": canonical_sha256(f"loop-terminal:{index}"),
        "seal_hash": canonical_sha256(f"loop-seal:{index}"),
    }
    return LoopRunSnapshot.model_validate(payload | {"snapshot_hash": canonical_sha256(payload)})


def _build_evaluation_report(
    harness: HarnessSpec,
    episodes: tuple[EpisodePackage, ...],
    loop_snapshots: tuple[LoopRunSnapshot, ...],
    *,
    evidence_bundle_hash: str,
    grader_independence: GraderIndependence,
) -> EvaluationReport:
    task = EvaluationTaskRecord(
        task_id=TASK_ID,
        version="1",
        task_contract_hash=canonical_sha256(harness.task_contract),
        protocol_hash=PROTOCOL_HASH,
        holdout_id="holdout.fixture",
        holdout_hash=canonical_sha256("holdout.fixture"),
        minimum_independent_trials=3,
    )
    rubric = RubricRecord.create(
        rubric_id="rubric.cycle.validation",
        version="1",
        criteria=[
            RubricCriterion(
                criterion_id=f"criterion.{dimension.value}",
                dimension=dimension,
                grader_id="agent.grader",
                threshold=1.0,
                description=f"Verify the frozen {dimension.value} contract.",
            )
            for dimension in RegressionDimension
        ],
    )
    projections: list[EpisodeEvaluationProjection] = []
    for index, (episode, loop_snapshot) in enumerate(
        zip(episodes, loop_snapshots, strict=True),
        start=1,
    ):
        projection = project_episode_for_evaluation(
            episode,
            task=task,
            rubric=rubric,
            replicate_index=index,
            evidence_bundle_hash=evidence_bundle_hash,
            evidence_verdict=EvaluationVerdict.PASS,
            replay_hash=episode.journal_lineage_hash,
            loop_snapshot_hash=loop_snapshot.snapshot_hash,
            independent_grader_ids=["agent.grader"],
        )
        payload = projection.model_dump(mode="json")
        for grader in payload["graders"]:
            grader["independence"] = grader_independence.value
        projections.append(EpisodeEvaluationProjection.model_validate(payload))
    regression_cases = []
    for dimension in RegressionDimension:
        digest = canonical_sha256(f"regression:{dimension.value}")
        regression_cases.append(
            RegressionCase(
                case_id=f"regression.{dimension.value}",
                dimension=dimension,
                expected_digest=digest,
                observed_digest=digest,
                deterministic_validator_passed=True,
                evidence_refs=[f"evidence.regression.{dimension.value}"],
                holdout_access_stage=(
                    HoldoutAccessStage.CONFIRMATORY_TERMINAL
                    if dimension == RegressionDimension.HOLDOUT_INTEGRITY
                    else HoldoutAccessStage.NEVER
                ),
            )
        )
    regression = LocalRegressionRunner().run(
        suite_id="regression.cycle.validation",
        version="1",
        cases=regression_cases,
    )
    security = FaultMatrixRunner().run(
        matrix_id="security.cycle.validation",
        version="1",
        cases=default_agentic_fault_cases(),
    )
    return UnifiedEvaluationEngine().evaluate(
        report_id="report.cycle.validation",
        task=task,
        rubric=rubric,
        projections=projections,
        regression=regression,
        security=security,
        policy=PromotionPolicy(
            policy_id="policy.promotion.fixture",
            version="1",
            minimum_independent_trials=3,
            minimum_success_rate=1.0,
            minimum_wilson_lower=0.4,
            max_total_tokens=0,
            max_estimated_cost_usd=0.0,
            max_wall_time_seconds=1.0,
            max_tool_calls=0,
        ),
        candidate_id="candidate.fixture",
        candidate_hash=canonical_sha256("candidate.fixture"),
        evaluated_at=BASE_TIME + timedelta(hours=2),
    )


LifecycleRecords = tuple[
    ResearchObservation,
    ResearchProblem,
    ResearchHypothesis,
    ScientificIntervention,
    ResearchEvaluation,
]
ScientificRecord = (
    ResearchObservation
    | ResearchProblem
    | ResearchHypothesis
    | ScientificIntervention
    | ResearchEvaluation
)


def _build_cycle_records(
    *,
    bundle_hash: str,
    harness: HarnessSpec,
    loop_spec: LoopSpec,
    report: EvaluationReport,
    assessment: HypothesisAssessment,
) -> LifecycleRecords:
    evidence_id = (
        "evidence.support" if assessment == HypothesisAssessment.SUPPORTED else "evidence.counter"
    )
    observation = ResearchObservation(
        observation_id="observation.fixture",
        statement="A frozen procedure produced a bounded local result.",
        measurement_spec_ref=_ref("plan.measurement", canonical_sha256("measurement.plan")),
        result_entity_ids=["entity.observation.result"],
        uncertainty_entity_ids=["entity.observation.uncertainty"],
        provenance=_binding(
            bundle_hash,
            record_entity_id="entity.record.observation",
            agent_ids=["agent.author", "agent.executor"],
            activity_ids=["activity.author", "activity.measure"],
            entity_ids=["entity.observation.result", "entity.observation.uncertainty"],
            plan_ids=["plan.author", "plan.measurement"],
        ),
    )
    problem = ResearchProblem(
        problem_id="problem.fixture",
        observation_ids=[observation.observation_id],
        statement="The bounded result requires discrimination among declared explanations.",
        scope="The frozen local contract only.",
        provenance=_binding(
            bundle_hash,
            record_entity_id="entity.record.problem",
        ),
    )
    hypothesis = ResearchHypothesis(
        hypothesis_id="hypothesis.fixture",
        problem_ids=[problem.problem_id],
        mechanism_claim_id="claim.mechanism",
        prediction_claim_ids=["claim.prediction"],
        falsifier_claim_ids=["claim.falsifier"],
        competing_explanation_claim_ids=["claim.competing"],
        scope="The declared local observation and intervention scope.",
        provenance=_binding(
            bundle_hash,
            record_entity_id="entity.record.hypothesis",
            claim_ids=[
                "claim.mechanism",
                "claim.prediction",
                "claim.falsifier",
                "claim.competing",
            ],
        ),
    )
    intervention = ScientificIntervention(
        intervention_id="intervention.fixture",
        hypothesis_ids=[hypothesis.hypothesis_id],
        protocol_ref=_ref("plan.protocol", PROTOCOL_HASH),
        comparator_entity_ids=["entity.intervention.comparator"],
        changed_factor_entity_ids=["entity.intervention.changed"],
        frozen_factor_entity_ids=["entity.intervention.frozen"],
        estimand_claim_ids=["claim.estimand"],
        metric_spec_entity_ids=["entity.intervention.measurement"],
        decision_rule_entity_ids=["entity.intervention.rule"],
        harness_spec_ref=_ref(harness.spec_id, harness.spec_hash),
        loop_spec_ref=_ref(loop_spec.spec_id, loop_spec.spec_hash),
        provenance=_binding(
            bundle_hash,
            record_entity_id="entity.record.intervention",
            entity_ids=[
                "entity.intervention.comparator",
                "entity.intervention.changed",
                "entity.intervention.frozen",
                "entity.intervention.measurement",
                "entity.intervention.rule",
            ],
            plan_ids=["plan.author", "plan.protocol"],
            claim_ids=["claim.estimand"],
        ),
    )
    assessment_record = HypothesisAssessmentRecord(
        hypothesis_id=hypothesis.hypothesis_id,
        assessment=assessment,
        supporting_evidence_ids=(
            [evidence_id] if assessment == HypothesisAssessment.SUPPORTED else []
        ),
        counterevidence_ids=(
            [evidence_id] if assessment == HypothesisAssessment.CONTRADICTED else []
        ),
        objective_result_entity_ids=["entity.evaluation.result"],
        uncertainty_entity_ids=["entity.evaluation.uncertainty"],
        rationale="The frozen decision rule was applied to validated evidence.",
    )
    evaluation = ResearchEvaluation(
        evaluation_id="evaluation.fixture",
        intervention_ids=[intervention.intervention_id],
        evaluation_report_ref=_ref(report.report_id, report.report_hash),
        evaluation_subject_hash=evaluation_subject_hash(report),
        assessments=[assessment_record],
        provenance=_binding(
            bundle_hash,
            record_entity_id="entity.record.evaluation",
            agent_ids=[
                "agent.author",
                "agent.decision",
                "agent.evidence",
                "agent.grader",
            ],
            activity_ids=[
                "activity.author",
                "activity.decision",
                "activity.evidence",
                "activity.validate",
            ],
            entity_ids=[
                "entity.decision.artifact",
                "entity.evaluation.result",
                "entity.evaluation.uncertainty",
                "entity.source",
            ],
            claim_ids=["claim.mechanism"],
            evidence_ids=[evidence_id],
            validation_ids=["validation.evidence"],
            decision_ids=["decision.evidence"],
        ),
    )
    return observation, problem, hypothesis, intervention, evaluation


def _binding(
    bundle_hash: str,
    *,
    record_entity_id: str,
    agent_ids: list[str] | None = None,
    activity_ids: list[str] | None = None,
    entity_ids: list[str] | None = None,
    plan_ids: list[str] | None = None,
    claim_ids: list[str] | None = None,
    evidence_ids: list[str] | None = None,
    validation_ids: list[str] | None = None,
    decision_ids: list[str] | None = None,
) -> ProvenanceBinding:
    return ProvenanceBinding(
        bundle_ref=_ref("bundle.cycle.validation", bundle_hash),
        agent_ids=agent_ids or ["agent.author"],
        activity_ids=activity_ids or ["activity.author"],
        entity_ids=[record_entity_id, *(entity_ids or [])],
        record_entity_id=record_entity_id,
        authoring_activity_id="activity.author",
        author_agent_ids=["agent.author"],
        plan_ids=plan_ids or ["plan.author"],
        claim_ids=claim_ids or [],
        evidence_ids=evidence_ids or [],
        validation_ids=validation_ids or [],
        decision_ids=decision_ids or [],
    )


def _build_provenance_bundle(
    records: LifecycleRecords,
    episodes: tuple[EpisodePackage, ...],
    report: EvaluationReport,
    *,
    assessment: HypothesisAssessment,
    evidence_validation_status: ValidationStatus,
) -> ProvenanceBundle:
    episode_output_hashes = [
        output_hash
        for episode in episodes
        if (output_hash := episode.final_outcome.output_hash) is not None
    ]
    if len(episode_output_hashes) != len(episodes):
        raise AssertionError("a successful fixture episode lacks an output hash")
    objective_hash = canonical_sha256({"episode_output_hashes": sorted(episode_output_hashes)})
    observation, problem, hypothesis, intervention, evaluation = records
    record_entities = [
        _entity(
            record.provenance.record_entity_id,
            kind,
            f"Authored {type(record).__name__}",
            scientific_record_semantic_hash(record),
        )
        for record, kind in (
            (observation, EntityKind.EXPERIMENT_RECORD),
            (problem, EntityKind.ARTIFACT),
            (hypothesis, EntityKind.HYPOTHESIS),
            (intervention, EntityKind.ARTIFACT),
            (evaluation, EntityKind.DECISION),
        )
    ]
    entities = [
        *record_entities,
        _entity(
            "entity.observation.result",
            EntityKind.EXPERIMENT_RECORD,
            "Observation result",
            canonical_sha256("observation.result"),
        ),
        _entity(
            "entity.observation.uncertainty",
            EntityKind.ARTIFACT,
            "Observation uncertainty",
            canonical_sha256("observation.uncertainty"),
        ),
        *[
            _entity(
                entity_id,
                EntityKind.ARTIFACT,
                f"Declared intervention field {index}",
                canonical_sha256(entity_id),
            )
            for index, entity_id in enumerate(
                (
                    "entity.intervention.comparator",
                    "entity.intervention.changed",
                    "entity.intervention.frozen",
                    "entity.intervention.measurement",
                    "entity.intervention.rule",
                ),
                start=1,
            )
        ],
        _entity(
            "entity.source",
            EntityKind.SOURCE_SNAPSHOT,
            "Frozen source snapshot",
            canonical_sha256("source.content"),
        ),
        _entity(
            "entity.evaluation.result",
            EntityKind.EXPERIMENT_RECORD,
            "Objective evaluation result",
            objective_hash,
        ),
        _entity(
            "entity.evaluation.uncertainty",
            EntityKind.ARTIFACT,
            "Evaluation uncertainty",
            report.uncertainty.content_hash(),
        ),
        _entity(
            "entity.decision.artifact",
            EntityKind.DECISION,
            "Decision artifact",
            canonical_sha256("decision.artifact"),
        ),
    ]
    activities = [
        _activity("activity.author", ActivityKind.PROJECTION, "Author records", 0, 10),
        _activity("activity.measure", ActivityKind.EXECUTION, "Measure result", 11, 20),
        _activity("activity.evidence", ActivityKind.PROJECTION, "Build evidence", 21, 30),
        _activity("activity.validate", ActivityKind.VALIDATION, "Validate evidence", 31, 40),
        _activity("activity.decision", ActivityKind.DECISION, "Record decision", 41, 50),
    ]
    claims = [
        Claim(
            claim_id=claim_id,
            statement=statement,
            project_id="project.fixture",
            confidence=0.8,
            core=claim_id == "claim.mechanism",
            valid_from=_at(0),
        )
        for claim_id, statement in (
            ("claim.mechanism", "A declared mechanism explains the bounded result."),
            ("claim.prediction", "The registered intervention predicts a result."),
            ("claim.falsifier", "A registered outcome would falsify the mechanism."),
            ("claim.competing", "A competing explanation remains distinguishable."),
            ("claim.estimand", "The registered contrast defines the target effect."),
        )
    ]
    evidence_id = (
        "evidence.support" if assessment == HypothesisAssessment.SUPPORTED else "evidence.counter"
    )
    evidence_records: list[Evidence] = []
    counterevidence_records: list[Counterevidence] = []
    if assessment == HypothesisAssessment.SUPPORTED:
        evidence_records.append(
            Evidence(
                evidence_id=evidence_id,
                claim_id="claim.mechanism",
                artifact_entity_id="entity.evaluation.result",
                source_entity_id="entity.source",
                source_snapshot_id="snapshot.source",
                generating_activity_id="activity.evidence",
                responsible_agent_ids=["agent.evidence"],
                validation_ids=["validation.evidence"],
                summary="Validated evidence supports the registered claim.",
                confidence=0.9,
                direction=EvidenceDirection.SUPPORTS,
                valid_from=_at(30),
            )
        )
    else:
        counterevidence_records.append(
            Counterevidence(
                evidence_id=evidence_id,
                claim_id="claim.mechanism",
                artifact_entity_id="entity.evaluation.result",
                source_entity_id="entity.source",
                source_snapshot_id="snapshot.source",
                generating_activity_id="activity.evidence",
                responsible_agent_ids=["agent.evidence"],
                validation_ids=["validation.evidence"],
                summary="Validated counterevidence contradicts the registered claim.",
                confidence=0.9,
                direction=EvidenceDirection.CONTRADICTS,
                valid_from=_at(30),
            )
        )
    return ProvenanceBundle.create(
        bundle_id="bundle.cycle.validation",
        project_id="project.fixture",
        run_id="run.provenance.fixture",
        created_at=_at(60),
        entities=entities,
        activities=activities,
        agents=[
            _agent("agent.author", "Lifecycle author", "implementation.author"),
            _agent("agent.executor", "Procedure executor", "implementation.executor"),
            _agent("agent.evidence", "Evidence producer", "implementation.evidence"),
            _agent("agent.grader", "Independent grader", "implementation.grader"),
            _agent("agent.decision", "Decision recorder", "implementation.decision"),
        ],
        plans=[
            Plan(
                plan_id="plan.author",
                title="Authorship plan",
                description="Create immutable lifecycle records.",
                content_digest=canonical_sha256("author.plan"),
                valid_from=_at(0),
            ),
            Plan(
                plan_id="plan.measurement",
                title="Measurement plan",
                description="Produce a bounded result and uncertainty record.",
                content_digest=canonical_sha256("measurement.plan"),
                valid_from=_at(0),
            ),
            Plan(
                plan_id="plan.protocol",
                title="Intervention protocol",
                description="Freeze the declared intervention procedure.",
                content_digest=PROTOCOL_HASH,
                valid_from=_at(0),
            ),
        ],
        usages=[
            Usage(
                usage_id="usage.evidence.source",
                activity_id="activity.evidence",
                entity_id="entity.source",
                role="source",
                at_time=_at(25),
                valid_from=_at(25),
            )
        ],
        generations=[
            *[
                Generation(
                    generation_id=f"generation.{record.provenance.record_entity_id}",
                    entity_id=record.provenance.record_entity_id,
                    activity_id="activity.author",
                    at_time=_at(10),
                    valid_from=_at(10),
                )
                for record in records
            ],
            Generation(
                generation_id="generation.observation.result",
                entity_id="entity.observation.result",
                activity_id="activity.measure",
                at_time=_at(20),
                valid_from=_at(20),
            ),
            Generation(
                generation_id="generation.observation.uncertainty",
                entity_id="entity.observation.uncertainty",
                activity_id="activity.measure",
                at_time=_at(20),
                valid_from=_at(20),
            ),
            Generation(
                generation_id="generation.evaluation.result",
                entity_id="entity.evaluation.result",
                activity_id="activity.evidence",
                at_time=_at(30),
                valid_from=_at(30),
            ),
            Generation(
                generation_id="generation.decision.artifact",
                entity_id="entity.decision.artifact",
                activity_id="activity.decision",
                at_time=_at(50),
                valid_from=_at(50),
            ),
        ],
        associations=[
            _association(
                "association.author",
                "activity.author",
                "agent.author",
                "author",
                "plan.author",
                5,
            ),
            _association(
                "association.measure",
                "activity.measure",
                "agent.executor",
                "executor",
                "plan.measurement",
                15,
            ),
            _association(
                "association.evidence",
                "activity.evidence",
                "agent.evidence",
                "evidence_builder",
                "plan.author",
                25,
            ),
            _association(
                "association.validator",
                "activity.validate",
                "agent.grader",
                "validator",
                "plan.author",
                35,
            ),
            _association(
                "association.decision",
                "activity.decision",
                "agent.decision",
                "decision_maker",
                "plan.author",
                45,
            ),
        ],
        source_snapshots=[
            SourceSnapshot(
                snapshot_id="snapshot.source",
                entity_id="entity.source",
                source_uri="urn:fixture:source",
                retrieved_at=_at(21),
                content_digest=canonical_sha256("source.content"),
                valid_from=_at(21),
            )
        ],
        claims=claims,
        evidence=evidence_records,
        counterevidence=counterevidence_records,
        validations=[
            Validation(
                validation_id="validation.evidence",
                subject_id=evidence_id,
                activity_id="activity.validate",
                agent_id="agent.grader",
                status=evidence_validation_status,
                summary="The evidence trace received its declared validation status.",
                checked_at=_at(40),
                artifact_entity_id="entity.evaluation.result",
                valid_from=_at(40),
            )
        ],
        decisions=[
            Decision(
                decision_id="decision.evidence",
                claim_ids=["claim.mechanism"],
                activity_id="activity.decision",
                responsible_agent_id="agent.decision",
                validation_ids=["validation.evidence"],
                artifact_entity_id="entity.decision.artifact",
                outcome=(
                    "The registered support decision passed."
                    if assessment == HypothesisAssessment.SUPPORTED
                    else "The registered contradiction decision passed."
                ),
                rationale="The bound evidence and validation are complete.",
                decided_at=_at(50),
                valid_from=_at(50),
            )
        ],
    )


def _entity(
    entity_id: str,
    kind: EntityKind,
    label: str,
    content_digest: str,
) -> Entity:
    return Entity(
        entity_id=entity_id,
        kind=kind,
        label=label,
        content_digest=content_digest,
        valid_from=_at(0),
    )


def _activity(
    activity_id: str,
    kind: ActivityKind,
    label: str,
    started_minute: int,
    ended_minute: int,
) -> Activity:
    return Activity(
        activity_id=activity_id,
        kind=kind,
        label=label,
        started_at=_at(started_minute),
        ended_at=_at(ended_minute),
        valid_from=_at(started_minute),
    )


def _agent(agent_id: str, label: str, implementation: str) -> Agent:
    return Agent(
        agent_id=agent_id,
        kind=ProvenanceAgentKind.SOFTWARE,
        label=label,
        implementation_hash=canonical_sha256(implementation),
        valid_from=_at(0),
    )


def _association(
    association_id: str,
    activity_id: str,
    agent_id: str,
    role: str,
    plan_id: str,
    minute: int,
) -> Association:
    return Association(
        association_id=association_id,
        activity_id=activity_id,
        agent_id=agent_id,
        role=role,
        plan_id=plan_id,
        at_time=_at(minute),
        valid_from=_at(minute),
    )


def _ref(ref_id: str, ref_hash: str) -> ContentAddressedRef:
    return ContentAddressedRef(ref_id=ref_id, ref_hash=ref_hash)


def _at(minutes: int) -> datetime:
    return BASE_TIME + timedelta(minutes=minutes)
