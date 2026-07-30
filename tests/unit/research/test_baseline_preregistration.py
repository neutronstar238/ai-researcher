from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from autoresearch.kernel.contracts import canonical_sha256
from autoresearch.research.baseline_preregistration import (
    FROZEN_DEPENDENCY_VERSIONS,
    REQUIRED_BASELINE_SOURCE_KEYS,
    REQUIRED_DESIGN_SOURCE_KEYS,
    BaselineEnvironmentLock,
    BaselineGateStatus,
    BaselineReproductionReport,
    BaselineTaskReplay,
    CausalSearchPreregistration,
    CleanBaselineSpecification,
    PinnedDistribution,
    baseline_preregistration_json_schemas,
    build_frozen_randomization_schedule,
    load_baseline_preregistration,
    write_baseline_preregistration,
)
from autoresearch.research.objective_task_panel import (
    ObjectiveFamilyProbe,
    OpenObjectiveTaskPanelReport,
    OpenObjectiveTaskUnit,
    OpenTaskPanelStatus,
    panel_power_scenarios,
)
from autoresearch.research.objective_task_registry import (
    ObjectiveTaskFamily,
    PanelPartition,
    frozen_sources,
)
from autoresearch.research.portfolio import PortfolioIntegrityError
from autoresearch.research.search_policy_study import StudyAblation, StudyArm

DIAGNOSIS_HASH = "7c4d06eb82eabb250cf1b509242480bf27f079f65eaec6fbe564593c54b4aa3c"


def _sha(label: str) -> str:
    return canonical_sha256({"label": label})


def _panel() -> OpenObjectiveTaskPanelReport:
    units = [
        OpenObjectiveTaskUnit.create_from_source(
            source,
            target_feature=(
                "class" if source.family is ObjectiveTaskFamily.TABULAR_CLASSIFICATION else "target"
            ),
            estimation_procedure_id=(
                1 if source.family is ObjectiveTaskFamily.TABULAR_CLASSIFICATION else 7
            ),
            number_instances=500,
            number_features=10,
            upstream_metadata_hash=_sha(f"metadata-{source.task_id}"),
            evaluator_source_hash=_sha("objective-evaluator"),
            source_reference_found=True,
            anonymous_data_available=True,
            fixed_split_available=True,
        )
        for source in frozen_sources()
    ]
    probes: list[ObjectiveFamilyProbe] = []
    for family in ObjectiveTaskFamily:
        representative = next(
            unit
            for unit in units
            if unit.family is family and unit.partition is PanelPartition.DEVELOPMENT
        )
        score = 0.75 if family is ObjectiveTaskFamily.TABULAR_CLASSIFICATION else 0.25
        probes.append(
            ObjectiveFamilyProbe.create(
                probe_id=f"probe-{family.value}",
                family=family,
                representative_unit_id=representative.unit_id,
                data_sha256=_sha(f"data-{family.value}"),
                data_bytes=4096,
                split_sha256=_sha(f"split-{family.value}"),
                split_bytes=1024,
                license_evidence_sha256=_sha(f"license-{family.value}"),
                evaluator_source_hash=representative.evaluator_source_hash,
                evaluator_score=score,
                evaluator_replay_score=score,
                rows_evaluated=20,
                compute_seconds=0.01,
                data_md5_verified=True,
                split_verified=True,
                license_verified=True,
                task_metadata_verified=True,
            )
        )
    return OpenObjectiveTaskPanelReport.create(
        report_id="task-263.4.1-open-objective-panel",
        feasibility_diagnosis_hash=DIAGNOSIS_HASH,
        source_suite_snapshot_hashes={
            "openml-cc18": _sha("cc18-suite"),
            "openml-ctr23": _sha("ctr23-suite"),
        },
        evaluator_code_license_hash=_sha("apache-license"),
        task_units=units,
        family_probes=probes,
        power_scenarios=panel_power_scenarios(),
    )


def _environment() -> BaselineEnvironmentLock:
    distributions = [
        PinnedDistribution.create(
            name=name,
            version=version,
            filename=f"{name.replace('-', '_')}-{version}-py3-none-any.whl",
            wheel_sha256=_sha(f"wheel-{name}-{version}"),
            pypi_json_sha256=_sha(f"pypi-{name}-{version}"),
            license_id=f"license-{name}",
        )
        for name, version in FROZEN_DEPENDENCY_VERSIONS.items()
    ]
    return BaselineEnvironmentLock.create(
        python_version="3.10.20",
        platform_tag="win_amd64",
        base_interpreter_sha256=_sha("base-interpreter"),
        distributions=distributions,
    )


def _specification(
    panel: OpenObjectiveTaskPanelReport,
    environment: BaselineEnvironmentLock,
) -> CleanBaselineSpecification:
    return CleanBaselineSpecification.create_from_panel(
        panel,
        baseline_source_snapshot_hashes={key: _sha(key) for key in REQUIRED_BASELINE_SOURCE_KEYS},
        runner_source_hash=_sha("baseline-runner"),
        environment_hash=environment.environment_hash,
    )


def _replays(
    panel: OpenObjectiveTaskPanelReport,
    specification: CleanBaselineSpecification,
    environment: BaselineEnvironmentLock,
    *,
    mismatch_unit_id: str | None = None,
) -> list[BaselineTaskReplay]:
    unit_by_id = {unit.unit_id: unit for unit in panel.task_units}
    replays: list[BaselineTaskReplay] = []
    for index, unit_id in enumerate(specification.development_unit_ids):
        unit = unit_by_id[unit_id]
        prediction_a = _sha(f"predictions-{unit_id}")
        prediction_b = (
            _sha(f"mismatched-{unit_id}") if unit_id == mismatch_unit_id else prediction_a
        )
        score = 0.8 if unit.family is ObjectiveTaskFamily.TABULAR_CLASSIFICATION else 0.4
        replays.append(
            BaselineTaskReplay.create(
                replay_id=f"replay-{unit_id}",
                unit_id=unit_id,
                family=unit.family,
                metric_id=unit.objective_metric,
                data_sha256=_sha(f"data-{unit_id}"),
                split_sha256=_sha(f"split-{unit_id}"),
                input_bundle_hash=_sha(f"bundle-{unit_id}"),
                runner_source_hash=specification.runner_source_hash,
                environment_hash=environment.environment_hash,
                command_template_hash=_sha("baseline-command-template"),
                run_a_id=f"run-a-{unit_id}",
                run_b_id=f"run-b-{unit_id}",
                run_a_workspace_hash=_sha(f"workspace-a-{unit_id}"),
                run_b_workspace_hash=_sha(f"workspace-b-{unit_id}"),
                run_a_process_id=10_000 + index,
                run_b_process_id=20_000 + index,
                run_a_prediction_hash=prediction_a,
                run_b_prediction_hash=prediction_b,
                prediction_count=50,
                run_a_score=score,
                run_b_score=score,
                run_a_trial_count=12,
                run_b_trial_count=12,
                run_a_seconds=2.0,
                run_b_seconds=2.1,
                artifact_hashes={
                    f"{unit_id}/a-predictions.json": prediction_a,
                    f"{unit_id}/a-result.json": _sha(f"a-result-{unit_id}"),
                    f"{unit_id}/b-predictions.json": prediction_b,
                    f"{unit_id}/b-result.json": _sha(f"b-result-{unit_id}"),
                },
            )
        )
    return replays


def _reproduction(
    panel: OpenObjectiveTaskPanelReport,
    *,
    mismatch_unit_id: str | None = None,
) -> BaselineReproductionReport:
    environment = _environment()
    specification = _specification(panel, environment)
    return BaselineReproductionReport.create(
        report_id="task-263.4.2-clean-baseline",
        specification=specification,
        environment=environment,
        task_replays=_replays(
            panel,
            specification,
            environment,
            mismatch_unit_id=mismatch_unit_id,
        ),
        install_lock_verified=True,
        runner_static_network_audit_passed=True,
        workspace_roots_disjoint=True,
    )


def _preregistration(
    panel: OpenObjectiveTaskPanelReport,
    reproduction: BaselineReproductionReport,
) -> CausalSearchPreregistration:
    return CausalSearchPreregistration.create_from_reproduction(
        preregistration_id="task-263.4.2-search-policy-preregistration",
        panel=panel,
        reproduction=reproduction,
        design_source_snapshot_hashes={key: _sha(key) for key in REQUIRED_DESIGN_SOURCE_KEYS},
    )


def test_exact_environment_and_outcome_blind_specification_are_frozen() -> None:
    panel = _panel()
    environment = _environment()
    specification = _specification(panel, environment)

    assert panel.status is OpenTaskPanelStatus.READY_FOR_CLEAN_BASELINE
    assert {item.name: item.version for item in environment.distributions} == (
        FROZEN_DEPENDENCY_VERSIONS
    )
    assert environment.virtual_environment_count == 2
    assert environment.execution_network_allowed is False
    assert specification.estimator_list == [
        "lgbm",
        "xgboost",
        "rf",
        "extra_tree",
    ]
    assert len(specification.development_unit_ids) == 7
    assert len(specification.confirmatory_unit_ids) == 60
    assert specification.confirmatory_payloads_downloaded is False
    assert specification.public_benchmark_runs_queried is False
    assert specification.study_outcomes_observed is False


def test_reproduced_baseline_unlocks_complete_result_free_preregistration() -> None:
    panel = _panel()
    reproduction = _reproduction(panel)
    preregistration = _preregistration(panel, reproduction)

    assert reproduction.status is BaselineGateStatus.BASELINE_REPRODUCED
    assert len(reproduction.task_replays) == 7
    assert all(item.passed for item in reproduction.task_replays)
    assert preregistration.status is (BaselineGateStatus.READY_FOR_DEVELOPMENT_SEARCH)
    assert [item.arm for item in preregistration.arms] == list(StudyArm)
    assert [item.ablation for item in preregistration.ablations] == list(StudyAblation)
    assert len(preregistration.task_thresholds) == 60
    assert len(preregistration.randomization_assignments) == 67 * 3 * 4
    assert preregistration.primary_comparison == [
        StudyArm.PORTFOLIO_MEMORY,
        StudyArm.LINEAR_SELF_LOOP,
    ]
    assert preregistration.confirmatory_results_sealed is True
    assert preregistration.confirmatory_payloads_downloaded is False
    assert preregistration.result_record_count == 0
    assert preregistration.development_search_started is False
    assert preregistration.external_submission_authorized is False


def test_prediction_mismatch_blocks_preregistration_without_replacing_task() -> None:
    panel = _panel()
    mismatch_unit_id = panel.development_unit_ids[0]
    reproduction = _reproduction(
        panel,
        mismatch_unit_id=mismatch_unit_id,
    )

    assert reproduction.status is BaselineGateStatus.BLOCKED
    assert reproduction.blockers == ["baseline-task-replay-failed"]
    assert len(reproduction.task_replays) == 7
    with pytest.raises(ValueError, match="did not reproduce"):
        _preregistration(panel, reproduction)


def test_missing_or_confirmatory_replay_cannot_manufacture_development_coverage() -> None:
    panel = _panel()
    environment = _environment()
    specification = _specification(panel, environment)
    replays = _replays(panel, specification, environment)
    confirmatory = next(
        unit
        for unit in panel.task_units
        if unit.partition is PanelPartition.CONFIRMATORY and unit.family is replays[-1].family
    )
    replacement_payload = replays[-1].model_dump(mode="json")
    replacement_payload["unit_id"] = confirmatory.unit_id
    replacement = BaselineTaskReplay.create(**replacement_payload)
    replays[-1] = replacement

    report = BaselineReproductionReport.create(
        report_id="task-263.4.2-bad-coverage",
        specification=specification,
        environment=environment,
        task_replays=replays,
        install_lock_verified=True,
        runner_static_network_audit_passed=True,
        workspace_roots_disjoint=True,
    )
    assert report.status is BaselineGateStatus.BLOCKED
    assert "development-replay-coverage-failed" in report.blockers


def test_thresholds_are_paired_formulas_not_observed_confirmation_scores() -> None:
    panel = _panel()
    preregistration = _preregistration(panel, _reproduction(panel))

    classification = next(
        item
        for item in preregistration.task_thresholds
        if item.family is ObjectiveTaskFamily.TABULAR_CLASSIFICATION
    )
    regression = next(
        item
        for item in preregistration.task_thresholds
        if item.family is ObjectiveTaskFamily.TABULAR_REGRESSION
    )
    assert classification.minimum_gain == 0.005
    assert classification.threshold_expression.endswith("balanced_accuracy + 0.005")
    assert regression.minimum_gain == 0.01
    assert regression.threshold_expression.endswith("r2 + 0.010")
    assert all(
        not item.baseline_score_observed and not item.policy_score_observed
        for item in preregistration.task_thresholds
    )


def test_randomization_is_deterministic_blocked_and_seed_repeats_are_not_units() -> None:
    panel = _panel()
    first = build_frozen_randomization_schedule(panel)
    second = build_frozen_randomization_schedule(panel)

    assert [item.model_dump(mode="json") for item in first] == [
        item.model_dump(mode="json") for item in second
    ]
    keys = {(item.unit_id, item.within_unit_seed, item.arm) for item in first}
    assert len(keys) == 67 * 3 * 4
    assert {item.benchmark_id for item in first} == {
        "openml-cc18",
        "openml-ctr23",
    }
    for unit_id in panel.confirmatory_unit_ids:
        assert (
            len({(item.within_unit_seed, item.arm) for item in first if item.unit_id == unit_id})
            == 3 * 4
        )


def test_nested_tamper_and_result_reveal_fail_closed() -> None:
    panel = _panel()
    preregistration = _preregistration(panel, _reproduction(panel))
    preregistration.task_thresholds[0].minimum_gain = 0.0
    with pytest.raises(PortfolioIntegrityError, match="threshold_hash"):
        preregistration.verify_integrity()

    payload = _preregistration(
        panel,
        _reproduction(panel),
    ).model_dump(mode="json")
    payload["result_record_count"] = 1
    with pytest.raises(ValidationError):
        CausalSearchPreregistration.model_validate(payload)


def test_round_trip_manifest_schemas_and_file_tamper_are_verified(
    tmp_path: Path,
) -> None:
    panel = _panel()
    reproduction = _reproduction(panel)
    preregistration = _preregistration(panel, reproduction)

    manifest = write_baseline_preregistration(
        tmp_path,
        reproduction,
        preregistration,
    )
    loaded_report, loaded_preregistration, loaded_manifest = load_baseline_preregistration(tmp_path)
    assert loaded_report.report_hash == reproduction.report_hash
    assert loaded_preregistration.preregistration_hash == preregistration.preregistration_hash
    assert loaded_manifest.manifest_hash == manifest.manifest_hash
    schemas = baseline_preregistration_json_schemas()
    assert set(schemas) == {
        "BaselineEnvironmentLock",
        "BaselinePreregistrationManifest",
        "BaselineReproductionReport",
        "BaselineTaskReplay",
        "CausalArmBudget",
        "CausalSearchPreregistration",
        "CleanBaselineSpecification",
        "FrozenAblationProtocol",
        "FrozenArmProtocol",
        "FrozenTaskSuccessThreshold",
        "PinnedDistribution",
    }
    assert schemas["CausalSearchPreregistration"]["additionalProperties"] is False

    path = tmp_path / "causal-preregistration.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["operator_grammar"][0] = "post-result operator"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises((PortfolioIntegrityError, ValidationError)):
        load_baseline_preregistration(tmp_path)
