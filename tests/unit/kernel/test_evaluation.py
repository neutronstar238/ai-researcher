"""Tests for unified evaluation, fault coverage, and promotion gates."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import cast

import pytest
from pydantic import ValidationError

from autoresearch.kernel import (
    AgenticFaultKind,
    CostRecord,
    EnvironmentOutcome,
    EpisodeCostRecord,
    EpisodeEvaluationProjection,
    EpisodeOutcomeStatus,
    EpisodePackage,
    EvaluationGate,
    EvaluationIntegrityError,
    EvaluationReport,
    EvaluationTaskRecord,
    EvaluationTrialRecord,
    EvaluationVerdict,
    ExternalBenchmarkSpec,
    FaultMatrixReport,
    FaultMatrixRunner,
    FaultSignals,
    GraderIndependence,
    GraderKind,
    GraderRecord,
    GraderResult,
    HoldoutAccessStage,
    JsonFieldType,
    LocalRegressionRunner,
    OutcomeRecord,
    PromotionDecision,
    PromotionPolicy,
    RegressionCase,
    RegressionDimension,
    RegressionSuiteReport,
    RubricCriterion,
    RubricRecord,
    ScientificOutcome,
    StepOutcome,
    StructuredField,
    StructuredOutputContract,
    TaskContract,
    TrajectoryKind,
    TrajectoryRecord,
    TrajectoryStep,
    TrialRecord,
    UncertaintyRecord,
    UnifiedEvaluationEngine,
    canonical_json,
    canonical_sha256,
    default_agentic_fault_cases,
    evaluation_json_schemas,
    project_episode_for_evaluation,
)

BASE_TIME = datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc)


def _hash(value: object) -> str:
    return cast(str, canonical_sha256(value))


def _task() -> EvaluationTaskRecord:
    return EvaluationTaskRecord(
        task_id="evaluation.fixture",
        version="1",
        task_contract_hash=_hash("task"),
        protocol_hash=_hash("protocol"),
        holdout_id="holdout.fixture",
        holdout_hash=_hash("holdout"),
    )


def _rubric() -> RubricRecord:
    return RubricRecord.create(
        rubric_id="rubric.fixture",
        version="1",
        criteria=[
            RubricCriterion(
                criterion_id=f"criterion.{dimension.value}",
                dimension=dimension,
                grader_id="grader.exact",
                threshold=1.0,
                description=f"Deterministically verify {dimension.value}.",
            )
            for dimension in RegressionDimension
        ],
    )


def _regression(
    *,
    failing: RegressionDimension | None = None,
) -> RegressionSuiteReport:
    cases = []
    for dimension in RegressionDimension:
        expected = _hash(f"expected:{dimension.value}")
        observed = _hash(f"observed:{dimension.value}") if dimension == failing else expected
        cases.append(
            RegressionCase(
                case_id=f"regression.{dimension.value}",
                dimension=dimension,
                expected_digest=expected,
                observed_digest=observed,
                deterministic_validator_passed=True,
                evidence_refs=[f"artifact.{dimension.value}"],
                holdout_access_stage=(
                    HoldoutAccessStage.CONFIRMATORY_TERMINAL
                    if dimension == RegressionDimension.HOLDOUT_INTEGRITY
                    else HoldoutAccessStage.NEVER
                ),
            )
        )
    return LocalRegressionRunner().run(
        suite_id="regression.fixture",
        version="1",
        cases=cases,
    )


def _security() -> FaultMatrixReport:
    return FaultMatrixRunner().run(
        matrix_id="security.fixture",
        version="1",
        cases=default_agentic_fault_cases(),
    )


def _policy(**overrides: object) -> PromotionPolicy:
    values: dict[str, object] = {
        "policy_id": "promotion.fixture",
        "version": "1",
        "max_total_tokens": 1_000,
        "max_estimated_cost_usd": 10.0,
        "max_wall_time_seconds": 60.0,
        "max_tool_calls": 30,
    }
    values.update(overrides)
    return PromotionPolicy.model_validate(values)


def _projection(
    replicate_index: int,
    rubric: RubricRecord,
    *,
    status: EpisodeOutcomeStatus = EpisodeOutcomeStatus.SUCCEEDED,
    evidence_verdict: EvaluationVerdict = EvaluationVerdict.PASS,
    grader_independence: GraderIndependence = GraderIndependence.INDEPENDENT,
    grader_score: float = 1.0,
    total_tokens: int = 10,
    cost_known: bool = True,
) -> EpisodeEvaluationProjection:
    trial_id = f"evaluation.trial.{replicate_index}"
    episode_id = f"episode.{replicate_index}"
    trajectory_id = f"{trial_id}.trajectory"
    outcome_id = f"{trial_id}.outcome"
    cost_id = f"{trial_id}.cost"
    successful = status in {
        EpisodeOutcomeStatus.SUCCEEDED,
        EpisodeOutcomeStatus.NEGATIVE_RESULT,
    }
    scientific_outcome = {
        EpisodeOutcomeStatus.SUCCEEDED: ScientificOutcome.POSITIVE,
        EpisodeOutcomeStatus.NEGATIVE_RESULT: ScientificOutcome.VERIFIED_NEGATIVE,
        EpisodeOutcomeStatus.BLOCKED: ScientificOutcome.NONE,
        EpisodeOutcomeStatus.FAILED: ScientificOutcome.NONE,
    }[status]
    graders = [
        GraderRecord(
            grader_record_id=f"{trial_id}.grader.{index}",
            evaluation_trial_id=trial_id,
            criterion_id=criterion.criterion_id,
            grader_id=criterion.grader_id,
            grader_version="1",
            kind=GraderKind.DETERMINISTIC,
            independence=grader_independence,
            score=grader_score,
            verdict=(
                EvaluationVerdict.PASS
                if grader_score >= criterion.threshold
                else EvaluationVerdict.FAIL
            ),
            explanation_hash=_hash(f"grader:{criterion.criterion_id}:{grader_score}"),
            evidence_refs=[f"artifact.{replicate_index}"],
        )
        for index, criterion in enumerate(rubric.criteria, start=1)
    ]
    trajectory = TrajectoryRecord(
        trajectory_id=trajectory_id,
        evaluation_trial_id=trial_id,
        episode_id=episode_id,
        episode_hash=_hash(f"episode:{replicate_index}"),
        trajectory_hash=_hash(f"trajectory:{replicate_index}"),
        journal_lineage_hash=_hash(f"lineage:{replicate_index}"),
        replay_hash=_hash(f"replay:{replicate_index}"),
        step_count=1,
        event_refs=[f"event.{replicate_index}"],
    )
    outcome = OutcomeRecord(
        outcome_id=outcome_id,
        evaluation_trial_id=trial_id,
        environment_status=status,
        scientific_outcome=scientific_outcome,
        environment_outcome_hash=_hash(f"outcome:{replicate_index}"),
        environment_output_hash=(_hash(f"output:{replicate_index}") if successful else None),
        evidence_bundle_hash=(_hash(f"evidence:{replicate_index}") if successful else None),
        evidence_verdict=(evidence_verdict if successful else EvaluationVerdict.UNKNOWN),
        summary_hash=_hash(f"summary:{replicate_index}"),
    )
    cost = CostRecord(
        cost_id=cost_id,
        evaluation_trial_id=trial_id,
        input_tokens=4,
        output_tokens=6,
        total_tokens=total_tokens,
        estimated_cost_usd=0.01,
        cost_known=cost_known,
        wall_time_seconds=0.1,
        tool_calls=1,
    )
    trial = EvaluationTrialRecord(
        evaluation_trial_id=trial_id,
        source_trial_id=f"source.trial.{replicate_index}",
        task_id="evaluation.fixture",
        replicate_index=replicate_index,
        episode_id=episode_id,
        episode_hash=trajectory.episode_hash,
        started_at=BASE_TIME + timedelta(seconds=replicate_index),
        completed_at=BASE_TIME + timedelta(seconds=replicate_index + 1),
        trajectory_id=trajectory_id,
        outcome_id=outcome_id,
        grader_record_ids=[item.grader_record_id for item in graders],
        cost_id=cost_id,
    )
    return EpisodeEvaluationProjection(
        trial=trial,
        trajectory=trajectory,
        outcome=outcome,
        graders=graders,
        cost=cost,
        failure_slices=[],
    )


def _evaluate(
    projections: list[EpisodeEvaluationProjection],
    *,
    regression: RegressionSuiteReport | None = None,
    policy: PromotionPolicy | None = None,
    candidate_is_active: bool = False,
    rollback_target_id: str | None = None,
    rollback_target_hash: str | None = None,
) -> EvaluationReport:
    return UnifiedEvaluationEngine().evaluate(
        report_id="evaluation.report",
        task=_task(),
        rubric=_rubric(),
        projections=projections,
        regression=regression or _regression(),
        security=_security(),
        policy=policy or _policy(),
        candidate_id="candidate.fixture",
        candidate_hash=_hash("candidate"),
        evaluated_at=BASE_TIME,
        candidate_is_active=candidate_is_active,
        rollback_target_id=rollback_target_id,
        rollback_target_hash=rollback_target_hash,
    )


def _episode(
    *,
    status: EpisodeOutcomeStatus = EpisodeOutcomeStatus.SUCCEEDED,
) -> EpisodePackage:
    output = {"status": "negative" if status == EpisodeOutcomeStatus.NEGATIVE_RESULT else "ok"}
    output_hash = _hash(output)
    task_contract = TaskContract(
        policy_id="task.fixture",
        version="1",
        task_id="evaluation.fixture",
        instructions="Execute the frozen local evaluation fixture.",
        output_contract=StructuredOutputContract(
            fields=[
                StructuredField(
                    name="status",
                    value_type=JsonFieldType.STRING,
                )
            ]
        ),
        success_criteria=["Return a schema-valid local result."],
        forbidden_actions=["Do not access a network service."],
        stop_conditions=["Stop after one trial."],
        required_permission_ids=[],
        required_tool_ids=[],
    )
    trajectory = TrajectoryStep(
        step_id="trajectory.step.1",
        sequence=1,
        trial_id="source.trial.1",
        kind=TrajectoryKind.MODEL,
        outcome=StepOutcome.SUCCEEDED,
        actor_id="model.fixture",
        occurred_at=BASE_TIME,
        summary="private raw trajectory sentence",
    )
    grader = GraderResult(
        grader_id="grader.exact",
        grader_version="1",
        kind=GraderKind.DETERMINISTIC,
        score=1.0,
        passed=True,
        reason="private raw grader explanation",
    )
    cost = EpisodeCostRecord(
        cost_id="cost.source.1",
        trial_id="source.trial.1",
        prompt_tokens=4,
        completion_tokens=3,
        total_tokens=7,
        estimated_cost_usd=0.0,
        cost_known=True,
        wall_time_seconds=0.1,
        tool_calls=0,
    )
    trial = TrialRecord(
        trial_id="source.trial.1",
        sequence=1,
        status=status,
        started_at=BASE_TIME,
        completed_at=BASE_TIME + timedelta(seconds=1),
        provider_ref="local.fixture",
        model_ref="model.fixture",
        trajectory_step_ids=[trajectory.step_id],
        grader_ids=[grader.grader_id],
        cost_id=cost.cost_id,
        output_hash=output_hash,
    )
    return EpisodePackage.create(
        episode_id="episode.source.1",
        run_id="run.source.1",
        harness_spec_id="harness.fixture",
        harness_spec_hash=_hash("harness"),
        task_contract=task_contract,
        task_input_hash=_hash({"fixture": True}),
        started_at=BASE_TIME,
        completed_at=BASE_TIME + timedelta(seconds=1),
        trials=[trial],
        trajectory=[trajectory],
        final_outcome=EnvironmentOutcome(
            status=status,
            summary="private raw environment summary",
            structured_output=output,
            output_hash=output_hash,
        ),
        graders=[grader],
        costs=[cost],
        journal_terminal_event_id="event.terminal",
        journal_terminal_event_hash=_hash("terminal-event"),
        journal_lineage_hash=_hash("lineage"),
        journal_seal_hash=_hash("seal"),
    )


def test_default_fault_matrix_detects_and_blocks_all_ten_faults() -> None:
    cases = default_agentic_fault_cases()
    report = FaultMatrixRunner().run(
        matrix_id="security.default",
        version="1",
        cases=cases,
    )

    assert len(cases) == len(AgenticFaultKind) == 10
    assert report.overall_verdict == EvaluationVerdict.PASS
    assert {item.expected_fault for item in report.results} == set(AgenticFaultKind)
    assert all(item.control_action == "block" for item in report.results)
    assert report.matrix_hash == report.calculated_hash()


def test_fault_detector_allows_benign_signals_and_requires_full_coverage() -> None:
    runner = FaultMatrixRunner()

    assert runner.detect(FaultSignals()) == []
    with pytest.raises(ValidationError, match="cover all required Agentic faults"):
        runner.run(
            matrix_id="security.incomplete",
            version="1",
            cases=default_agentic_fault_cases()[:-1],
        )


def test_fault_and_regression_reports_reject_forged_case_results() -> None:
    security = _security()
    security_values = security.model_dump(mode="json", exclude={"matrix_hash"})
    security_values["results"][0]["case_hash"] = _hash("forged")
    with pytest.raises(ValidationError, match="contradicts its case"):
        FaultMatrixReport.create(**security_values)

    regression = _regression()
    regression_values = regression.model_dump(
        mode="json",
        exclude={"suite_hash"},
    )
    regression_values["results"][0]["verdict"] = EvaluationVerdict.FAIL
    with pytest.raises(ValidationError, match="contradicts its case"):
        RegressionSuiteReport.create(**regression_values)


@pytest.mark.parametrize(
    ("dimension", "reason"),
    [
        (RegressionDimension.PROTOCOL_MATCH, "digest_mismatch"),
        (RegressionDimension.EVIDENCE_MATCH, "digest_mismatch"),
        (RegressionDimension.SCIENTIFIC_CORE, "digest_mismatch"),
        (RegressionDimension.REPLAY_FIDELITY, "digest_mismatch"),
        (RegressionDimension.HOLDOUT_INTEGRITY, "digest_mismatch"),
    ],
)
def test_local_regression_fails_closed_by_dimension(
    dimension: RegressionDimension,
    reason: str,
) -> None:
    report = _regression(failing=dimension)
    failed = next(item for item in report.results if item.dimension == dimension)

    assert report.overall_verdict == EvaluationVerdict.FAIL
    assert failed.verdict == EvaluationVerdict.FAIL
    assert failed.reason_code == reason


def test_local_regression_rejects_adaptive_holdout_use() -> None:
    digest = _hash("same")
    cases = [
        RegressionCase(
            case_id=f"regression.{dimension.value}",
            dimension=dimension,
            expected_digest=digest,
            observed_digest=digest,
            deterministic_validator_passed=True,
            evidence_refs=["artifact.fixture"],
            holdout_access_stage=(
                HoldoutAccessStage.ADAPTIVE
                if dimension == RegressionDimension.HOLDOUT_INTEGRITY
                else HoldoutAccessStage.NEVER
            ),
        )
        for dimension in RegressionDimension
    ]
    report = LocalRegressionRunner().run(
        suite_id="regression.holdout",
        version="1",
        cases=cases,
    )

    failed = next(
        item for item in report.results if item.dimension == RegressionDimension.HOLDOUT_INTEGRITY
    )
    assert failed.reason_code == "holdout_leakage"
    assert report.overall_verdict == EvaluationVerdict.FAIL


def test_uncertainty_reports_repeats_and_never_collapses_unknown() -> None:
    uncertainty = UncertaintyRecord.calculate(
        {
            "trial.1": EvaluationVerdict.PASS,
            "trial.2": EvaluationVerdict.PASS,
            "trial.3": EvaluationVerdict.FAIL,
        }
    )

    assert uncertainty.trial_count == 3
    assert uncertainty.success_count == 2
    assert uncertainty.success_rate == pytest.approx(2 / 3)
    assert 0.0 < uncertainty.wilson_lower < uncertainty.wilson_upper < 1.0
    with pytest.raises(ValueError, match="cannot collapse unknown"):
        UncertaintyRecord.calculate({"trial.1": EvaluationVerdict.UNKNOWN})


def test_external_benchmark_requires_explicit_opt_in() -> None:
    benchmark = ExternalBenchmarkSpec(
        benchmark_id="benchmark.core",
        version="1",
        source_ref="core-bench",
        opt_in_env="AUTORESEARCH_CORE_BENCH",
        network_required=True,
        max_estimated_cost_usd=50.0,
    )

    assert benchmark.enabled_by_default is False
    assert benchmark.is_opted_in({}) is False
    assert benchmark.is_opted_in({"AUTORESEARCH_CORE_BENCH": "true"}) is True
    assert benchmark.is_opted_in({"AUTORESEARCH_CORE_BENCH": "0"}) is False


def test_unified_engine_promotes_only_when_every_hard_gate_passes() -> None:
    rubric = _rubric()
    projections = [_projection(index, rubric) for index in range(1, 4)]

    report = _evaluate(projections)

    assert report.promotion.decision == PromotionDecision.PROMOTE
    assert {item.gate for item in report.promotion.gates} == set(EvaluationGate)
    assert all(item.verdict == EvaluationVerdict.PASS for item in report.promotion.gates)
    assert report.system_quality_verdict == EvaluationVerdict.PASS
    assert report.scientific_validity_verdict == EvaluationVerdict.PASS
    assert report.rollback is None
    report.verify_integrity()

    report.costs[0].total_tokens += 1
    with pytest.raises(EvaluationIntegrityError, match="integrity"):
        report.verify_integrity()


def test_repeated_trials_must_reference_distinct_episode_evidence() -> None:
    rubric = _rubric()
    projections = [_projection(index, rubric) for index in range(1, 4)]
    projections[1].trial.episode_hash = projections[0].trial.episode_hash
    projections[1].trajectory.episode_hash = projections[0].trajectory.episode_hash

    with pytest.raises(ValidationError, match="independent episode hash"):
        _evaluate(projections)


def test_verified_negative_is_an_eligible_scientific_result() -> None:
    rubric = _rubric()
    projections = [
        _projection(
            index,
            rubric,
            status=EpisodeOutcomeStatus.NEGATIVE_RESULT,
        )
        for index in range(1, 4)
    ]

    report = _evaluate(projections)

    assert report.promotion.decision == PromotionDecision.PROMOTE
    assert all(
        item.scientific_outcome == ScientificOutcome.VERIFIED_NEGATIVE for item in report.outcomes
    )
    assert report.scientific_validity_verdict == EvaluationVerdict.PASS


def test_evidence_failure_does_not_relabel_system_quality() -> None:
    rubric = _rubric()
    projections = [
        _projection(
            index,
            rubric,
            evidence_verdict=EvaluationVerdict.FAIL,
        )
        for index in range(1, 4)
    ]

    report = _evaluate(projections)
    gates = {item.gate: item.verdict for item in report.promotion.gates}

    assert report.promotion.decision == PromotionDecision.HOLD
    assert report.system_quality_verdict == EvaluationVerdict.PASS
    assert report.scientific_validity_verdict == EvaluationVerdict.FAIL
    assert gates[EvaluationGate.REPEATED_TRIALS] == EvaluationVerdict.PASS
    assert gates[EvaluationGate.EVIDENCE_MATCH] == EvaluationVerdict.FAIL


def test_active_failure_requires_and_records_rollback() -> None:
    rubric = _rubric()
    projections = [_projection(index, rubric) for index in range(1, 4)]

    with pytest.raises(ValueError, match="rollback target"):
        _evaluate(
            projections,
            regression=_regression(failing=RegressionDimension.REPLAY_FIDELITY),
            candidate_is_active=True,
        )

    report = _evaluate(
        projections,
        regression=_regression(failing=RegressionDimension.REPLAY_FIDELITY),
        candidate_is_active=True,
        rollback_target_id="candidate.previous",
        rollback_target_hash=_hash("previous"),
    )
    assert report.promotion.decision == PromotionDecision.ROLLBACK
    assert report.rollback is not None
    assert report.rollback.target_id == "candidate.previous"
    assert "replay_fidelity_failed" in report.rollback.reason_codes


@pytest.mark.parametrize(
    ("cost_known", "grader_independence"),
    [
        (False, GraderIndependence.INDEPENDENT),
        (True, GraderIndependence.UNKNOWN),
        (True, GraderIndependence.SAME_MODEL_OR_POLICY),
    ],
)
def test_cost_and_grader_integrity_fail_closed(
    cost_known: bool,
    grader_independence: GraderIndependence,
) -> None:
    rubric = _rubric()
    projections = [
        _projection(
            index,
            rubric,
            cost_known=cost_known,
            grader_independence=grader_independence,
        )
        for index in range(1, 4)
    ]

    report = _evaluate(projections)

    assert report.promotion.decision == PromotionDecision.HOLD
    assert report.system_quality_verdict == EvaluationVerdict.FAIL


def test_projection_hashes_raw_episode_content_instead_of_copying_it() -> None:
    rubric = _rubric()
    episode = _episode()

    projection = project_episode_for_evaluation(
        episode,
        task=_task(),
        rubric=rubric,
        replicate_index=1,
        evidence_bundle_hash=_hash("evidence"),
        evidence_verdict=EvaluationVerdict.PASS,
    )
    serialized = canonical_json(projection)

    assert len(projection.graders) == len(RegressionDimension)
    assert projection.trajectory.trajectory_hash == _hash(
        [step.model_dump(mode="json") for step in episode.trajectory]
    )
    assert "private raw trajectory sentence" not in serialized
    assert "private raw grader explanation" not in serialized
    assert "private raw environment summary" not in serialized


def test_evaluation_schema_export_is_deterministic_and_complete() -> None:
    first = evaluation_json_schemas()
    second = evaluation_json_schemas()

    assert first == second
    assert {
        "EvaluationTaskRecord",
        "TrajectoryRecord",
        "OutcomeRecord",
        "RubricRecord",
        "GraderRecord",
        "CostRecord",
        "EvaluationTrialRecord",
        "RegressionSuiteReport",
        "FaultMatrixReport",
        "PromotionRecord",
        "RollbackRecord",
        "EvaluationReport",
    }.issubset(first)
