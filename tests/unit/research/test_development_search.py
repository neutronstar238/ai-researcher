import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from autoresearch.research.development_search import (
    CandidateEvaluation,
    DevelopmentAssignment,
    DevelopmentInput,
    EvaluationStatus,
    PolicyRealization,
    StageRecordStatus,
    _decode_arff,
    _EvaluationOutcome,
    _execute_assignment,
    _split_test_rows,
    analyze_development_search,
    audit_frozen_runner_source,
    frozen_candidate_catalogue,
    frozen_policy_realizations,
    prepare_development_labels,
)
from autoresearch.research.objective_task_registry import ObjectiveTaskFamily
from autoresearch.research.portfolio import PortfolioArmKind

SHA = "a" * 64


def _arff_bytes() -> bytes:
    return b"""@relation tiny
@attribute feature numeric
@attribute class {A,B}
@data
0,A
1,B
2,A
3,B
4,A
5,B
"""


def _split_bytes() -> bytes:
    return b"""@relation split
@attribute type {TRAIN,TEST}
@attribute rowid numeric
@attribute repeat numeric
@attribute fold numeric
@data
TRAIN,0,0,0
TRAIN,1,0,0
TRAIN,2,0,0
TRAIN,3,0,0
TEST,4,0,0
TEST,5,0,0
TRAIN,0,1,0
TEST,1,1,0
"""


def test_candidate_catalogue_and_policy_matrix_are_complete() -> None:
    candidates = frozen_candidate_catalogue()
    policies = frozen_policy_realizations()

    assert len(candidates) == 12
    assert len({item.candidate_id for item in candidates}) == 12
    assert (
        len(
            {
                item.mechanism_family
                for item in candidates
                if item.arm_kind is PortfolioArmKind.MECHANISM
            }
        )
        >= 3
    )
    assert sum(
        item.arm_kind is PortfolioArmKind.NULL_OR_RULE for item in candidates
    ) == 2
    assert sum(item.intentional_failure_control for item in candidates) == 1
    assert len(policies) == 9
    assert {item.policy_id for item in policies} == {
        "one_shot",
        "linear_self_loop",
        "portfolio",
        "portfolio_memory",
        "ablation-certificate",
        "ablation-diversity",
        "ablation-multi_fidelity",
        "ablation-reviewer",
        "ablation-memory",
    }
    for policy in policies:
        assert policy.proposal_slots == 12
        assert policy.model_calls_per_assignment == 0
        assert policy.reviewer_score_is_scientific_gate is False


def test_prepare_development_labels_fetches_no_confirmatory_resource(
    tmp_path: Path,
) -> None:
    data = _arff_bytes()
    split = _split_bytes()
    data_sha = hashlib.sha256(data).hexdigest()
    split_sha = hashlib.sha256(split).hexdigest()
    development = SimpleNamespace(
        unit_id="dev-task",
        family=ObjectiveTaskFamily.TABULAR_CLASSIFICATION,
        data_url="https://example.test/dev-data",
        split_url="https://example.test/dev-split",
        data_md5=hashlib.md5(data).hexdigest(),
        target_feature="class",
    )
    confirmatory = SimpleNamespace(
        unit_id="confirm-task",
        family=ObjectiveTaskFamily.TABULAR_CLASSIFICATION,
        data_url="https://example.test/confirm-data",
        split_url="https://example.test/confirm-split",
        data_md5="0" * 32,
        target_feature="class",
    )
    panel = SimpleNamespace(
        report_hash="b" * 64,
        task_units=[development, confirmatory],
    )
    report = SimpleNamespace(
        task_replays=[
            SimpleNamespace(
                unit_id="dev-task",
                data_sha256=data_sha,
                split_sha256=split_sha,
            )
        ]
    )
    requested: list[str] = []

    def fake_fetch(url: str, maximum_bytes: int, timeout: int) -> bytes:
        assert maximum_bytes > 0
        assert timeout > 0
        requested.append(url)
        return {
            development.data_url: data,
            development.split_url: split,
        }[url]

    labels, audit = prepare_development_labels(
        panel,
        report,
        tmp_path,
        fetch=fake_fetch,
    )

    assert requested == [development.data_url, development.split_url]
    assert not {
        confirmatory.data_url,
        confirmatory.split_url,
    }.intersection(requested)
    assert labels["dev-task"].row_ids == [4, 5]
    assert labels["dev-task"].labels == ["A", "B"]
    assert audit.confirmatory_resource_url_count == 0
    assert audit.confirmatory_payloads_downloaded is False
    assert audit.raw_payloads_redistributed is False

    requested.clear()
    replayed, replay_audit = prepare_development_labels(
        panel,
        report,
        tmp_path,
        fetch=fake_fetch,
    )
    assert requested == []
    assert replayed["dev-task"].label_hash == labels["dev-task"].label_hash
    assert replay_audit.audit_hash == audit.audit_hash


def test_arff_and_split_parser_are_deterministic() -> None:
    attributes, rows = _decode_arff(_arff_bytes())
    assert [item[0] for item in attributes] == ["feature", "class"]
    assert rows[4] == ["4", "A"]
    assert _split_test_rows(_split_bytes()) == [4, 5]


def test_runner_static_audit_rejects_network_import(tmp_path: Path) -> None:
    safe = tmp_path / "safe.py"
    unsafe = tmp_path / "unsafe.py"
    safe.write_text("import json\nprint(json.dumps({}))\n", encoding="utf-8")
    unsafe.write_text("import requests\nrequests.get('x')\n", encoding="utf-8")

    assert audit_frozen_runner_source(safe) is True
    assert audit_frozen_runner_source(unsafe) is False


def test_v2_runner_pins_v1_and_declares_mixed_type_pipeline() -> None:
    runner_path = Path(
        "src/autoresearch/research/assets/frozen_tabular_candidate_runner_v2.py"
    )
    source = runner_path.read_text(encoding="utf-8")

    assert audit_frozen_runner_source(runner_path) is True
    assert "LEGACY_RUNNER_SHA256" in source
    assert "SimpleImputer(strategy=\"most_frequent\")" in source
    assert 'handle_unknown="ignore"' in source
    assert "make_column_selector(dtype_include=np.number)" in source
    assert "make_column_selector(dtype_exclude=np.number)" in source


def _fake_freeze(policy_id: str) -> SimpleNamespace:
    policies = {item.policy_id: item for item in frozen_policy_realizations()}
    task_input = DevelopmentInput(
        unit_id="unit-1",
        opaque_unit_id="opaque-unit-1",
        family="tabular_classification",
        train_path="train.csv",
        test_path="test.csv",
        labels_path="labels.json",
        train_sha256="1" * 64,
        test_sha256="2" * 64,
        labels_sha256="3" * 64,
        label_hash="4" * 64,
        train_row_count=100,
        test_row_count=20,
        label_count=20,
        feature_count=4,
        data_sha256="5" * 64,
        split_sha256="6" * 64,
        baseline_score=0.50,
        metric_id="balanced_accuracy",
        minimum_gain=0.005,
        threshold_hash="7" * 64,
    )
    return SimpleNamespace(
        policies=[policies[policy_id]],
        inputs=[task_input],
        candidates=frozen_candidate_catalogue(),
        freeze_hash="8" * 64,
        budget_realization=SimpleNamespace(
            maximum_cpu_seconds_per_assignment=240,
            maximum_memory_mb=4096,
        ),
    )


def _fake_preregistration() -> SimpleNamespace:
    return SimpleNamespace(
        budget=SimpleNamespace(
            fidelity_stages=[
                SimpleNamespace(
                    stage_id="F1",
                    training_fraction=0.25,
                    maximum_seconds_per_candidate=10,
                ),
                SimpleNamespace(
                    stage_id="F2",
                    training_fraction=0.50,
                    maximum_seconds_per_candidate=20,
                ),
                SimpleNamespace(
                    stage_id="F3",
                    training_fraction=1.00,
                    maximum_seconds_per_candidate=60,
                ),
            ]
        )
    )


def _fake_evaluation(
    candidate,
    *,
    stage: str,
    seed: int,
    failed: bool = False,
) -> _EvaluationOutcome:
    if failed:
        evaluation = CandidateEvaluation.create(
            evaluation_id=f"eval-{candidate.candidate_id}-{stage}",
            unit_id="unit-1",
            opaque_unit_id="opaque-unit-1",
            within_unit_seed=seed,
            candidate_id=candidate.candidate_id,
            candidate_hash=candidate.candidate_hash,
            mechanism_family=candidate.mechanism_family,
            stage=stage,
            status=EvaluationStatus.FAILED,
            config_hash=SHA,
            command_hash="b" * 64,
            runner_source_hash="c" * 64,
            train_sha256="1" * 64,
            test_sha256="2" * 64,
            labels_sha256="3" * 64,
            metric_id="balanced_accuracy",
            cpu_seconds=0.1,
            wall_seconds=0.1,
            peak_rss_mb=10.0,
            maximum_seconds={"F1": 10, "F2": 20, "F3": 60}[stage],
            maximum_memory_mb=4096,
            artifact_valid=False,
            evaluator_integrity_valid=False,
            memory_valid=False,
            replay_required=stage == "F3",
            replay_exact=False if stage == "F3" else None,
            stdout_sha256="d" * 64,
            stderr_sha256="e" * 64,
            return_code=1,
            timed_out=False,
            failure_code="intentional_failure",
            failure_summary="retained negative control",
        )
    else:
        base = 0.60 + (
            int(candidate.candidate_hash[:4], 16) % 100
        ) / 10_000
        score = base + {"F1": 0.00, "F2": 0.01, "F3": 0.02}[stage]
        evaluation = CandidateEvaluation.create(
            evaluation_id=f"eval-{candidate.candidate_id}-{stage}",
            unit_id="unit-1",
            opaque_unit_id="opaque-unit-1",
            within_unit_seed=seed,
            candidate_id=candidate.candidate_id,
            candidate_hash=candidate.candidate_hash,
            mechanism_family=candidate.mechanism_family,
            stage=stage,
            status=EvaluationStatus.SUCCEEDED,
            config_hash=SHA,
            command_hash="b" * 64,
            runner_source_hash="c" * 64,
            train_sha256="1" * 64,
            test_sha256="2" * 64,
            labels_sha256="3" * 64,
            metric_id="balanced_accuracy",
            score=score,
            prediction_sha256="f" * 64,
            prediction_count=20,
            fit_row_count=80,
            evaluation_row_count=20,
            cpu_seconds=0.1,
            wall_seconds=0.1,
            peak_rss_mb=10.0,
            maximum_seconds={"F1": 10, "F2": 20, "F3": 60}[stage],
            maximum_memory_mb=4096,
            artifact_valid=True,
            evaluator_integrity_valid=True,
            memory_valid=True,
            replay_required=stage == "F3",
            replay_exact=True if stage == "F3" else None,
            result_file_sha256="9" * 64,
            replay_file_sha256="0" * 64 if stage == "F3" else None,
            stdout_sha256="d" * 64,
            stderr_sha256="e" * 64,
            return_code=0,
            timed_out=False,
        )
    return _EvaluationOutcome(evaluation, cache_reused=False)


def test_assignment_retains_full_f0_f3_matrix_and_budget(monkeypatch) -> None:
    freeze = _fake_freeze("portfolio_memory")
    assignment = DevelopmentAssignment.create(
        assignment_id="assignment-1",
        sequence_index=0,
        unit_id="unit-1",
        within_unit_seed=1729,
        policy_id="portfolio_memory",
        schedule_source="task-263.4.2-randomization",
    )

    def fake_execute(
        _freeze,
        _preregistration,
        _task_input,
        candidate,
        *,
        seed,
        stage,
        output_dir,
    ):
        del _freeze, _preregistration, _task_input, output_dir
        return _fake_evaluation(
            candidate,
            stage=stage,
            seed=seed,
            failed=candidate.intentional_failure_control,
        )

    monkeypatch.setattr(
        "autoresearch.research.development_search._execute_candidate",
        fake_execute,
    )
    result = _execute_assignment(
        freeze,
        _fake_preregistration(),
        assignment,
        {"F1": {}, "F2": {}},
        output_dir=Path("."),
    )
    replayed_after_interruption = _execute_assignment(
        freeze,
        _fake_preregistration(),
        assignment,
        {"F1": {}, "F2": {}},
        output_dir=Path("."),
        seen_evaluation_hashes=set(),
    )

    assert len(result.stage_records) == 48
    assert {
        stage: sum(item.stage == stage for item in result.stage_records)
        for stage in ("F0", "F1", "F2", "F3")
    } == {"F0": 12, "F1": 12, "F2": 12, "F3": 12}
    assert result.cost.requested_evaluations == {"F1": 6, "F2": 3, "F3": 1}
    assert result.cost.reserved_cpu_seconds == 180
    assert result.cost.proposal_model_calls == 0
    assert result.cost.within_budget is True
    invalid_f0 = next(
        item
        for item in result.stage_records
        if item.stage == "F0" and item.candidate_id == "invalid-schema-probe"
    )
    assert invalid_f0.status is StageRecordStatus.STATIC_REJECT
    assert result.prediction_replay_valid is True
    assert result.objective_task_success is True
    assert replayed_after_interruption.result_hash == result.result_hash


def _analysis_result(
    policy: PolicyRealization,
    unit_index: int,
    seed: int,
) -> SimpleNamespace:
    if policy.policy_id == "portfolio_memory":
        success = unit_index < 5
    elif policy.policy_id == "linear_self_loop":
        success = unit_index < 4
    else:
        success = unit_index < 3
    high = 0.50 + unit_index * 0.03 + (seed % 7) * 0.0001
    stage_records = [
        SimpleNamespace(
            stage="F1",
            candidate_id="selected",
            status=StageRecordStatus.EXECUTED,
            objective_score=high - 0.02,
        ),
        SimpleNamespace(
            stage="F2",
            candidate_id="selected",
            status=StageRecordStatus.EXECUTED,
            objective_score=high - 0.01,
        ),
    ]
    return SimpleNamespace(
        policy_id=policy.policy_id,
        unit_id=f"unit-{unit_index}",
        within_unit_seed=seed,
        objective_task_success=success,
        normalized_margin=2.0 if success else 0.0,
        failure_codes=[],
        artifact_valid=True,
        prediction_replay_valid=True,
        budget_valid=True,
        evaluator_integrity_valid=True,
        selected_candidate_id="selected",
        selected_candidate_family="family",
        policy_score=high,
        stage_records=stage_records,
        cost=SimpleNamespace(
            reserved_cpu_seconds=180,
            newly_executed_cpu_seconds=1.0,
            newly_executed_wall_seconds=1.0,
            peak_rss_mb=100.0,
        ),
    )


def test_analysis_uses_tasks_not_seeds_and_applies_holm() -> None:
    policies = frozen_policy_realizations()
    freeze = SimpleNamespace(
        inputs=[SimpleNamespace(unit_id=f"unit-{index}") for index in range(7)],
        policies=policies,
        minimum_development_task_successes=4,
        minimum_low_high_spearman=0.20,
    )
    results = [
        _analysis_result(policy, unit_index, seed)
        for policy in policies
        for unit_index in range(7)
        for seed in (1729, 3253, 7919)
    ]

    analysis = analyze_development_search(freeze, results)

    assert len(analysis.task_outcomes) == 9 * 7
    assert all(len(item.seed_successes) == 3 for item in analysis.task_outcomes)
    assert analysis.holm_family_size == 10
    assert len(analysis.arm_comparisons) == 6
    assert len(analysis.ablation_comparisons) == 5
    assert all(
        item.holm_adjusted_p is not None
        for item in [
            *[
                row
                for row in analysis.arm_comparisons
                if row.role == "secondary_arm"
            ],
            *analysis.ablation_comparisons,
        ]
    )
    portfolio_calibrations = [
        item
        for item in analysis.fidelity_calibrations
        if item.policy_id == "portfolio_memory"
    ]
    assert {item.pair_count for item in portfolio_calibrations} == {7}
    assert {item.analysis_unit for item in portfolio_calibrations} == {
        "independent task"
    }
    assert analysis.surviving_policy_ids == ["portfolio_memory"]


def test_tampered_evaluation_hash_is_rejected() -> None:
    candidate = frozen_candidate_catalogue()[0]
    evaluation = _fake_evaluation(
        candidate,
        stage="F1",
        seed=1729,
    ).evaluation
    payload = evaluation.model_dump(mode="json")
    payload["score"] = float(payload["score"]) + 0.1

    with pytest.raises(ValidationError, match="evaluation_hash mismatch"):
        CandidateEvaluation.model_validate(payload)
