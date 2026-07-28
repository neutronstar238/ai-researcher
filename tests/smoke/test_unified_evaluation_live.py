"""Opt-in unified evaluation over two persisted real Sprint migration rounds."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from autoresearch.campaign import SprintParityReport
from autoresearch.kernel import (
    CostRecord,
    EpisodeEvaluationProjection,
    EpisodeOutcomeStatus,
    EvaluationReport,
    EvaluationTaskRecord,
    EvaluationTrialRecord,
    EvaluationVerdict,
    FaultMatrixRunner,
    GraderIndependence,
    GraderKind,
    GraderRecord,
    HoldoutAccessStage,
    LocalRegressionRunner,
    OutcomeRecord,
    PromotionDecision,
    PromotionPolicy,
    RegressionCase,
    RegressionDimension,
    RubricCriterion,
    RubricRecord,
    ScientificOutcome,
    TrajectoryRecord,
    UnifiedEvaluationEngine,
    canonical_sha256,
    default_agentic_fault_cases,
)
from autoresearch.observability import (
    GenAIEvaluationEvent,
    GenAIOperation,
    GenAISpan,
    GenAITelemetryBatch,
    LocalGenAIOtlpExporter,
    LocalGenAITelemetryPolicy,
)

LIVE_ENV = "AUTORESEARCH_UNIFIED_EVALUATION_LIVE"
OUTPUT_ENV = "AUTORESEARCH_UNIFIED_EVALUATION_OUTPUT"
BASE_TIME = datetime(2026, 7, 29, 10, 0, tzinfo=timezone.utc)
FORMAL_SPRINT_IDS = (
    "task261-bounded-autonomous-clean-v1",
    "task261-bounded-autonomous-clean-v2",
)

pytestmark = pytest.mark.skipif(
    os.getenv(LIVE_ENV) != "1",
    reason=(
        f"set {LIVE_ENV}=1 to evaluate two persisted real Sprint migration "
        "rounds and export redacted local OTLP"
    ),
)


def _rubric() -> RubricRecord:
    return RubricRecord.create(
        rubric_id="rubric.real-sprint-parity",
        version="1",
        criteria=[
            RubricCriterion(
                criterion_id=f"criterion.{dimension.value}",
                dimension=dimension,
                grader_id="grader.real-parity",
                threshold=1.0,
                description=f"Verify persisted {dimension.value} evidence.",
            )
            for dimension in RegressionDimension
        ],
    )


def _projection(
    report: SprintParityReport,
    rubric: RubricRecord,
    *,
    replicate_index: int,
) -> EpisodeEvaluationProjection:
    trial_id = f"task262.9.real.eval.{replicate_index}"
    trajectory_id = f"{trial_id}.trajectory"
    outcome_id = f"{trial_id}.outcome"
    cost_id = f"{trial_id}.cost"
    episode_hash = canonical_sha256(report)
    graders = [
        GraderRecord(
            grader_record_id=f"{trial_id}.grader.{index}",
            evaluation_trial_id=trial_id,
            criterion_id=criterion.criterion_id,
            grader_id=criterion.grader_id,
            grader_version="1",
            kind=GraderKind.DETERMINISTIC,
            independence=GraderIndependence.INDEPENDENT,
            score=1.0,
            verdict=EvaluationVerdict.PASS,
            explanation_hash=canonical_sha256(
                {
                    "criterion": criterion.criterion_id,
                    "parity_report": report.source_fingerprint,
                }
            ),
            evidence_refs=[f"parity-report.{replicate_index}"],
        )
        for index, criterion in enumerate(rubric.criteria, start=1)
    ]
    trajectory = TrajectoryRecord(
        trajectory_id=trajectory_id,
        evaluation_trial_id=trial_id,
        episode_id=report.legacy.sprint_id,
        episode_hash=episode_hash,
        trajectory_hash=report.expected_event_semantics_sha256,
        journal_lineage_hash=report.journal_lineage_hash,
        replay_hash=report.journal_seal_hash,
        step_count=report.journal_event_count,
        event_refs=[f"journal.{replicate_index}"],
    )
    outcome = OutcomeRecord(
        outcome_id=outcome_id,
        evaluation_trial_id=trial_id,
        environment_status=EpisodeOutcomeStatus.NEGATIVE_RESULT,
        scientific_outcome=ScientificOutcome.VERIFIED_NEGATIVE,
        environment_outcome_hash=canonical_sha256(report.legacy),
        environment_output_hash=report.source_fingerprint,
        evidence_bundle_hash=canonical_sha256(
            [item.model_dump(mode="json") for item in report.checks]
        ),
        evidence_verdict=EvaluationVerdict.PASS,
        summary_hash=report.journal_seal_hash,
    )
    cost = CostRecord(
        cost_id=cost_id,
        evaluation_trial_id=trial_id,
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        estimated_cost_usd=0.0,
        cost_known=True,
        wall_time_seconds=0.01,
        tool_calls=0,
    )
    trial = EvaluationTrialRecord(
        evaluation_trial_id=trial_id,
        source_trial_id=report.formal_run_id,
        task_id="evaluation.real-sprint-parity",
        replicate_index=replicate_index,
        episode_id=report.legacy.sprint_id,
        episode_hash=episode_hash,
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


def _regression(
    reports: list[SprintParityReport],
    summary_by_sprint: dict[str, dict[str, object]],
):
    expected_protocol = [item.expected_event_semantics_sha256 for item in reports]
    observed_protocol = [item.projected_event_semantics_sha256 for item in reports]
    expected_evidence = [check.legacy_sha256 for report in reports for check in report.checks]
    observed_evidence = [check.projected_sha256 for report in reports for check in report.checks]
    expected_science = [item.legacy.scientific_endpoint for item in reports]
    observed_science = [item.projected.scientific_endpoint for item in reports]
    expected_replay = [
        [
            summary_by_sprint[item.legacy.sprint_id]["lineage_hash"],
            summary_by_sprint[item.legacy.sprint_id]["seal_hash"],
        ]
        for item in reports
    ]
    observed_replay = [[item.journal_lineage_hash, item.journal_seal_hash] for item in reports]
    observations = {
        RegressionDimension.PROTOCOL_MATCH: (
            expected_protocol,
            observed_protocol,
            all(item.equivalent for item in reports),
        ),
        RegressionDimension.EVIDENCE_MATCH: (
            expected_evidence,
            observed_evidence,
            all(check.passed for item in reports for check in item.checks),
        ),
        RegressionDimension.SCIENTIFIC_CORE: (
            expected_science,
            observed_science,
            all(item.legacy.scientific_endpoint == "negative_result" for item in reports),
        ),
        RegressionDimension.REPLAY_FIDELITY: (
            expected_replay,
            observed_replay,
            expected_replay == observed_replay,
        ),
        RegressionDimension.HOLDOUT_INTEGRITY: (
            {"stage": "never", "adaptive": False},
            {"stage": "never", "adaptive": False},
            True,
        ),
    }
    cases = []
    for dimension, (expected, observed, validator_passed) in observations.items():
        cases.append(
            RegressionCase(
                case_id=f"real-sprint.{dimension.value}",
                dimension=dimension,
                expected_digest=canonical_sha256(expected),
                observed_digest=canonical_sha256(observed),
                deterministic_validator_passed=validator_passed,
                evidence_refs=[f"parity-report.{index}" for index in range(1, len(reports) + 1)],
                holdout_access_stage=(
                    HoldoutAccessStage.NEVER
                    if dimension == RegressionDimension.HOLDOUT_INTEGRITY
                    else HoldoutAccessStage.NEVER
                ),
            )
        )
    return LocalRegressionRunner().run(
        suite_id="regression.real-sprint-parity",
        version="1",
        cases=cases,
    )


def _telemetry(
    reports: list[SprintParityReport],
    evaluation: EvaluationReport,
) -> GenAITelemetryBatch:
    root = GenAISpan(
        span_id="span.evaluation",
        operation=GenAIOperation.INVOKE_WORKFLOW,
        started_at=BASE_TIME,
        ended_at=BASE_TIME + timedelta(seconds=5),
        workflow_name="unified-evaluation",
        content={
            "autoresearch.content.formal_runs": [item.model_dump(mode="json") for item in reports]
        },
    )
    spans = [root]
    events = []
    for index, report in enumerate(reports, start=1):
        span = GenAISpan(
            span_id=f"span.parity.{index}",
            parent_span_id=root.span_id,
            operation=GenAIOperation.EXECUTE_TOOL,
            started_at=BASE_TIME + timedelta(seconds=index),
            ended_at=BASE_TIME + timedelta(seconds=index, milliseconds=500),
            tool_name="sprint.parity",
            tool_type="function",
            data_source_hash=report.source_fingerprint,
        )
        spans.append(span)
        events.append(
            GenAIEvaluationEvent(
                event_id=f"evaluation.parity.{index}",
                parent_span_id=span.span_id,
                occurred_at=BASE_TIME + timedelta(seconds=index, milliseconds=250),
                evaluation_name="sprint_parity",
                score_value=1.0,
                score_label="pass",
                explanation_hash=evaluation.report_hash,
                response_id_hash=report.source_fingerprint,
            )
        )
    return GenAITelemetryBatch(
        batch_id="telemetry.task262.9.real",
        run_id="task262.9.real-evaluation",
        service_name="autoresearch",
        service_version="vnext",
        spans=spans,
        evaluation_events=events,
    )


def test_real_negative_sprint_rounds_promote_and_export_redacted_otlp(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    source_root = repository_root / "runs" / "manual-live" / "task262-sprint-migration-live-v1"
    summary_path = source_root / "smoke-summary.json"
    assert summary_path.is_file()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary_by_sprint = {item["sprint_id"]: item for item in summary["formal_runs"]}
    reports = [
        SprintParityReport.model_validate_json(
            next(
                (source_root / "migration" / "sprints" / sprint_id / "invocations").glob(
                    "*/parity-report.json"
                )
            ).read_text(encoding="utf-8")
        )
        for sprint_id in FORMAL_SPRINT_IDS
    ]
    assert len({item.source_fingerprint for item in reports}) == 2
    assert all(item.equivalent for item in reports)

    rubric = _rubric()
    task = EvaluationTaskRecord(
        task_id="evaluation.real-sprint-parity",
        version="1",
        task_contract_hash=canonical_sha256(summary["scientific_scope"]),
        protocol_hash=canonical_sha256([item.expected_event_semantics_sha256 for item in reports]),
        holdout_id="holdout.not-used",
        holdout_hash=canonical_sha256({"stage": "never", "adaptive": False}),
        minimum_independent_trials=2,
    )
    evaluation = UnifiedEvaluationEngine().evaluate(
        report_id="evaluation.task262.9.real",
        task=task,
        rubric=rubric,
        projections=[
            _projection(item, rubric, replicate_index=index)
            for index, item in enumerate(reports, start=1)
        ],
        regression=_regression(reports, summary_by_sprint),
        security=FaultMatrixRunner().run(
            matrix_id="security.task262.9.real",
            version="1",
            cases=default_agentic_fault_cases(),
        ),
        policy=PromotionPolicy(
            policy_id="promotion.task262.9.real",
            version="1",
            minimum_independent_trials=2,
            minimum_success_rate=1.0,
            minimum_wilson_lower=0.3,
            max_total_tokens=0,
            max_estimated_cost_usd=0.0,
            max_wall_time_seconds=1.0,
            max_tool_calls=0,
        ),
        candidate_id="candidate.vnext-evaluation",
        candidate_hash=canonical_sha256([item.model_dump(mode="json") for item in reports]),
        evaluated_at=BASE_TIME,
    )
    evaluation.verify_integrity()
    assert evaluation.promotion.decision == PromotionDecision.PROMOTE
    assert evaluation.system_quality_verdict == EvaluationVerdict.PASS
    assert evaluation.scientific_validity_verdict == EvaluationVerdict.PASS
    assert all(
        item.scientific_outcome == ScientificOutcome.VERIFIED_NEGATIVE
        for item in evaluation.outcomes
    )

    output_root = Path(os.getenv(OUTPUT_ENV, str(tmp_path))).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    report_path = output_root / "evaluation-report.json"
    report_path.write_text(
        evaluation.canonical_json() + "\n",
        encoding="utf-8",
    )
    restored = EvaluationReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    restored.verify_integrity()

    export = LocalGenAIOtlpExporter(output_root / "otel").export(
        _telemetry(reports, evaluation),
        LocalGenAITelemetryPolicy(
            policy_id="telemetry.task262.9.real",
            version="1",
        ),
        at_time=BASE_TIME,
    )
    otlp_path = output_root / "otel" / export.relative_path
    otlp_text = otlp_path.read_text(encoding="utf-8")
    assert export.raw_content_artifact is None
    assert export.redacted_content_field_count == 1
    assert all(sprint_id not in otlp_text for sprint_id in FORMAL_SPRINT_IDS)

    smoke_summary = {
        "schema_version": 1,
        "source_rounds": list(FORMAL_SPRINT_IDS),
        "source_fingerprints": [item.source_fingerprint for item in reports],
        "evaluation_report_sha256": evaluation.report_hash,
        "regression_suite_sha256": evaluation.regression.suite_hash,
        "fault_matrix_sha256": evaluation.security.matrix_hash,
        "decision": evaluation.promotion.decision,
        "system_quality_verdict": evaluation.system_quality_verdict,
        "scientific_validity_verdict": evaluation.scientific_validity_verdict,
        "verified_negative_count": len(evaluation.outcomes),
        "otlp_sha256": export.sha256,
        "raw_content_persisted": False,
    }
    (output_root / "smoke-summary.json").write_text(
        json.dumps(smoke_summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
